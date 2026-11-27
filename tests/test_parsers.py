from pathlib import Path

from app.catalog import parse_search as catalog_search
from app.catalog import parse_variants, pick_variant
from app.docs import extract
from app.sources import fabrikant, money, roseltorg, ru_datetime

F = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (F / name).read_text(encoding="utf-8")


def test_roseltorg_search_and_detail():
    items = roseltorg.parse_search(read("roseltorg_search.html"))
    assert len(items) == 10
    atom = next(t for t in items if t.number == "ATOM27112600434")
    assert atom.procedure_type == "Мониторинг цен"
    assert atom.deadline and atom.deadline.day == 1
    d = roseltorg.parse_detail(read("roseltorg_detail.html"), atom)
    assert [x.name for x in d.docs][:2] == ["Запрос ЭТКП.docx", "Прил № 1 Техническое задание.docx"]
    assert "ATOM27112600434" in d.page_text


def test_fabrikant_search():
    items = fabrikant.parse_search(read("fabrikant_search.html"))
    assert len(items) == 10
    first = items[0]
    assert first.price == 2789901.27
    assert first.msp_only is True
    assert first.law == "44-ФЗ"


def test_catalog():
    fams = catalog_search(read("softline_search.html"))
    assert fams[0]["url"].startswith("https://store.softline.ru/kaspersky/")
    vs = parse_variants(read("softline_product.html"), "u")
    assert len(vs) == 8
    v = pick_variant(vs, 120, "продление")
    assert v and v.min_qty <= 120 <= v.max_qty


def test_docx_text():
    text = extract((F / "tz.docx").read_bytes(), "tz.docx")
    assert "Kaspersky EDR" in text


def test_helpers():
    assert money("10 080 000,00 ₽") == 10080000.0
    assert money("0,00") is None
    assert ru_datetime("01.12.26 23:59").year == 2026
