"""Черновик КП по шаблону ПАО «Софтлайн» (docx) и отчет менеджеру (xlsx).

Печать и подпись в черновик не ставятся: КП уходит менеджеру на проверку, подписывает он.
"""

import io
from datetime import date

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

RED = RGBColor(0xC8, 0x10, 0x2E)


def rub(x: float | None) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") if x is not None else "–"


def _p(doc, text: str = "", size: int = 10, bold: bool = False, align=None, color=None):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.size, r.bold = Pt(size), bold
    if color:
        r.font.color.rgb = color
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(2)
    return p


def kp_docx(tender: dict, analysis: dict, kp: dict) -> bytes:
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Arial", Pt(10)
    for s in doc.sections:
        s.left_margin = s.right_margin = Pt(50)

    _p(doc, "ЧЕРНОВИК – на проверку менеджеру перед подачей", 9, True, WD_ALIGN_PARAGRAPH.RIGHT, RED)
    head = doc.add_table(rows=1, cols=2)
    left, right = head.rows[0].cells
    left.paragraphs[0].add_run("softline").font.size = Pt(26)
    left.paragraphs[0].runs[0].bold = True
    left.paragraphs[0].runs[0].font.color.rgb = RED
    for line in (
        "119021, город Москва, ул Льва Толстого, д. 5 стр. 1, этаж 3, помещ. 1, ком. №2, 2а (а-311)",
        "Т +7 495 232 00 23 | info@softline.com",
        "www.softline.ru | www.softline.com",
    ):
        r = left.add_paragraph().add_run(line)
        r.font.size = Pt(8)
    rp = right.paragraphs[0]
    rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    rp.add_run(f"Куда: {tender.get('customer') or '[Наименование заказчика]'}").font.size = Pt(10)
    p2 = right.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p2.add_run(f"Исх. № бн от {date.today():%d.%m.%Y}").font.size = Pt(10)
    p3 = right.add_paragraph()
    p3.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p3.add_run(f"на закупку № {tender.get('number')}").font.size = Pt(8)

    _p(doc)
    _p(doc, "Уважаемый заказчик!", 11, True, WD_ALIGN_PARAGRAPH.CENTER)
    _p(
        doc,
        "ПАО «Софтлайн» предлагает Вашему вниманию коммерческое предложение на следующих условиях:",
        10,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )

    lines = kp.get("lines") or []
    t = doc.add_table(rows=1, cols=6)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, h in zip(
        t.rows[0].cells,
        ["Артикул", "Наименование", "Кол-во", "Цена, руб.", "Сумма, руб.", "В т.ч. НДС, руб."],
        strict=True,
    ):
        cell.text = ""
        r = cell.paragraphs[0].add_run(h)
        r.bold, r.font.size = True, Pt(9)
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    eco = kp.get("economics") or {}
    # если цена каталога выше НМЦ – КП по НМЦ: цены строк пропорционально снижаются
    k = (eco.get("offer_total") or 0) / eco["total_catalog"] if eco.get("total_catalog") else 1
    total = vat_total = 0.0
    for ln in lines:
        unit = round(ln["unit_price"] * k, 2)
        s = round(unit * ln["qty"], 2)
        vat = round(s * ln["vat_rate"] / (1 + ln["vat_rate"]), 2) if ln["vat_rate"] else 0
        total += s
        vat_total += vat
        row = t.add_row().cells
        vals = [
            ln["sku"] or "–",
            ln["name"] or ln["request_name"],
            str(ln["qty"]),
            rub(unit),
            rub(s),
            rub(vat) if vat else "без НДС",
        ]
        for cell, v in zip(row, vals, strict=True):
            cell.text = ""
            cell.paragraphs[0].add_run(v).font.size = Pt(9)
    row = t.add_row().cells
    row[1].text = ""
    row[1].paragraphs[0].add_run("Итого").bold = True
    row[4].text = rub(total)
    row[5].text = rub(vat_total) if vat_total else "без НДС"

    _p(doc)
    pay = analysis.get("payment_terms") or ("Предоплата" if analysis.get("prepayment") else "Постоплата")
    for line in (
        "Цена указана с учетом всех налогов, сборов и других обязательных платежей."
        + (" Лицензии на ПО НДС не облагаются (пп. 26 п. 2 ст. 149 НК РФ)." if not vat_total else ""),
        f"Условия оплаты: {pay}.",
        f"Срок поставки: {analysis.get('delivery_term') or 'в течение 5 рабочих дней с даты заключения договора'}.",
        f"Срок действия коммерческого предложения – до {_ru_date(eco.get('valid_until'))}.",
    ):
        _p(doc, line, 10)
    _p(doc)
    _p(doc)
    _p(doc, "[Должность, ФИО ответственного менеджера]", 10)
    _p(doc, "[Подпись]   [Печать]", 9, color=RGBColor(0x88, 0x88, 0x88))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _ru_date(iso: str | None) -> str:
    if not iso:
        return "[Дата]"
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


