"""Каталог store.softline.ru: поиск семейств товаров и артикулы с ценами.

Поиск – серверная страница /search/?query=; артикулы – JSON window.temporaryFrontConfig на странице
товара (familyFilteredProducts: sku, цена, мин./макс. количество, НДС, срок поставки). Кэш – 12 часов.
"""

import json
import re
from urllib.parse import quote, urljoin

import httpx2
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from .db import DB
from .models import Variant
from .sources import clean, get, money

BASE = "https://store.softline.ru"
TTL = 12 * 3600


def parse_search(html: str, limit: int = 8) -> list[dict]:
    tree = HTMLParser(html)
    out = []
    for item in tree.css("div.b-product-item"):
        a = item.css_first("a.b-product-item__description") or item.css_first("a.js-ecommerce-link")
        if not a:
            continue
        href = (a.attributes.get("href") or "").split("?")[0]
        vendor = item.css_first(".b-product-item__vendor")
        text = clean(item.text(separator=" "))
        price = re.search(r"От\s*([\d\s\xa0]+(?:,\d+)?)\s*₽", text) or re.search(
            r"([\d\s\xa0]+(?:,\d+)?)\s*₽", text
        )
        out.append(
            {
                "name": clean(a.attributes.get("title") or a.text()),
                "vendor": clean(vendor.text()).strip("«»") if vendor else "",
                "url": urljoin(BASE, href),
                "from_price": money(price.group(1)) if price else None,
            }
        )
        if len(out) >= limit:
            break
    return out


def parse_variants(html: str, family_url: str) -> list[Variant]:
    m = re.search(r"window\.temporaryFrontConfig\s*=\s*(\{.*?\});?\s*</script>", html, re.S)
    if not m:
        return []
    try:
        cfg = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    out = []
    for p in cfg.get("familyFilteredProducts") or []:
        price = money(str(p.get("priceWithDiscount") or p.get("priceWithoutDiscount") or ""))
        if not price:
            continue
        out.append(
            Variant(
                sku=p.get("sku") or "",
                name=clean(p.get("name")),
                config=clean(p.get("shortConfiguration")),
                price=price,
                min_qty=p.get("minQuantity"),
                max_qty=p.get("maxQuantity"),
                vat=str(p.get("vat") or "0"),
                delivery_days=p.get("deliveryDays"),
                family_url=family_url,
                vendor=clean(p.get("vendorName")).strip("«»"),
            )
        )
    return out


class Catalog:
    def __init__(self, http: httpx2.AsyncClient, db: DB):
        self.http, self.db = http, db

    async def _page(self, url: str) -> str:
        cached = self.db.cache_get("page:" + url, TTL)
        if cached is not None:
            return cached
        r = await get(self.http, url)
        r.raise_for_status()
        self.db.cache_put("page:" + url, r.text)
        return r.text

    async def search(self, query: str, limit: int = 8) -> list[dict]:
        html = await self._page(f"{BASE}/search/?query={quote(query)}")
        return parse_search(html, limit)

    async def variants(self, family_url: str) -> list[Variant]:
        """Все артикулы семейства: страница по умолчанию показывает один тип лицензии (обычно продление),
        остальные типы (новая, миграция…) – отдельными запросами с фильтром конфигуратора."""
        if not family_url.startswith(BASE):
            family_url = urljoin(BASE, family_url)
        url = family_url.split("?")[0]
        html = await self._page(url)
        found = {v.sku: v for v in parse_variants(html, url)}
        for name, value, _label in parse_filters(html, "license_type")[:4]:
            try:
                extra = await self._page(f"{url}?{quote(name)}={value}")
            except Exception:  # noqa: BLE001 – доп. варианты необязательны
                continue
            for v in parse_variants(extra, url):
                found.setdefault(v.sku, v)
        return list(found.values())


def parse_filters(html: str, kind: str) -> list[tuple[str, str, str]]:
    """Значения фильтра конфигуратора: [(имя поля, значение, подпись)], kind – data-ecommerce_name."""
    tree = HTMLParser(html)
    out = []
    for inp in tree.css("input.js-configurer-btn"):
        a = inp.attributes
        if a.get("data-ecommerce_name") == kind and a.get("name") and a.get("value"):
            out.append((a["name"], a["value"], a.get("data-ecommerce_value") or ""))
    return out


def pick_variant(variants: list[Variant], qty: int, hint: str = "") -> Variant | None:
    """Артикул под количество и пожелания (продление/новая, срок): код, а не модель, выбирает цену.

    Сначала – подходящие по диапазону количества, затем – по совпадению слов подсказки с конфигурацией.
    """
    if not variants:
        return None
    words = [w for w in re.findall(r"\w+", hint.lower()) if len(w) > 2]

    def fits(v: Variant) -> bool:
        lo = v.min_qty or 1
        hi = v.max_qty or 10**9
        return lo <= qty <= hi

    def overlap(v: Variant) -> int:
        cfg = (v.config + " " + v.name).lower()
        return sum(1 for w in words if w in cfg)

    pool = [v for v in variants if fits(v)] or variants
    return max(pool, key=lambda v: (overlap(v), -v.price))
