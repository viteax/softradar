"""Данные, которые идут по конвейеру: закупка с площадки → анализ агента → строки КП."""

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class Doc:
    name: str
    url: str


@dataclass
class Tender:
    source: str  # roseltorg | fabrikant
    number: str  # номер процедуры на площадке
    url: str
    title: str
    customer: str = ""
    price: float | None = None  # НМЦ, ₽ (None – не указана)
    procedure_type: str = ""  # как пишет площадка: «Мониторинг цен», «Запрос котировок»…
    status: str = ""
    deadline: datetime | None = None  # окончание приема заявок/КП (МСК)
    published: datetime | None = None
    law: str = ""  # 44-ФЗ / 223-ФЗ / коммерческая
    section: str = ""  # торговая секция
    region: str = ""
    msp_only: bool | None = None  # только для МСП (None – площадка не сообщила)
    tags: list[str] = field(default_factory=list)
    docs: list[Doc] = field(default_factory=list)
    page_text: str = ""  # текст карточки процедуры, для агента

    @property
    def key(self) -> str:
        return f"{self.source}:{self.number}"

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("deadline", "published"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Tender:
        d = dict(d)
        d["docs"] = [Doc(**x) for x in d.get("docs") or []]
        for k in ("deadline", "published"):
            d[k] = datetime.fromisoformat(d[k]) if d.get(k) else None
        return cls(**d)


@dataclass
class Variant:
    """Конкретный артикул каталога store.softline.ru."""

    sku: str
    name: str
    config: str
    price: float  # ₽ за единицу, розница каталога
    min_qty: int | None
    max_qty: int | None
    vat: str  # "0" – без НДС (лицензии), "20" и т.д.
    delivery_days: int | None
    family_url: str
    vendor: str = ""

    @property
    def vat_rate(self) -> float:
        try:
            return float(self.vat) / 100
        except ValueError:
            return 0.0


@dataclass
class KpLine:
    request_name: str  # как позиция названа в закупке
    qty: int
    sku: str = ""
    name: str = ""  # наименование из каталога
    unit_price: float = 0.0
    vat_rate: float = 0.0
    url: str = ""
    matched: bool = False
    note: str = ""

    @property
    def total(self) -> float:
        return round(self.unit_price * self.qty, 2)

    @property
    def vat_amount(self) -> float:
        # цены каталога включают НДС: выделяем его из суммы
        return round(self.total * self.vat_rate / (1 + self.vat_rate), 2) if self.vat_rate else 0.0
