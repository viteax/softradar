from datetime import timedelta

from app.config import Settings
from app.filters import check, now_msk
from app.kp import kp_docx
from app.models import KpLine, Tender
from app.pricing import economics, score


def tender(**kw) -> Tender:
    base = dict(
        source="roseltorg",
        number="X1",
        url="u",
        title="Лицензии Kaspersky Endpoint Security",
        procedure_type="Мониторинг цен",
        deadline=now_msk() + timedelta(days=5),
    )
    return Tender(**(base | kw))


def test_filters():
    s = Settings()
    assert check(tender(), s.max_price)[0]
    assert not check(tender(price=2_000_000), s.max_price)[0]
    assert not check(tender(procedure_type="Электронный аукцион"), s.max_price)[0]
    assert not check(tender(procedure_type="Запрос котировок МСП"), s.max_price)[0]
    assert not check(tender(title="Поставка мебели"), s.max_price)[0]


def test_economics_and_score():
    s = Settings()
    t = tender(price=300000)
    lines = [KpLine(request_name="KES", qty=100, sku="KL1", name="KES", unit_price=1800, matched=True)]
    a = {
        "decision": "подавать КП",
        "vendor": "Kaspersky",
        "has_tz": True,
        "kp_validity_days": 60,
    }
    eco = economics(t, a, lines, s)
    assert eco["total_catalog"] == 180000
    assert eco["margin_pct"] == 0.25
    pts, verdict, why = score(t, a, lines, eco, s)
    assert verdict == "fit" and pts > 70
    assert (
        score(t, a | {"decision": "не подавать", "decision_reason": "аукцион"}, lines, eco, s)[1] == "reject"
    )
    a2 = a | {"msp_only": True}
    assert score(t, a2, lines, eco, s)[1] == "reject"
    doc = kp_docx(t.to_dict(), a, {"lines": [vars(lines[0]) | {"total": 180000}], "economics": eco})
    assert doc[:2] == b"PK"


def test_conditions_five():
    from app.pricing import conditions

    d = {"deadline": "2099-01-01T10:00:00"}
    a = {"has_tz": False, "prepayment": True, "contract_format": "без договора"}
    lines = [{"matched": True, "note": ""}]
    assert all(ok for _, ok in conditions(d, a, lines, "fit"))
    a2 = a | {"prepayment": False, "payment_days": 30}
    assert sum(ok for _, ok in conditions(d, a2, lines, "fit")) == 4
