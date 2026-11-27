"""Росэлторг (roseltorg.ru): поиск процедур и карточка с документами. Только открытые страницы, без входа."""

import re
from urllib.parse import urljoin

import httpx2
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..models import Doc, Tender
from . import clean, get, money, ru_datetime

BASE = "https://www.roseltorg.ru"
NAME = "roseltorg"


def parse_search(html: str) -> list[Tender]:
    tree = HTMLParser(html)
    out = []
    for card in tree.css("div.search-results__item"):
        number = card.attributes.get("data-feature-favorite-lots-procedure-number") or ""
        link = card.css_first("a.search-results__link--description")
        if not number or not link:
            continue
        lot = card.attributes.get("data-feature-favorite-lots-lot-number") or "1"
        price_el = card.css_first(".search-results__sum p.desktop") or card.css_first(".search-results__sum")
        text = clean(card.text(separator=" "))
        dl = re.search(r"Окончание приема заявок\s*([\d.]+\s*в\s*[\d:]+)", text)
        section = (
            clean(card.css_first(".search-results__section").text())
            if card.css_first(".search-results__section")
            else ""
        )
        customer_el = card.css_first(".search-results__customer a")
        out.append(
            Tender(
                source=NAME,
                number=f"{number}/{lot}" if lot != "1" else number,
                url=urljoin(BASE, link.attributes.get("href") or ""),
                title=clean(link.text()),
                customer=clean(customer_el.text()) if customer_el else "",
                price=money(price_el.text()) if price_el else None,
                procedure_type=clean(card.css_first(".search-results__type").text())
                if card.css_first(".search-results__type")
                else "",
                status=clean(card.css_first(".search-results__status").text())
                if card.css_first(".search-results__status")
                else "",
                deadline=ru_datetime(dl.group(1)) if dl else None,
                section=section,
                region=clean(card.css_first(".search-results__region").text())
                if card.css_first(".search-results__region")
                else "",
                law="44-ФЗ" if re.fullmatch(r"\d{19}", number) else "",
                tags=[clean(a.text()) for a in card.css(".procedure-tags a")],
            )
        )
    return out


async def search(http: httpx2.AsyncClient, query: str, pages: int, max_price: float) -> list[Tender]:
    found: list[Tender] = []
    for page in range(pages):
        params = [
            ("query_field", query),
            ("end_price", str(int(max_price))),
            ("status[]", "0"),  # прием заявок
            ("status[]", "5"),  # ожидание приема заявок
            ("currency", "all"),
            ("page", str(page)),
        ]
        r = await get(http, f"{BASE}/procedures/search", params=params)
        items = parse_search(r.text)
        found += items
        if len(items) < 10:
            break
    return found


def parse_detail(html: str, t: Tender) -> Tender:
    tree = HTMLParser(html)
    for bad in tree.css("script, style, header, footer, nav"):
        bad.decompose()
    text = tree.body.text(separator="\n") if tree.body else ""
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    # полезная часть – от начала карточки до блока рекламных сервисов площадки
    end = text.find("Сервисы для торгов")
    start = max(0, text.find(t.number.split("/")[0]) - 300)
    t.page_text = text[start : end if end > start else start + 12000][:12000]
    docs = []
    for a in tree.css("a"):
        href = a.attributes.get("href") or ""
        if "/file/get/" in href and any(
            k in href for k in ("LotDocuments", "RequestDocs", "NoticeDocuments")
        ):
            name = clean(a.text()) or href.rsplit("/", 1)[-1]
            if "Скачать все" in name:
                continue
            docs.append(Doc(name=name, url=href))
    seen = set()
    t.docs = [d for d in docs if not (d.url in seen or seen.add(d.url))]
    m = re.search(r"Прием заявок\s*до\s*([\d.]+\s*[\d:]+)", t.page_text)
    if m and not t.deadline:
        t.deadline = ru_datetime(m.group(1))
    m = re.search(r"Способ проведения\s*\n?\s*([^\n]+)", t.page_text)
    if m and not t.procedure_type:
        t.procedure_type = clean(m.group(1))
    low = t.page_text.lower()
    if re.search(
        r"только\s+субъект\w*\s+мал\w+|участник\w*\s+.{0,40}только\s+.{0,20}мсп|только для мсп", low
    ):
        t.msp_only = True
    elif t.msp_only is None and "мсп" not in low:
        t.msp_only = False
    return t


async def detail(http: httpx2.AsyncClient, t: Tender) -> Tender:
    r = await get(http, t.url)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return parse_detail(r.text, t)
