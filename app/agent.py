"""Агент-аналитик закупки на GigaChat (function calling).

Модель сама решает, какие документы прочитать и что искать в каталоге, и сдает структурированный итог
через submit_analysis. Модель НЕ считает цены: артикул и цену под количество выбирает код (pick_variant),
он же сверяет, что ссылка на товар действительно из каталога.
"""

import json
import logging
from dataclasses import dataclass, field

import httpx2

from .catalog import Catalog, pick_variant
from .db import DB
from .docs import fetch_text
from .gigachat import GigaChat
from .models import Tender

log = logging.getLogger(__name__)
MAX_STEPS = 12
DOC_CHUNK = 9000

SYSTEM = """Ты – аналитик менеджера Softline по маркетплейсам ПО. Тебе дают закупку с электронной площадки.
Задача: понять, можно ли подать коммерческое предложение (КП), и подготовить данные для КП по каталогу
store.softline.ru.

Порядок работы:
1. Прочитай документы закупки инструментом read_document: в первую очередь запрос КП/ТКП, извещение,
   техническое задание, проект договора. Условия оплаты, срок действия КП и формат договора обычно там.
   Если документов нет – работай по тексту карточки (там бывают позиции, количество и условия), это
   не повод останавливаться.
2. Выдели позиции ПО: точное наименование, количество (узлы, пользователи, лицензии), срок (мес.),
   тип лицензии (новая или продление). Количество – из ТЗ или карточки. Если в названии лицензии указан
   диапазон («1500-2499 Node», «от 50 до 99 узлов»), а точного числа нет – бери нижнюю границу диапазона.
3. Для КАЖДОЙ позиции обязательно найди товар в каталоге: search_catalog (коротким запросом: вендор +
   продукт, например «Kaspersky Endpoint Security Стандартный»), затем get_variants по ссылке с нужным
   количеством. Если не нашлось – попробуй другую формулировку, потом оставь catalog_url пустым.
4. Сдай итог инструментом submit_analysis. Это обязательный последний шаг. Отвечать текстом без
   вызова инструмента нельзя.

Как понимать критерии:
- Закупка ПО – это и «предоставление права использования/неисключительных прав», и лицензии, подписки,
  продления, сертификаты техподдержки ПО. Не ПО – оборудование, разработка, внедрение, работы, обучение.
- Подача КП без конкурса – мониторинг цен, запрос котировок/цен/предложений/ТКП, упрощенная или малая
  закупка, «процедура по закупке с выбором победителя», закупка в интернет-магазине. Конкурс и аукцион – нет.
- decision: «подавать КП» – закупка ПО, без конкурса, позиции понятны; «не подавать» – только при явной
  причине из документов (не ПО, конкурс/аукцион, только МСП, сумма больше 1 млн ₽, срок истек);
  «нужна проверка» – данных не хватает (нет количества, документов, точного названия). Нехватка данных –
  никогда не причина для «не подавать». Причину пиши в decision_reason.

Правила: ничего не выдумывай. Если в документах нет данных – null или «не указано». Цены не считай,
это сделает программа по каталогу. catalog_url бери только из ответов search_catalog. Риски – коротко:
постоплата больше 30 дней, сжатые сроки, требования к опыту/лицензиям ФСТЭК, штрафы, поставка
не ПО (оборудование, работы), отсутствие товара в каталоге, только для МСП, обязательная регистрация
в ЕИС/на площадке и т.п. Пиши по-русски."""

