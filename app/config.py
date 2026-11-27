"""Настройки из окружения. Все, что бизнес может захотеть поменять, – здесь, а не в коде."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in _env(name, default).split(",") if x.strip()]


# Ключевые вендоры из задачи заказчика (слайд «С чем работать») – дают бонус в скоринге.
KEY_VENDORS = {
    "astra": ["астра", "astra", "rusbitech", "русбитех", "брест", "termidesk", "rupost", "aldpro", "ald pro"],
    "contentai": ["contentai", "content ai", "контент ии", "finereader", "abbyy", "аббии"],
    "cryptopro": ["криптопро", "cryptopro", "крипто-про", "csp"],
    "cyberprotect": ["киберпротект", "cyberprotect", "кибер бэкап", "кибер бекап", "cyber backup"],
    "drweb": ["dr.web", "drweb", "доктор веб", "др.веб", "dr web"],
    "kaspersky": ["kaspersky", "касперск"],
    "pro32": ["pro32"],
    "usergate": ["usergate", "юзергейт"],
    "yandex": ["яндекс", "yandex"],
    "basalt": ["базальт", "basealt", "альт рабочая", "альт сервер", "alt linux", "альт линукс", "альт 1"],
    "positive": ["positive technologies", "maxpatrol", "pt af", "pt application", "pt sandbox", "позитив"],
    "redsoft": ["редсофт", "red soft", "ред ос", "redos", "red os", "ред база"],
}

# Поисковые запросы к площадкам: общие формулировки закупок ПО + ключевые вендоры.
DEFAULT_QUERIES = (
    "программное обеспечение,лицензии программного обеспечения,неисключительных прав программного,"
    "антивирус,права использования программ,Kaspersky,Касперского,Dr.Web,КриптоПро,Astra Linux,"
    "РЕД ОС,UserGate,Positive Technologies,Кибер Бэкап,Базальт,FineReader,МойОфис,Р7-Офис"
)

# Оценка скидки Софтлайн от розничной цены каталога по вендору (доля). В каталоге маржа не указана –
# это допущение для оценки маржи, его правит менеджер в .env (VENDOR_DISCOUNTS=kaspersky:0.25,...).
DEFAULT_DISCOUNTS = (
    "kaspersky:0.25,drweb:0.30,cryptopro:0.20,astra:0.18,basalt:0.20,redsoft:0.20,usergate:0.15,"
    "positive:0.15,cyberprotect:0.22,contentai:0.25,yandex:0.10,pro32:0.30,other:0.15"
)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "data")))
    max_price: float = field(default_factory=lambda: float(_env("MAX_PRICE", "1000000")))
    queries: list[str] = field(default_factory=lambda: _list("SEARCH_QUERIES", DEFAULT_QUERIES))
    sources: list[str] = field(default_factory=lambda: _list("SOURCES", "roseltorg,fabrikant"))
    pages_per_query: int = field(default_factory=lambda: int(_env("PAGES_PER_QUERY", "2")))
    run_interval_min: int = field(default_factory=lambda: int(_env("RUN_INTERVAL_MIN", "60")))
    max_analyze_per_run: int = field(default_factory=lambda: int(_env("MAX_ANALYZE_PER_RUN", "25")))
    min_margin: float = field(default_factory=lambda: float(_env("MIN_MARGIN", "0.08")))
    discounts: dict[str, float] = field(
        default_factory=lambda: {
            k.strip(): float(v)
            for k, v in (x.split(":") for x in _list("VENDOR_DISCOUNTS", DEFAULT_DISCOUNTS))
        }
    )
    giga_auth_key: str = field(default_factory=lambda: _env("GIGACHAT_AUTH_KEY"))
    giga_scope: str = field(default_factory=lambda: _env("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"))
    giga_model: str = field(default_factory=lambda: _env("GIGACHAT_MODEL", "GigaChat-3-Pro"))
    giga_oauth_url: str = field(
        default_factory=lambda: _env(
            "GIGACHAT_OAUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        )
    )
    giga_api_url: str = field(default_factory=lambda: _env("GIGACHAT_API_URL", "https://api.giga.chat/v1"))
    # цена GigaChat за 1000 токенов, ₽ – для расчета стоимости запроса на дашборде
    giga_price_per_1k: float = field(default_factory=lambda: float(_env("GIGACHAT_PRICE_PER_1K", "1.5")))
    autorun: bool = field(default_factory=lambda: _env("AUTORUN", "1") == "1")

    @property
    def llm_ready(self) -> bool:
        return bool(self.giga_auth_key)


settings = Settings()
