"""Клиент GigaChat API: OAuth-токен (живет 30 минут) и chat/completions с function calling.

Сертификаты Сбера выпущены Russian Trusted Root CA (Минцифры) – его нет в образе, поэтому он грузится
в SSL-контекст только этого клиента, а не в систему.
"""

import asyncio
import logging
import ssl
import time
import uuid
from pathlib import Path

import httpx2

log = logging.getLogger(__name__)
CA_FILE = Path(__file__).parent / "certs" / "russian_trusted_root_ca.pem"
RETRY_STATUS = {429, 500, 502, 503, 504}  # временные сбои – повторяем


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=CA_FILE)
    return ctx


class GigaChatError(Exception):
    def __init__(self, text: str, status: int = 0):
        super().__init__(text)
        self.status = status

    @property
    def user_text(self) -> str:
        """Что сказать пользователю: по коду видно, поможет ли подождать."""
        if self.status in (401, 403):
            return "GigaChat не принял ключ – проверьте GIGACHAT_AUTH_KEY в /opt/jarvis/.env."
        if self.status == 402:
            return "У GigaChat закончились токены – пополните баланс или смените модель (GIGACHAT_MODEL)."
        return "GigaChat сейчас не отвечает. Попробуйте чуть позже."


class GigaChat:
    def __init__(
        self,
        auth_key: str,
        scope: str,
        model: str,
        oauth_url: str,
        api_url: str,
        transport: httpx2.AsyncBaseTransport | None = None,
    ):
        self.auth_key, self.scope, self.model = auth_key, scope, model
        self.oauth_url, self.api_url = oauth_url, api_url.rstrip("/")
        self.http = httpx2.AsyncClient(
            verify=ssl_context() if transport is None else True,
            transport=transport,
            timeout=httpx2.Timeout(90, connect=10),
        )
        self._token, self._expires = "", 0.0
        self.retry_delays: tuple[float, ...] = (1, 4)  # пауза перед 2-й и 3-й попыткой
        self.last_usage: dict = {}  # usage последнего ответа: prompt_tokens, completion_tokens, total_tokens

    async def token(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        r = await self.http.post(
            self.oauth_url,
            headers={
                "Authorization": f"Basic {self.auth_key}",
                "RqUID": str(uuid.uuid4()),
                "Accept": "application/json",
            },
            data={"scope": self.scope},
        )
        if r.status_code != 200:
            raise GigaChatError(f"токен GigaChat: HTTP {r.status_code} {r.text[:200]}", r.status_code)
        body = r.json()
        self._token = body["access_token"]
        exp = float(body.get("expires_at", 0))
        # в примерах документации – секунды, в ответах встречаются миллисекунды
        self._expires = exp / 1000 if exp > 1e11 else exp or time.time() + 25 * 60
        return self._token

    async def chat(self, messages: list[dict], functions: list[dict] | None = None) -> dict:
        """Один запрос; возвращает message ответа (role assistant, content, function_call?)."""
        payload: dict = {"model": self.model, "messages": messages}
        if functions:
            payload["functions"] = functions
            payload["function_call"] = "auto"
        last = GigaChatError("GigaChat: нет попыток")
        for attempt in range(len(self.retry_delays) + 1):
            if attempt:
                log.warning("%s – повтор %d через %s с", last, attempt, self.retry_delays[attempt - 1])
                await asyncio.sleep(self.retry_delays[attempt - 1])
            try:
                return await self._chat_once(payload)
            except httpx2.TimeoutException as e:
                # ответ модели может идти долго – после таймаута чтения не повторяем, иначе ждать минуты
                if not isinstance(e, httpx2.ConnectTimeout):
                    raise GigaChatError(f"GigaChat: нет ответа ({type(e).__name__})") from e
                last = GigaChatError(f"GigaChat: не подключиться ({type(e).__name__})")
            except httpx2.TransportError as e:
                last = GigaChatError(f"GigaChat: связь оборвалась ({type(e).__name__})")
            except GigaChatError as e:
                if e.status not in RETRY_STATUS:
                    raise
                last = e
        raise last

    async def _chat_once(self, payload: dict) -> dict:
        r = await self._post_chat(payload)
        if r.status_code == 401:  # токен отозван раньше срока – один раз берем новый
            self._token = ""
            r = await self._post_chat(payload)
        if r.status_code != 200:
            raise GigaChatError(f"GigaChat: HTTP {r.status_code} {r.text[:300]}", r.status_code)
        body = r.json()
        self.last_usage = body.get("usage") or {}
        choice = body["choices"][0]
        if choice.get("finish_reason") == "blacklist":
            return {"role": "assistant", "content": "Эту тему GigaChat обсуждать отказывается."}
        return choice["message"]

    async def _post_chat(self, payload: dict) -> httpx2.Response:
        return await self.http.post(
            f"{self.api_url}/chat/completions",
            headers={"Authorization": f"Bearer {await self.token()}"},
            json=payload,
        )

    async def balance(self) -> dict[str, int]:
        """Остаток токенов по моделям (пакеты физлица): {"GigaChat-Max": 24925832, ...}."""
        r = await self.http.get(
            f"{self.api_url}/balance", headers={"Authorization": f"Bearer {await self.token()}"}
        )
        if r.status_code != 200:
            raise GigaChatError(f"баланс GigaChat: HTTP {r.status_code} {r.text[:200]}", r.status_code)
        return {b["usage"]: int(b["value"]) for b in r.json().get("balance", [])}

    async def aclose(self) -> None:
        await self.http.aclose()
