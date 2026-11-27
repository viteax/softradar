"""Строки КП, экономика сделки и скоринг. Только код, без LLM: цифрам в КП можно доверять."""

import re
from datetime import date, timedelta

from .catalog import Catalog, pick_variant
from .config import Settings
from .filters import now_msk, vendor_of
from .models import KpLine, Tender


async def build_lines(analysis: dict, catalog: Catalog) -> list[KpLine]:
    lines: list[KpLine] = []
    for item in analysis.get("items") or []:
        name = str(item.get("name") or "").strip()
        try:
            qty = max(1, int(item.get("qty") or 1))
        except TypeError, ValueError:
            qty = 1
        hint = " ".join(str(item.get(k) or "") for k in ("license_type", "term_months"))
        if item.get("term_months"):
            hint += f" {item['term_months']} мес"
        line = KpLine(request_name=name, qty=qty)
        url = str(item.get("catalog_url") or "")
        note = ""
        if "store.softline.ru" not in url and name:
            # агент не нашел – код пробует поиск по названию позиции сам
            found = await catalog.search(re.sub(r"[«»\"]", "", name)[:80], limit=1)
            if found:
                url, note = found[0]["url"], "подобрано автоматически по названию – проверить"
        if "store.softline.ru" in url:
            variants = await catalog.variants(url)
            v = pick_variant(variants, qty, hint)
            if v:
                line.sku, line.name, line.unit_price = v.sku, v.name, v.price
                line.vat_rate, line.url, line.matched = v.vat_rate, v.family_url, True
                in_range = (v.min_qty or 1) <= qty <= (v.max_qty or 10**9)
                if not in_range:
                    note = (
                        note + "; " if note else ""
                    ) + f"артикул на {v.min_qty}–{v.max_qty} шт., нужно {qty}"
        if not line.matched:
            note = note or "нет в каталоге store.softline.ru"
        line.note = note
        lines.append(line)
    return lines


def economics(t: Tender, analysis: dict, lines: list[KpLine], s: Settings) -> dict:
    total = round(sum(x.total for x in lines), 2)
    vat = round(sum(x.vat_amount for x in lines), 2)
    nmc = analysis.get("nmc_rub") or t.price
    try:
        nmc = float(nmc) if nmc else None
    except TypeError, ValueError:
        nmc = None
    vendor = vendor_of(f"{analysis.get('vendor', '')} {t.title} {' '.join(x.name for x in lines)}") or "other"
    disc = s.discounts.get(vendor, s.discounts.get("other", 0.15))
    cost = round(total * (1 - disc), 2)  # оценка закупочной цены: розница каталога минус скидка партнера
    offer = total
    note = ""
    if nmc and total > nmc:
        offer, note = nmc, "цена каталога выше НМЦ – КП по НМЦ, скидка за счет маржи"
    margin = round(offer - cost, 2) if total else 0.0
    margin_pct = round(margin / offer, 4) if offer else 0.0
    validity = max(int(analysis.get("kp_validity_days") or 0), 30)
    return {
        "total_catalog": total,
        "vat": vat,
        "nmc": nmc,
        "offer_total": round(offer, 2),
        "discount_assumed": disc,
        "vendor_key": vendor,
        "cost_est": cost,
        "margin": margin,
        "margin_pct": margin_pct,
        "note": note,
        "valid_until": (date.today() + timedelta(days=validity)).isoformat(),
        "validity_days": validity,
    }


def score(t: Tender, a: dict, lines: list[KpLine], eco: dict, s: Settings) -> tuple[float, str, list[str]]:
    """0–100, вердикт fit | partial | reject и объяснение – каждое слагаемое видно менеджеру."""
    why: list[str] = []
    gates = {
        "закупка ПО": a.get("is_software_purchase") is not False,
        "подача КП без конкурса": a.get("procedure_simplified") is not False,
        "не только для МСП": not a.get("msp_only") and not t.msp_only,
        f"сумма до {s.max_price:,.0f} ₽".replace(",", " "): not (eco["nmc"] and eco["nmc"] > s.max_price)
        and eco["offer_total"] <= s.max_price,
    }
    failed = [k for k, ok in gates.items() if not ok]
    pts = 40.0
    if failed:
        why += [f"✗ {k}" for k in failed]
        return 0.0, "reject", why
    why.append("✓ критерии отбора: ПО, без конкурса, не МСП, до лимита (+40)")
    matched = sum(1 for x in lines if x.matched)
    if lines and matched == len(lines):
        pts += 20
        why.append("✓ все позиции найдены в каталоге (+20)")
    elif matched:
        pts += 8
        why.append(f"~ найдено {matched} из {len(lines)} позиций (+8)")
    else:
        why.append("✗ позиции не найдены в каталоге")
    if vendor_of(f"{a.get('vendor', '')} {t.title}"):
        pts += 10
        why.append("✓ ключевой вендор Softline (+10)")
    mp = eco["margin_pct"]
    if mp >= s.min_margin:
        add = min(15, round(mp * 60))
        pts += add
        why.append(f"✓ оценка маржи {mp:.0%} (+{add})")
    elif eco["total_catalog"]:
        why.append(f"✗ маржа {mp:.0%} ниже порога {s.min_margin:.0%}")
    if a.get("prepayment"):
        pts += 5
        why.append("✓ предоплата (+5)")
    elif (a.get("payment_days") or 0) > 30:
        pts -= 10
        why.append(f"✗ постоплата {a.get('payment_days')} дн. (−10)")
    if t.deadline:
        hours = (t.deadline - now_msk()).total_seconds() / 3600
        if hours >= 72:
            pts += 5
            why.append("✓ до дедлайна больше 3 дней (+5)")
        elif hours < 24:
            pts -= 10
            why.append("✗ до дедлайна меньше суток (−10)")
    if a.get("has_tz"):
        pts += 5
        why.append("✓ есть ТЗ (+5)")
    pts = max(0.0, min(100.0, pts))
    full = (
        lines
        and matched == len(lines)
        and mp >= s.min_margin
        and not any("нет в каталоге" in x.note for x in lines)
    )
    verdict = "fit" if full else "partial"
    return pts, verdict, why