FUNCTIONS = [
    {
        "name": "read_document",
        "description": "Прочитать текст документа закупки (ТЗ, запрос КП, проект договора) по номеру из списка.",
        "parameters": {
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "номер документа из списка, с 1"},
                "part": {"type": "integer", "description": "часть длинного документа, с 1 (по умолчанию 1)"},
            },
            "required": ["index"],
        },
    },
    {
        "name": "search_catalog",
        "description": "Поиск товаров в каталоге store.softline.ru. Возвращает семейства товаров со ссылками и "
        "ценой «от».",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "например: Kaspersky EDR Оптимальный"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_variants",
        "description": "Артикулы семейства товара из каталога: конфигурация, цена за единицу, диапазон количества.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "ссылка на товар из search_catalog"},
                "quantity": {"type": "integer", "description": "нужное количество"},
                "hint": {"type": "string", "description": "пожелания: продление/новая, срок 12/24 мес."},
            },
            "required": ["url", "quantity"],
        },
    },
    {
        "name": "submit_analysis",
        "description": "Сдать итоговый анализ закупки. Последний шаг.",
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["подавать КП", "не подавать", "нужна проверка"],
                    "description": "решение по закупке",
                },
                "decision_reason": {"type": "string", "description": "почему такое решение, 1 предложение"},
                "msp_only": {"type": "boolean", "description": "участвовать могут только субъекты МСП"},
                "nmc_rub": {"type": "number", "description": "НМЦ/максимальная цена, ₽, если указана"},
                "kp_deadline": {"type": "string", "description": "срок приема КП: ДД.ММ.ГГГГ ЧЧ:ММ"},
                "kp_validity_days": {"type": "integer", "description": "минимальный срок действия КП, дней"},
                "payment_terms": {"type": "string", "description": "порядок оплаты как в документах"},
                "prepayment": {"type": "boolean", "description": "есть предоплата/аванс"},
                "payment_days": {
                    "type": "integer",
                    "description": "через сколько дней после поставки оплата",
                },
                "contract_format": {
                    "type": "string",
                    "enum": ["без договора", "шаблон заказчика", "шаблон поставщика", "не указан"],
                },
                "delivery_term": {"type": "string", "description": "срок поставки/передачи лицензий"},
                "has_tz": {"type": "boolean", "description": "есть техническое задание"},
                "vendor": {"type": "string", "description": "основной вендор ПО"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "позиция как в закупке"},
                            "qty": {"type": "integer"},
                            "term_months": {"type": "integer"},
                            "license_type": {"type": "string", "enum": ["новая", "продление", "не указано"]},
                            "catalog_url": {
                                "type": "string",
                                "description": "ссылка из search_catalog или пусто",
                            },
                        },
                        "required": ["name", "qty"],
                    },
                },
                "risks": {"type": "array", "items": {"type": "string"}},
                "summary": {
                    "type": "string",
                    "description": "2–3 предложения для менеджера: что, кому, стоит ли",
                },
            },
            "required": ["decision", "decision_reason", "items", "summary"],
        },
    },
]


@dataclass
class Result:
    analysis: dict = field(default_factory=dict)
    trace: list = field(default_factory=list)
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    requests: int = 0
    error: str = ""


def tender_brief(t: Tender) -> str:
    docs = "\n".join(f"{i}. {d.name}" for i, d in enumerate(t.docs, 1)) or "документов в карточке нет"
    price = f"{t.price:,.2f} ₽".replace(",", " ") if t.price else "не указана"
    deadline = f"{t.deadline:%d.%m.%Y %H:%M} МСК" if t.deadline else "не указан"
    lines = [
        f"Площадка: {t.source}",
        f"Номер: {t.number}",
        f"Ссылка: {t.url}",
        f"Предмет: {t.title}",
        f"Заказчик/организатор: {t.customer}",
        f"Способ: {t.procedure_type}",
        f"Секция: {t.section} {t.law}".strip(),
        f"НМЦ: {price}",
        f"Прием КП до: {deadline}",
        f"Документы:\n{docs}",
        f"\nТекст карточки (фрагмент):\n{t.page_text[:3500]}",
    ]
    return "\n".join(lines)


