"""Площадки. Каждая – модуль с async search(http, query, pages) и async detail(http, tender)."""

import asyncio
import logging
import re
from datetime import datetime

import httpx2

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)


def client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        headers={"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"},
        timeout=httpx2.Timeout(30, connect=10),
        follow_redirects=True,
    )


async def get(http: httpx2.AsyncClient, url: str, **kw) -> httpx2.Response:
    """GET с двумя повторами на сетевые сбои и 5xx; площадки иногда отвечают 503."""
    last: Exception | None = None
    for delay in (0, 2, 5):
        if delay:
            await asyncio.sleep(delay)
        try:
            r = await http.get(url, **kw)
            if r.status_code < 500:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        except httpx2.TransportError as e:
            last = e
    raise RuntimeError(f"{url}: {last}")


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def money(s: str) -> float | None:
    """«10 080 000,00 ₽» → 10080000.0; 0 и пусто → None (НМЦ не указана)."""
    s = re.sub(r"[^\d,.]", "", s.replace("\xa0", "")).replace(",", ".")
    if s.count(".") > 1:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        v = float(s)
    except ValueError:
        return None
    return v or None


def ru_datetime(s: str) -> datetime | None:
    """«07.12.2026 в 11:00», «01.12.26 23:59», «07.12.2026 06:00» → datetime (время МСК, без зоны)."""
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{2,4})(?:\D{1,4}(\d{1,2}):(\d{2}))?", s or "")
    if not m:
        return None
    d, mo, y, h, mi = m.groups()
    y = int(y) + (2000 if len(y) == 2 else 0)
    try:
        return datetime(y, int(mo), int(d), int(h or 23), int(mi or 59))
    except ValueError:
        return None
