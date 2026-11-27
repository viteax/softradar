"""OpenAI-совместимый провайдер (cloud.ru Foundation Models и др.) с тем же интерфейсом, что и GigaChat.

Агент ведет историю в формате GigaChat (function_call / role=function); здесь она переводится
в tools / tool_calls и обратно, так что агент не знает, какой провайдер под капотом.
"""

import json

import httpx2

from .gigachat import GigaChatError


class OpenAIChat:
    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 120):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.last_usage: dict = {}
        self.http = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=httpx2.Timeout(timeout, connect=15)
        )

    @staticmethod
    def to_openai(messages: list[dict]) -> list[dict]:
        out, n, last_id = [], 0, ""
        for m in messages:
            role = m.get("role")
            if role == "assistant" and m.get("function_call"):
                n += 1
                last_id = f"call_{n}"
                call = m["function_call"]
                args = call.get("arguments") or {}
                out.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": last_id,
                                "type": "function",
                                "function": {
                                    "name": call.get("name", ""),
                                    "arguments": args
                                    if isinstance(args, str)
                                    else json.dumps(args, ensure_ascii=False),
                                },
                            }
                        ],
                    }
                )
            elif role == "function":
                out.append({"role": "tool", "tool_call_id": last_id, "content": m.get("content") or ""})
            else:
                out.append({"role": role, "content": m.get("content") or ""})
        return out

    async def chat(self, messages: list[dict], functions: list[dict] | None = None) -> dict:
        payload: dict = {"model": self.model, "messages": self.to_openai(messages), "temperature": 0.1}
        if functions:
            payload["tools"] = [{"type": "function", "function": f} for f in functions]
            payload["tool_choice"] = "auto"
        r = await self.http.post(f"{self.base_url}/chat/completions", json=payload)
        if r.status_code != 200:
            raise GigaChatError(f"LLM {self.model}: HTTP {r.status_code} {r.text[:300]}", r.status_code)
        data = r.json()
        self.last_usage = data.get("usage") or {}
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        out = {"role": "assistant", "content": msg.get("content") or ""}
        calls = msg.get("tool_calls") or []
        if calls:
            fn = calls[0].get("function") or {}
            args = fn.get("arguments") or "{}"
            try:
                args = json.loads(args) if isinstance(args, str) else args
            except json.JSONDecodeError:
                args = {}
            out["function_call"] = {"name": fn.get("name", ""), "arguments": args}
        return out

    async def aclose(self) -> None:
        await self.http.aclose()
