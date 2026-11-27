"""Сравнение моделей GigaChat на одних и тех же закупках (копия БД, стенд не трогает).

docker exec softradar python scripts/compare_models.py GigaChat-3-Pro GigaChat-3-Ultra -- key1 key2 ...
"""

import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

from app.agent import Agent
from app.catalog import Catalog
from app.config import Settings
from app.db import DB
from app.gigachat import GigaChat
from app.models import Tender
from app.pricing import build_lines, economics, score
from app.sources import client


async def main() -> None:
    i = sys.argv.index("--")
    models, keys = sys.argv[1:i], sys.argv[i + 1 :]
    s = Settings()
    tmp = Path("/tmp/cmp.db")
    src = sqlite3.connect(s.data_dir / "softradar.db")
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    src.close()
    dst.close()
    db = DB(tmp)
    http = client()
    catalog = Catalog(http, db)
    out = []
    for model in models:
        giga = GigaChat(s.giga_auth_key, s.giga_scope, model, s.giga_oauth_url, s.giga_api_url)
        agent = Agent(giga, http, db, catalog)
        for key in keys:
            row = db.tender(key)
            t = Tender.from_dict(row["data"])
            t0 = time.time()
            try:
                res = await agent.analyze(t)
            except Exception as e:  # noqa: BLE001
                out.append({"model": model, "key": key, "error": str(e)[:200]})
                print(model, key, "ERROR", e, flush=True)
                continue
            a = res.analysis or {}
            lines = await build_lines(a, catalog)
            eco = economics(t, a, lines, s)
            pts, verdict, _ = score(t, a, lines, eco, s)
            rec = {
                "model": model,
                "key": key,
                "sec": round(time.time() - t0, 1),
                "requests": res.requests,
                "prompt": res.prompt_tokens,
                "completion": res.completion_tokens,
                "decision": a.get("decision"),
                "verdict": verdict,
                "score": round(pts),
                "kp_validity": a.get("kp_validity_days"),
                "payment_days": a.get("payment_days"),
                "contract": a.get("contract_format"),
                "items": [(x.get("name", "")[:60], x.get("qty")) for x in a.get("items") or []],
                "skus": [(x.sku, x.qty) for x in lines],
                "offer": eco.get("offer_total"),
                "error": res.error,
            }
            out.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
        await giga.aclose()
    Path("/tmp/cmp.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    await http.aclose()


asyncio.run(main())