VERDICT = {"fit": "Подходит – КП готово", "partial": "Частично – проверить", "reject": "Не подходит"}


def report_xlsx(rows: list[dict]) -> bytes:
    """Отчет менеджеру по брифингу: наверху «5 из 5», затем по вердикту, баллу и близости срока подачи."""
    from .pricing import conditions

    prepared = []
    for r in rows:
        a, d, kp = r.get("analysis") or {}, r["data"], r.get("kp") or {}
        conds = kp.get("conditions") or conditions(d, a, kp.get("lines") or [], r.get("verdict") or "")
        ok = sum(1 for _, v in conds if v)
        prepared.append((r, a, d, kp, conds, ok))
    rank = {"fit": 0, "partial": 1, "reject": 2}
    prepared.sort(
        key=lambda x: (
            -x[5],
            rank.get(x[0].get("verdict") or "", 3),
            -(x[0].get("score") or 0),
            x[2].get("deadline") or "9",
        )
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Закупки"
    head = [
        "Условий из 5",
        "Не выполнено",
        "Балл",
        "Вердикт",
        "Прием КП до",
        "Предмет",
        "Позиции и артикулы",
        "Заказчик",
        "ИНН заказчика",
        "НМЦ, ₽",
        "Сумма КП, ₽",
        "Маржа, %",
        "Оплата",
        "Предоплата",
        "Постоплата, дн.",
        "Формат договора",
        "ТЗ",
        "Срок действия КП, дн.",
        "Вендор",
        "Почему так (агент)",
        "Риски",
        "Площадка",
        "Номер",
        "Ссылка на процедуру",
    ]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="C8102E")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    green, yellow = PatternFill("solid", fgColor="D9F2D9"), PatternFill("solid", fgColor="FFF4CC")
    for r, a, d, kp, conds, ok in prepared:
        eco = kp.get("economics") or {}
        items = [
            f"{x.get('request_name', '')[:80]} × {x.get('qty')}"
            + (f" → {x['sku']}" if x.get("matched") else " → не найдено")
            for x in kp.get("lines") or []
        ] or [f"{i.get('name', '')[:80]} × {i.get('qty')}" for i in a.get("items") or []]
        ws.append(
            [
                f"{ok} из 5",
                "; ".join(n for n, v in conds if not v),
                round(r.get("score") or 0),
                VERDICT.get(r.get("verdict") or "", "не проанализирована"),
                (d.get("deadline") or "").replace("T", " ")[:16],
                d["title"],
                "\n".join(items),
                d.get("customer"),
                a.get("customer_inn"),
                eco.get("nmc") or d.get("price"),
                eco.get("offer_total"),
                round((eco.get("margin_pct") or 0) * 100, 1) if eco else None,
                a.get("payment_terms"),
                {True: "да", False: "нет"}.get(a.get("prepayment"), "?"),
                a.get("payment_days"),
                a.get("contract_format"),
                {True: "есть", False: "нет"}.get(a.get("has_tz"), "?"),
                a.get("kp_validity_days"),
                a.get("vendor"),
                (a.get("decision_reason") or "") + ("\n" + a["summary"] if a.get("summary") else ""),
                "; ".join(a.get("risks") or []),
                d["source"],
                d["number"],
                d["url"],
            ]
        )
        fill = green if ok == 5 else yellow if ok >= 3 else None
        if fill:
            ws.cell(row=ws.max_row, column=1).fill = fill
        ws.cell(row=ws.max_row, column=24).hyperlink = d["url"]
    widths = [9, 40, 7, 16, 16, 50, 55, 35, 13, 13, 13, 9, 40, 10, 10, 16, 6, 10, 14, 60, 45, 11, 18, 40]
    for i, w in enumerate(widths):
        ws.column_dimensions[ws.cell(row=1, column=i + 1).column_letter].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
