"""Текст документов закупки (ТЗ, запрос КП, проект договора): docx, doc, xlsx, pdf, rtf, txt. Кэш – в БД."""

import io
import logging
import re
import zipfile

import httpx2

from .db import DB
from .sources import get

log = logging.getLogger(__name__)
MAX_BYTES = 8 * 1024 * 1024
MAX_CHARS = 40000


def _docx(data: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"</w:tc>", " | ", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    rows = []
    for ws in wb.worksheets[:3]:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c not in (None, "")]
            if cells:
                rows.append(" | ".join(cells))
            if len(rows) > 400:
                break
    return "\n".join(rows)


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:20])


def _rtf(data: bytes) -> str:
    t = data.decode("cp1251", "ignore")
    t = re.sub(r"\'([0-9a-f]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1251", "ignore"), t)
    t = re.sub(r"\[a-z]+-?\d* ?|[{}]", " ", t)
    return t


def _ole_text(data: bytes) -> str:
    """Старый Word .doc (OLE): текст хранится в UTF-16LE – вытаскиваем длинные текстовые прогоны."""
    runs = re.findall(rb"(?:[\x20-\x7e\x0d\x09]\x00|[\x00-\xff]\x04){8,}", data)
    return "\n".join(r.decode("utf-16le", "ignore") for r in runs)


def extract(data: bytes, name: str) -> str:
    low = name.lower()
    head = data[:8]
    try:
        if head.startswith(b"%PDF") or low.endswith(".pdf"):
            return _pdf(data)
        if head.startswith(b"PK"):
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
            if "word/document.xml" in names:
                return _docx(data)
            if any(n.startswith("xl/") for n in names):
                return _xlsx(data)
            return f"[архив: {', '.join(names[:20])}]"
        if head.startswith(b"\xd0\xcf\x11\xe0"):
            return _ole_text(data)
        if head.startswith(b"{\rtf"):
            return _rtf(data)
        if low.endswith((".txt", ".csv", ".xml", ".html")):
            return data.decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001 – битый файл не должен ронять анализ
        return f"[не удалось прочитать {name}: {type(e).__name__}]"
    return f"[формат не поддерживается: {name}]"


def tidy(text: str) -> str:
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:MAX_CHARS]


async def fetch_text(http: httpx2.AsyncClient, db: DB, url: str, name: str) -> str:
    key = "doc:" + url
    cached = db.cache_get(key, 7 * 24 * 3600)
    if cached is not None:
        return cached
    try:
        r = await get(http, url)
        if r.status_code != 200:
            return f"[документ недоступен: HTTP {r.status_code}]"
        data = r.content[:MAX_BYTES]
    except Exception as e:  # noqa: BLE001
        return f"[документ недоступен: {e}]"
    text = tidy(extract(data, name))
    db.cache_put(key, text)
    return text


VALIDITY = re.compile(
    r"срок\w*\s+действия\s+(?:\w+\s+){0,4}?(?:предложени|кп|ткп|цен)\w*[^.\d]{0,80}?(?:не\s+менее|не\s+мене|≥|от)\s*"
    r"(\d{1,3})\s*\(?[^)]{0,30}\)?\s*(?:календарн\w+\s+|рабоч\w+\s+)?(дн|день|дне|мес)",
    re.I,
)


PAYMENT = re.compile(
    r"оплат\w*[^.;\n]{0,120}?в\s+течени[еи]\s+(\d{1,3})\s*\(?[^)]{0,25}\)?\s*(?:рабочих|календарных|банковских)?\s*дн\w*"
    r"[^.;\n]{0,80}",
    re.I,
)


def extract_conditions(text: str) -> dict:
    """Резерв для агента: минимальный срок действия КП и формат договора по типовым формулировкам."""
    out: dict = {}
    m = VALIDITY.search(text or "")
    if m:
        n = int(m.group(1))
        out["kp_validity_days"] = n * 30 if m.group(2).lower().startswith("мес") else n
    pay = PAYMENT.search(text or "")
    if pay:
        out["payment_terms"] = re.sub(r"\s+", " ", pay.group(0)).strip(" ,;.")
        out["payment_days"] = int(pay.group(1))
        out["prepayment"] = bool(re.search(r"предоплат|аванс", pay.group(0), re.I))
    low = (text or "").lower()
    if "проект договора" in low or "проект контракта" in low:
        out["contract_format"] = "шаблон заказчика"
    return out
