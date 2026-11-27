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
    "basalt": ["базальт спо", "basealt", "альт рабочая", "альт сервер", "alt linux", "альт линукс", "альт 1"],
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
    max_analyze_per_run: int = field(default_factory=lambda: int(_env("MAX_ANALYZE_PER_RUN", "40")))
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
    # провайдер LLM: gigachat (developers.sber.ru) или openai (OpenAI-совместимый API, например cloud.ru)
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "gigachat"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "https://foundation-models.api.cloud.ru/v1")
    )
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "GigaChat/GigaChat-4-708B-A41"))
    # цена за 1 млн токенов, ₽ (вход / выход) – для стоимости разбора на дашборде
    price_in_1m: float = field(default_factory=lambda: float(_env("LLM_PRICE_IN_1M", "96.22")))
    price_out_1m: float = field(default_factory=lambda: float(_env("LLM_PRICE_OUT_1M", "288.6")))
    # ежедневный отчет на почту (пусто – не отправлять)
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(_env("SMTP_PORT", "465")))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER"))
    smtp_password: str = field(default_factory=lambda: _env("SMTP_PASSWORD"))
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM"))
    report_to: str = field(default_factory=lambda: _env("REPORT_TO"))
    report_hour: int = field(default_factory=lambda: int(_env("REPORT_HOUR", "9")))  # МСК
    autorun: bool = field(default_factory=lambda: _env("AUTORUN", "1") == "1")

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key) if self.llm_provider == "openai" else bool(self.giga_auth_key)

    @property
    def mail_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.report_to)

    @property
    def model_name(self) -> str:
        return self.llm_model if self.llm_provider == "openai" else self.giga_model

    def cost(self, prompt: int, completion: int, total: int = 0) -> float:
        """₽ за разбор: по входным/выходным токенам; если разбивки нет – все по цене входа."""
        if not (prompt or completion):
            prompt = total
        return (prompt * self.price_in_1m + completion * self.price_out_1m) / 1_000_000


settings = Settings()
