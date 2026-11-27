"""Заполненный калькулятор экономики решения (структура шаблона «ИИкузница 2026 – калькулятор экономики»).

Токены – замер на стенде: средние по закупкам, разобранным агентом (kp.prompt_tokens/completion_tokens).
Запуск: uv run python docs/make_cost.py <prompt_tokens> <completion_tokens> <requests> <tenders_per_day>
"""

import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

p_in, p_out, calls, per_day = (float(x) for x in sys.argv[1:5])
PRICE = (
    500.0  # ₽ за 1 млн токенов с НДС: GigaChat Pro, 0,5 ₽ / 1000 токенов (developers.sber.ru, тарифы юрлиц)
)

wb = Workbook()
ws = wb.active
ws.title = "Калькулятор"
ws["A1"] = "ИИкузница 2026 – калькулятор экономики решения · СофтРадар (команда «Менталисты»)"
ws["A1"].font = Font(bold=True, size=13)
ws["A2"] = "Суммы в рублях. «Запрос» = разбор одной закупки агентом (от карточки до черновика КП)."
ws["A3"] = "Курс доллара не нужен: цены GigaChat в рублях."
ws["A5"] = "Модели на один запрос"
ws["A5"].font = Font(bold=True, color="C8102E")
head = [
    "Шаг агента",
    "Модель",
    "Вызовов на запрос",
    "Токенов на входе",
    "Токенов на выходе",
    "Цена входа за 1 млн",
    "Цена выхода за 1 млн",
    "Валюта",
    "₽ на 1 запрос",
]
ws.append([])
ws.append(head)
for c in ws[7]:
    c.font = Font(bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor="C8102E")
    c.alignment = Alignment(wrap_text=True, vertical="center")
share = {
    "read_document – чтение документов закупки": 0.45,
    "search_catalog / get_variants – подбор в каталоге": 0.35,
    "submit_analysis – структурированный итог": 0.20,
}
r = 8
for step, k in share.items():
    ws.append(
        [
            step,
            "GigaChat-3-Pro (тариф Pro)",
            round(calls * k, 1),
            round(p_in * k),
            round(p_out * k),
            PRICE,
            PRICE,
            "₽",
            None,
        ]
    )
    ws[f"I{r}"] = f"=(D{r}*F{r}+E{r}*G{r})/1000000"
    r += 1
ws.append(["Итого модели на 1 запрос"] + [None] * 7)
ws[f"I{r}"] = f"=SUM(I8:I{r - 1})"
ws[f"A{r}"].font = ws[f"I{r}"].font = Font(bold=True)
r += 2
ws[f"A{r}"] = "Инфраструктура и масштаб"
ws[f"A{r}"].font = Font(bold=True, color="C8102E")
rows = [
    ("Закупок, разбираемых агентом в день", per_day),
    ("LLM в месяц, ₽ (30 дней)", f"=I{r - 2}*B{r + 1}*30"),
    ("VPS 2 vCPU / 2 ГБ (доля под сервис), ₽ в месяц", 500),
    ("Итого в месяц, ₽", f"=B{r + 2}+B{r + 3}"),
    ("Стоимость одного запроса с инфраструктурой, ₽", f"=B{r + 4}/(B{r + 1}*30)"),
    ("Ручной мониторинг: 3 ч/нед × 15 площадок × 800 ₽/ч, ₽ в месяц", "=3*15*800*4.3"),
]
for i, (k, v) in enumerate(rows, start=1):
    ws[f"A{r + i}"], ws[f"B{r + i}"] = k, v
r += len(rows) + 2
ws[f"A{r}"] = "Комментарий: допущения, ссылки на прайсы, затраты на свои серверы"
ws[f"A{r}"].font = Font(bold=True, color="C8102E")
ws[f"A{r + 1}"] = (
    "Токены – средние по закупкам, разобранным агентом на стенде softradar.iptvik.ru (usage из ответов "
    "GigaChat). Цена – GigaChat Pro 0,5 ₽/1000 токенов с НДС, вход и выход по одной цене "
    "(developers.sber.ru/docs/ru/gigachat/tariffs/legal-tariffs)."
)
ws[f"A{r + 2}"] = (
    "Сбор с площадок, фильтры, подбор артикулов, расчет КП и маржи – код без LLM, на том же VPS. "
    "Агент вызывается только для закупок, прошедших фильтры (~15–20% найденных)."
)
ws[f"A{r + 3}"] = (
    "Что может изменить цифры: длинные ТЗ (до 40 тыс. символов читаются частями), смена модели "
    "(GigaChat Lite – 0,065 ₽/1000, в 7,7 раза дешевле), рост числа площадок."
)
for col, w in zip("ABCDEFGHI", [52, 26, 12, 14, 14, 14, 14, 9, 14], strict=True):
    ws.column_dimensions[col].width = w
wb.save(sys.argv[5] if len(sys.argv) > 5 else "docs/softradar_cost.xlsx")
print("ok")
