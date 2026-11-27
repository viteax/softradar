"""Жесткие критерии заказчика – детерминированно, до LLM: дешево и проверяемо.

Критерии (задача Softline): ПО; сумма до 1 млн ₽; упрощенная подача КП без конкурсной процедуры;
исключить закупки только для МСП. Что нельзя решить по карточке (НМЦ не указана, МСП неизвестно), –
пропускаем дальше, решает агент по документам.
"""

import re
from datetime import datetime, timedelta, timezone

from .config import KEY_VENDORS
from .models import Tender

MSK = timezone(timedelta(hours=3))

# Упрощенная подача КП – без торгов с переторжкой и конкурсной комиссией
SIMPLIFIED = [
    "мониторинг цен",
    "запрос котировок",
    "запрос цен",
    "запрос предложений",
    "запрос ткп",
    "запрос кп",
    "коммерческ",
    "малого объема",
    "малых закупок",
    "малая закупка",
    "упрощенн",
    "котировочн",
    "интернет-магазин",
    "ценов",
    "сбор предложений",
    "rfi",
    "rfq",
    "закупка у единственного",
]
COMPETITIVE = ["аукцион", "конкурс", "переторжк", "продажа", "публичного предложения"]

SOFTWARE = [
    "программн",
    "лиценз",
    "неисключительн",
    "права использования",
    "право использования",
    " по)",
    "софт",
    "антивирус",
    "операционн",
    "subscription",
    "подписк",
    "сертификат",
    "технической поддержк",
    "средств защиты",
    "сзи",
    "скзи",
    "межсетев",
    "офисн",
]
NOT_SOFTWARE = [
    "разработк",
    "внедрени",
    "сопровождени",
    "строительн",
    "ремонт",
    "монтаж",
    "поставка оборудования",
    "картридж",
    "мебел",
    "компьютерн техник",
    "ноутбук",
    "сервер ",
    "обучени",
]


def now_msk() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)


def vendor_of(text: str) -> str:
    low = text.lower()
    for key, words in KEY_VENDORS.items():
        if any(w in low for w in words):
            return key
    return ""


def procedure_kind(t: Tender) -> str:
    """simplified | competitive | unknown – по названию способа закупки и заголовку."""
    s = f"{t.procedure_type} {t.title[:120]}".lower()
    if any(w in s for w in COMPETITIVE):
        return "competitive"
    if any(w in s for w in SIMPLIFIED):
        return "simplified"
    return "unknown"


def is_software(t: Tender) -> bool:
    s = f" {t.title} {' '.join(t.tags)} ".lower()
    if vendor_of(s):
        return True
    soft = sum(1 for w in SOFTWARE if w in s)
    hard = sum(1 for w in NOT_SOFTWARE if w in s)
    return soft > 0 and soft >= hard


def check(t: Tender, max_price: float) -> tuple[bool, list[str]]:
    """(проходит ли в анализ, причины отказа/предупреждения)."""
    reasons: list[str] = []
    ok = True
    if t.price is not None and t.price > max_price:
        ok = False
        reasons.append(f"НМЦ {t.price:,.0f} ₽ больше лимита {max_price:,.0f} ₽".replace(",", " "))
    kind = procedure_kind(t)
    if kind == "competitive":
        ok = False
        reasons.append(f"конкурсная процедура: {t.procedure_type}")
    if t.msp_only or re.search(r"\bмсп\b|субъект\w* мал", t.procedure_type.lower()):
        ok = False
        reasons.append("только для МСП")
    if t.deadline and t.deadline < now_msk() + timedelta(hours=2):
        ok = False
        reasons.append("прием КП закончился или заканчивается в ближайшие 2 часа")
    if not is_software(t):
        ok = False
        reasons.append("не похоже на закупку ПО")
    if ok and kind == "unknown":
        reasons.append("способ закупки неясен – уточнит агент")
    if ok and t.price is None:
        reasons.append("НМЦ не указана – оценим по каталогу")
    return ok, reasons