class Agent:
    def __init__(self, giga: GigaChat, http: httpx2.AsyncClient, db: DB, catalog: Catalog):
        self.giga, self.http, self.db, self.catalog = giga, http, db, catalog

    async def _tool(self, t: Tender, name: str, args: dict) -> str:
        if name == "read_document":
            i = int(args.get("index") or 0)
            if not 1 <= i <= len(t.docs):
                return json.dumps({"error": f"нет документа {i}, всего {len(t.docs)}"}, ensure_ascii=False)
            doc = t.docs[i - 1]
            text = await fetch_text(self.http, self.db, doc.url, doc.name)
            part = max(1, int(args.get("part") or 1))
            chunk = text[(part - 1) * DOC_CHUNK : part * DOC_CHUNK]
            parts = max(1, -(-len(text) // DOC_CHUNK))
            return json.dumps(
                {"name": doc.name, "part": part, "parts": parts, "text": chunk}, ensure_ascii=False
            )
        if name == "search_catalog":
            items = await self.catalog.search(str(args.get("query") or ""), limit=6)
            return json.dumps(
                {"results": items} if items else {"results": [], "note": "ничего не найдено"},
                ensure_ascii=False,
            )
        if name == "get_variants":
            url = str(args.get("url") or "")
            if "store.softline.ru" not in url:
                return json.dumps(
                    {"error": "нужна ссылка store.softline.ru из search_catalog"}, ensure_ascii=False
                )
            qty = int(args.get("quantity") or 1)
            vs = await self.catalog.variants(url)
            best = pick_variant(vs, qty, str(args.get("hint") or ""))
            short = [
                {
                    "sku": v.sku,
                    "config": v.config[:160],
                    "price": v.price,
                    "min_qty": v.min_qty,
                    "max_qty": v.max_qty,
                }
                for v in sorted(vs, key=lambda v: v is not best)[:6]
            ]
            return json.dumps(
                {
                    "total_variants": len(vs),
                    "best_for_quantity": best.sku if best else None,
                    "variants": short,
                },
                ensure_ascii=False,
            )
        return json.dumps({"error": f"неизвестный инструмент {name}"}, ensure_ascii=False)

    async def analyze(self, t: Tender) -> Result:
        res = Result()
        searched = pushed_back = False
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": tender_brief(t)},
        ]
        for step in range(MAX_STEPS):
            # на последнем шаге оставляем только сдачу итога, чтобы агент не зациклился
            funcs = FUNCTIONS if step < MAX_STEPS - 2 else [FUNCTIONS[-1]]
            msg = await self.giga.chat(messages, funcs)
            usage = getattr(self.giga, "last_usage", {}) or {}
            res.tokens += int(usage.get("total_tokens", 0))
            res.prompt_tokens += int(usage.get("prompt_tokens", 0))
            res.completion_tokens += int(usage.get("completion_tokens", 0))
            res.requests += 1
            call = msg.get("function_call")
            if not call:
                res.trace.append(
                    {"step": step + 1, "type": "text", "content": (msg.get("content") or "")[:1500]}
                )
                messages += [
                    {"role": "assistant", "content": msg.get("content") or ""},
                    {
                        "role": "user",
                        "content": "Продолжай через инструменты: найди каждую позицию в каталоге "
                        "(search_catalog, get_variants), затем сдай итог через submit_analysis.",
                    },
                ]
                continue
            name = call.get("name", "")
            args = call.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name == "submit_analysis":
                unsearched = not searched and args.get("decision") != "не подавать"
                if unsearched and not pushed_back and step < MAX_STEPS - 3:
                    # самопроверка: позиции есть, а каталог не смотрели – возвращаем агенту один раз
                    pushed_back = True
                    result = json.dumps(
                        {
                            "error": "итог не принят: каталог не проверен. Выдели позиции из документов или карточки, найди каждую через "
                            "search_catalog и get_variants, затем снова submit_analysis."
                        },
                        ensure_ascii=False,
                    )
                    res.trace.append(
                        {
                            "step": step + 1,
                            "type": "tool",
                            "name": "self_check",
                            "args": {},
                            "result": "итог возвращен агенту: позиции не проверены в каталоге",
                        }
                    )
                else:
                    res.analysis = args
                    res.trace.append({"step": step + 1, "type": "submit", "args": args})
                    return res
            else:
                searched = searched or name == "search_catalog"
                try:
                    result = await self._tool(t, name, args)
                except Exception as e:  # noqa: BLE001 – ошибка инструмента уходит модели, а не роняет анализ
                    log.warning("инструмент %s: %s", name, e)
                    result = json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)
                res.trace.append(
                    {"step": step + 1, "type": "tool", "name": name, "args": args, "result": result[:1200]}
                )
            assistant_msg = {"role": "assistant", "content": msg.get("content") or "", "function_call": call}
            if msg.get("functions_state_id"):
                assistant_msg["functions_state_id"] = msg["functions_state_id"]
            messages += [assistant_msg, {"role": "function", "name": name, "content": result}]
        res.error = "агент не сдал итог за отведенные шаги"
        return res
