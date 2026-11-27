"""Конвейер: площадки → жесткие фильтры → карточка и документы → агент → КП, экономика, скоринг."""

import asyncio
import collections
import json
import logging
import re
import time
from dataclasses import asdict

from . import filters
from .agent import Agent
from .catalog import Catalog
from .config import Settings
from .db import DB
from .gigachat import GigaChat, GigaChatError
from .models import Tender
from .pricing import build_lines, economics, score
from .sources import client, fabrikant, roseltorg

log = logging.getLogger(__name__)
SOURCES = {"roseltorg": roseltorg, "fabrikant": fabrikant}


class Pipeline:
    def __init__(self, s: Settings, db: DB):
        self.s, self.db = s, db
        self.http = client()
        self.catalog = Catalog(self.http, db)
        self.giga = (
            GigaChat(s.giga_auth_key, s.giga_scope, s.giga_model, s.giga_oauth_url, s.giga_api_url)
            if s.llm_ready
            else None
        )
        self.agent = Agent(self.giga, self.http, db, self.catalog) if self.giga else None
        self.lock = asyncio.Lock()
        self.log: collections.deque[str] = collections.deque(maxlen=200)
        self.progress = ""

    def say(self, text: str) -> None:
        log.info(text)
        self.progress = text
        self.log.appendleft(f"{time.strftime('%H:%M:%S')} {text}")

    @property
    def running(self) -> bool:
        return self.lock.locked()

    # --- сбор ---
    async def collect(self) -> dict[str, Tender]:
        found: dict[str, Tender] = {}
        for name in self.s.sources:
            mod = SOURCES.get(name)
            if not mod:
                continue
            for q in self.s.queries:
                try:
                    items = await mod.search(self.http, q, self.s.pages_per_query, self.s.max_price)
                except Exception as e:  # noqa: BLE001 – одна площадка не должна ронять прогон
                    self.say(f"{name}: «{q}» – ошибка {e}")
                    continue
                for t in items:
                    found.setdefault(t.key, t)
                self.say(f"{name}: «{q}» – {len(items)} шт., всего уникальных {len(found)}")
                await asyncio.sleep(1.2)  # бережно к площадкам
        return found

    async def enrich(self, t: Tender) -> Tender:
        await asyncio.sleep(1.5)  # площадки отвечают 429 на частые запросы карточек
        try:
            t = await SOURCES[t.source].detail(self.http, t)
        except Exception as e:  # noqa: BLE001
            self.say(f"{t.key}: карточка недоступна – {e}")
        return t

    # --- анализ ---
    async def analyze(self, key: str) -> dict:
        row = self.db.tender(key)
        if not row:
            raise KeyError(key)
        t = Tender.from_dict(row["data"])
        if not self.agent:
            self.db.save_analysis(key, {"summary": "LLM не настроен (GIGACHAT_AUTH_KEY)"}, [], {}, 0, "", 0)
            return {}
        if not t.page_text or not t.docs:
            t = await self.enrich(t)
            ok, reasons = filters.check(t, self.s.max_price)
            manual = "добавлена вручную" in (row.get("filter_reasons") or [])
            self.db.upsert_tender(
                t.to_dict(), ok or manual, reasons + (["добавлена вручную"] if manual else [])
            )
            if not ok and not manual:
                self.say(f"{t.key}: после чтения карточки не проходит фильтр – {', '.join(reasons)}")
                return {}
        self.say(f"агент разбирает {t.key}: {t.title[:70]}")
        try:
            res = await self.agent.analyze(t)
        except GigaChatError as e:
            self.say(f"{t.key}: GigaChat – {e}")
            return {}
        a = res.analysis or {"summary": res.error or "агент не вернул результат", "items": []}
        lines = await build_lines(a, self.catalog)
        eco = economics(t, a, lines, self.s)
        pts, verdict, why = score(t, a, lines, eco, self.s)
        if res.error:
            verdict = "partial" if verdict != "reject" else verdict
            why.append(f"✗ {res.error}")
        kp = {
            "lines": [asdict(x) | {"total": x.total} for x in lines],
            "economics": eco,
            "why": why,
            "requests": res.requests,
        }
        self.db.save_analysis(key, a, res.trace, kp, pts, verdict, res.tokens)
        self.say(
            f"{t.key}: {verdict}, {pts:.0f} баллов, {res.tokens} токенов, {res.requests} запросов к модели"
        )
        return kp

    async def run(self, analyze_limit: int | None = None) -> dict:
        if self.lock.locked():
            return {"error": "уже идет прогон"}
        async with self.lock:
            started = time.time()
            run_id = self.db.x("INSERT INTO runs(started) VALUES (?)", (started,))
            stats = {"found": 0, "new": 0, "passed": 0, "analyzed": 0, "fit": 0, "tokens": 0}
            try:
                self.say("сбор закупок с площадок")
                found = await self.collect()
                stats["found"] = len(found)
                for t in found.values():
                    ok, reasons = filters.check(t, self.s.max_price)
                    known = self.db.tender(t.key)
                    if ok and not (known and known["data"].get("page_text")):
                        t = await self.enrich(t)
                        ok, reasons = filters.check(t, self.s.max_price)
                    elif known:
                        t.page_text, t.docs = (
                            known["data"].get("page_text", ""),
                            Tender.from_dict(known["data"]).docs,
                        )
                    stats["new"] += self.db.upsert_tender(t.to_dict(), ok, reasons)
                    stats["passed"] += ok
                self.say(f"прошли фильтры {stats['passed']} из {stats['found']}; анализ агентом")
                limit = self.s.max_analyze_per_run if analyze_limit is None else analyze_limit
                for row in self.db.to_analyze(limit):
                    kp = await self.analyze(row["key"])
                    stats["analyzed"] += 1
                    done = self.db.tender(row["key"]) or {}
                    stats["fit"] += done.get("verdict") == "fit"
                    stats["tokens"] += done.get("tokens") or 0
                    del kp
                self.say(f"готово: {json.dumps(stats, ensure_ascii=False)}")
                self.db.x(
                    "UPDATE runs SET finished=?, stats=? WHERE id=?", (time.time(), json.dumps(stats), run_id)
                )
            except Exception as e:  # noqa: BLE001
                log.exception("прогон упал")
                self.say(f"прогон упал: {e}")
                self.db.x(
                    "UPDATE runs SET finished=?, stats=?, error=? WHERE id=?",
                    (time.time(), json.dumps(stats), str(e), run_id),
                )
            return stats

    async def add_by_url(self, url: str) -> str:
        """Разобрать закупку по ссылке (менеджер прислал сам). Возвращает ключ."""
        url = url.strip()
        if "roseltorg.ru/procedure/" in url:
            m = re.search(r"/procedure/([^/?#]+)", url)
            t = Tender(source="roseltorg", number=m.group(1) if m else url, url=url, title="")
        elif "fabrikant.ru" in url:
            t = Tender(
                source="fabrikant", number=re.sub(r"\W+", "-", url.split("//")[-1])[-40:], url=url, title=""
            )
        else:
            raise ValueError("поддерживаются ссылки roseltorg.ru/procedure/… и fabrikant.ru")
        t = await self.enrich(t)
        if not t.title:
            m = re.search(r"Наименование процедуры\s*\n([^\n]+)", t.page_text)
            t.title = m.group(1).strip() if m else t.page_text[:120]
        ok, reasons = filters.check(t, self.s.max_price)
        self.db.upsert_tender(t.to_dict(), True, reasons + ["добавлена вручную"])
        return t.key

    async def loop(self) -> None:
        await asyncio.sleep(15)
        while True:
            try:
                await self.run()
            except Exception:  # noqa: BLE001
                log.exception("фоновый прогон")
            await asyncio.sleep(self.s.run_interval_min * 60)
