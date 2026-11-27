"""Фабрикант (fabrikant.ru): поиск закупок. Страница – Next.js, но карточки отрисованы на сервере."""

import re

import httpx2
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from ..models import Doc, Tender
from . import clean, get, money, ru_datetime

BASE = "https://www.fabrikant.ru"
NAME = "fabrikant"
LAWS = ("44-ФЗ", "223-ФЗ")


def parse_search(html: str) -> list[Tender]:
    tree = HTMLParser(html)
    out = []
    for card in tree.css("div[data-slot=card][data-id]"):
        links = [a for a in card.css("a") if "fabrikant.ru" in (a.attributes.get("href") or "")]
        if not links:
            continue
        title_a = max(links, key=lambda a: len(a.text()))
        parts = [clean(p) for p in card.text(separator="|").split("|")]
        parts = [p for p in parts if p]
        text = " ".join(parts)
        badges = [clean(b.text()) for b in card.css("[data-slot=badge]")]
        num = re.search(r"№\s*(\d+)\s*(-\d+)?", text)
        price = re.search(r"([\d\s\xa0]+,\s*\d{2})\s*RUB", text)
        dl = re.search(r"Дата окончания при[её]ма заявок\s*([\d.]+\s*[\d:]+)", text)
        pub = re.search(r"Дата публикации\s*([\d.]+\s*[\d:]+)", text)
        cust = re.search(r"Заказчик\s+(.+?)(?:\s+\.\.\.|\s+Дата публикации|$)", text)
        org = re.search(r"Организатор\s+(.+?)\s+(?:Заказчик|Дата публикации)", text)
        law = next((x for x in LAWS if any(x in b for b in badges)), "коммерческая")
        out.append(
            Tender(
                source=NAME,
                number=(num.group(1) + (num.group(2) or "")) if num else card.attributes.get("data-id", ""),
                url=title_a.attributes.get("href") or "",
                title=clean(title_a.text()),
                customer=clean((cust or org).group(1)) if (cust or org) else "",
                price=money(price.group(1)) if price else None,
                procedure_type=parts[0] if parts else "",
                status=next((b for b in badges if "заяв" in b.lower() or "заверш" in b.lower()), ""),
                deadline=ru_datetime(dl.group(1)) if dl else None,
                published=ru_datetime(pub.group(1)) if pub else None,
                law=law,
                section=", ".join(badges),
                msp_only="МСП" in badges or "только субъекты малого" in text.lower(),
            )
        )
    return out


async def search(http: httpx2.AsyncClient, query: str, pages: int, max_price: float) -> list[Tender]:
    found: list[Tender] = []
    for page in range(1, pages + 1):
        r = await get(http, f"{BASE}/procedure/search/purchases", params={"query": query, "page": page})
        items = parse_search(r.text)
        found += items
        if len(items) < 10:
            break
    return found


def _text(html: str) -> tuple[HTMLParser, str]:
    tree = HTMLParser(html)
    for bad in tree.css("script, style, header, footer, nav"):
        bad.decompose()
    text = tree.body.text(separator="\n") if tree.body else ""
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return tree, re.sub(r"\n\s*\n+", "\n", text)


def _abs(r: httpx2.Response, href: str) -> str:
    return str(r.url.join(href))


async def detail(http: httpx2.AsyncClient, t: Tender) -> Tender:
    r = await get(http, t.url)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    tree, text = _text(r.text)
    start = max(0, text.find(t.title[:40]) - 300) if t.title else 0
    t.page_text = text[start : start + 9000]
    docs: list[Doc] = []
    links = {(a.attributes.get("href") or ""): clean(a.text()) for a in tree.css("a")}
    for href, name in links.items():
        if re.search(r"\.(docx?|pdf|xlsx?|rtf)(\?|$)", href, re.I) or "/download" in href:
            docs.append(Doc(name=name or href.rsplit("/", 1)[-1], url=_abs(r, href)))
    # секции «trades/<площадка>/<Тип>/?action=view»: позиции и документы – на отдельных страницах
    for href in links:
        if "action=view_positions" in href or "action=product_requirements_view" in href:
            try:
                _, ptext = _text((await get(http, _abs(r, href))).text)
                i = ptext.find("Наименование")
                t.page_text += "\n\n[Позиции закупки]\n" + ptext[max(0, i - 200) : max(0, i - 200) + 4000]
            except Exception:  # noqa: BLE001 – позиции необязательны
                pass
    doc_page = next((h for h in links if "file_documentations_view" in h), "")
    if doc_page:
        try:
            dr = await get(http, _abs(r, doc_page))
            for a in HTMLParser(dr.text).css("a"):
                href = a.attributes.get("href") or ""
                if "file_documentations_get_file" in href:
                    name = clean(a.text()).strip("_ ") or "документ"
                    docs.append(
                        Doc(name=f"Документация закупки {len(docs) + 1} ({name})", url=_abs(dr, href))
                    )
        except Exception:  # noqa: BLE001
            pass
    seen: set[str] = set()
    t.docs = [d for d in docs if not (d.url in seen or seen.add(d.url))][:15]
    if t.msp_only is None and "только субъект" in text.lower():
        t.msp_only = True
    if t.price is None:
        m = re.search(r"(?:Общая цена|Начальная цена|НМЦ)[^\d]{0,40}([\d\s\xa0]+,\d{2})\s*руб", text)
        if m:
            t.price = money(m.group(1))
    return t
