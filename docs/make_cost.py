"""Заполненный калькулятор экономики решения (структура шаблона «ИИкузница 2026 – калькулятор экономики»).

Токены – замер на стенде и скриптом scripts/compare_models.py (средние на одну закупку).
Цены – каталог cloud.ru Evolution Foundation Models (коммерческий доступ к GigaChat с 01.12.2026), ₽ за 1 млн токенов.
Запуск: uv run python docs/make_cost.py
"""

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

PER_DAY = 40  # закупок, прошедших фильтры и разобранных агентом, в день
# основная модель: GigaChat Ultra (замер Pro vs Ultra на 10 закупках: 17,8 тыс. вход / 0,54 тыс. выход, 4,9 вызова)
MAIN = ("GigaChat Ultra 3.5 (цена cloud.ru GigaChat3.5-432B-A28B)", 4.9, 17820, 542, 96.22, 288.6)
ALTS = [
    ("GigaChat-3-Pro (cloud.ru)", 6.3, 14789, 525, 73.03, 176.39),
    ("GigaChat-4-708B-A41 (cloud.ru, сейчас бесплатно)", 4.9, 17820, 542, 0.0, 0.0),
    ("GigaChat Pro по тарифу юрлиц developers.sber.ru (до 30.11.2026)", 6.3, 14789, 525, 500.0, 500.0),
]
SHARE = {
    "read_document – чтение документов закупки": 0.45,
    "search_catalog / get_variants – подбор в каталоге": 0.35,
    "submit_analysis – структурированный итог": 0.20,
}

RED = "C8102E"
wb = Workbook()
ws = wb.active
ws.title = "Калькулятор"
ws["A1"] = "ИИкузница 2026 – калькулятор экономики решения · СофтРадар (команда «Менталисты»)"
ws["A1"].font = Font(bold=True, size=13)
ws["A2"] = "Суммы в рублях с НДС. «Запрос» = разбор одной закупки агентом (от карточки до черновика КП)."
ws["A3"] = "Курс доллара не нужен: цены моделей в рублях."
ws["A5"] = "Модели на один запрос"
ws["A5"].font = Font(bold=True, color=RED)
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
    c.fill = PatternFill("solid", fgColor=RED)
    c.alignment = Alignment(wrap_text=True, vertical="center")
name, calls, p_in, p_out, c_in, c_out = MAIN
r = 8
for step, k in SHARE.items():
    ws.append([step, name, round(calls * k, 1), round(p_in * k), round(p_out * k), c_in, c_out, "₽", None])
    ws[f"I{r}"] = f"=(D{r}*F{r}+E{r}*G{r})/1000000"
    r += 1
total_row = r
ws.append(["Итого модели на 1 запрос"] + [None] * 7)
ws[f"I{r}"] = f"=SUM(I8:I{r - 1})"
ws[f"A{r}"].font = ws[f"I{r}"].font = Font(bold=True)

r += 2
ws[f"A{r}"] = "Инфраструктура и масштаб"
ws[f"A{r}"].font = Font(bold=True, color=RED)
rows = [
    ("Закупок, разбираемых агентом в день", PER_DAY),
    ("LLM в месяц, ₽ (30 дней)", f"=I{total_row}*B{r + 1}*30"),
    ("VPS 2 vCPU / 2 ГБ (доля под сервис), ₽ в месяц", 500),
    ("Итого в месяц, ₽", f"=B{r + 2}+B{r + 3}"),
    ("Стоимость одного запроса с инфраструктурой, ₽", f"=B{r + 4}/(B{r + 1}*30)"),
    (
        "Для сравнения: ручной мониторинг 15 площадок, 3 ч/нед на площадку × 800 ₽/ч, ₽ в месяц",
        "=3*15*800*4.3",
    ),
]
for i, (k, v) in enumerate(rows, start=1):
    ws[f"A{r + i}"], ws[f"B{r + i}"] = k, v
r += len(rows) + 2

ws[f"A{r}"] = "Сравнение моделей (тот же агент, замер на одних и тех же 10 закупках)"
ws[f"A{r}"].font = Font(bold=True, color=RED)
r += 1
for j, h in enumerate(
    ["Модель", "", "Вызовов", "Вход", "Выход", "Цена входа", "Цена выхода", "", "₽ на 1 запрос"]
):
    ws.cell(row=r, column=j + 1, value=h).font = Font(bold=True)
for alt in [MAIN] + ALTS:
    r += 1
    n, cl, a, b, x, y = alt
    ws[f"A{r}"], ws[f"C{r}"], ws[f"D{r}"], ws[f"E{r}"], ws[f"F{r}"], ws[f"G{r}"] = n, cl, a, b, x, y
    ws[f"I{r}"] = f"=(D{r}*F{r}+E{r}*G{r})/1000000"
r += 2

ws[f"A{r}"] = "Комментарий: допущения, ссылки на прайсы, затраты на свои серверы"
ws[f"A{r}"].font = Font(bold=True, color=RED)
notes = [
    "Токены – usage из ответов API: средние по 10 закупкам, разобранным одним и тем же агентом на Pro и Ultra "
    "(scripts/compare_models.py), и по закупкам на стенде softradar.iptvik.ru.",
    "Цены – каталог cloud.ru Evolution Foundation Models (cloud.ru/products/evolution-ai-factory/catalog-foundation-models, "
    "27.11.2026): GigaChat3.5-432B-A28B 96,22 / 288,6 ₽, GigaChat-3-Pro 73,03 / 176,39 ₽, GigaChat-4-708B-A41 бесплатно.",
    "Допущение: GigaChat Ultra в API Сбера = GigaChat 3.5 (в кабинете Studio помечено «Ultra 3.5»), поэтому цена Ultra "
    "взята по GigaChat3.5-432B на cloud.ru. Тариф юрлиц developers.sber.ru (Pro 0,5 ₽/1000) действует до 30.11.2026.",
    "Ultra выбрана по замеру: на 10 закупках точнее Pro (верный продукт и количество в 6 случаях из 10, хуже – ни разу), "
    "вдвое быстрее (6,4 с против 12,1 с) и меньше вызовов (4,9 против 6,3).",
    "Сбор с площадок, фильтры, подбор артикулов, расчет КП и маржи – код без LLM, на том же VPS. Агент вызывается "
    "только для закупок, прошедших фильтры (~18% найденных). Провайдер и модель меняются в .env без правки кода.",
]
for i, t in enumerate(notes, start=1):
    ws[f"A{r + i}"] = t
for col, w in zip("ABCDEFGHI", [60, 34, 11, 12, 12, 13, 13, 8, 14], strict=True):
    ws.column_dimensions[col].width = w
wb.save("docs/softradar_cost.xlsx")
print("ok", round((p_in * c_in + p_out * c_out) / 1e6, 2), "₽ на запрос")
