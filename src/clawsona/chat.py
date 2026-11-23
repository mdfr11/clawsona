import json
from collections.abc import AsyncIterator

import aiohttp

from clawsona.openclaw_client import OpenClawClient


class ChatClient:
    """Direct model API for DeepSeek, Ollama and compatible local servers."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: float = 120,
        max_tokens: int = 384,
        extra_body: dict | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout_s, connect=10, sock_read=60)
        self._max_tokens = max_tokens
        self._extra_body = extra_body or {}

    async def chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            **self._extra_body,
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": self._max_tokens,
        }
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    f"{self.base_url}/chat/completions", headers=headers, json=payload
                ) as response:
                    if response.status != 200:
                        # A provider's error body may echo credentials or user data.
                        raise RuntimeError(
                            f"LLM HTTP {response.status}: проверьте адрес, ключ и модель"
                        )
                    completed = False
                    async for raw_line in response.content:
                        line = raw_line.decode("utf-8").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            event = json.loads(data)
                            if event.get("error"):
                                raise RuntimeError("LLM вернула ошибку в потоке ответа")
                            choices = event.get("choices") or []
                            if not choices:
                                continue
                            if choices[0].get("finish_reason") is not None:
                                completed = True
                            text = (choices[0].get("delta") or {}).get("content")
                            if isinstance(text, str) and text:
                                yield text
                        except (
                            ValueError,
                            TypeError,
                            AttributeError,
                            IndexError,
                        ) as exc:
                            raise RuntimeError("Некорректный поток ответа LLM") from exc
                    if not completed:
                        raise RuntimeError("LLM закрыла поток до завершения ответа")
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise RuntimeError("Модель недоступна или не ответила вовремя") from exc


def create_chat_client(config) -> ChatClient | OpenClawClient:
    if config.llm_provider == "openclaw":
        if not config.openclaw_gateway_token:
            raise ValueError("Настройте OpenClaw: clawsona openclaw-setup")
        return OpenClawClient(
            config.chat_url,
            config.openclaw_gateway_token,
            config.openclaw_agent,
            max(config.llm_timeout_s, 180),
        )
    if config.llm_provider == "deepseek" and not config.chat_key:
        raise ValueError(
            "Задайте DEEPSEEK_API_KEY в .env (или выберите LLM_PROVIDER=ollama)"
        )
    return ChatClient(
        config.chat_url,
        config.chat_model,
        config.chat_key,
        config.llm_timeout_s,
        config.llm_max_tokens,
        extra_body={
            "thinking": {"type": "enabled" if config.deepseek_thinking else "disabled"}
        }
        if config.llm_provider == "deepseek"
        else None,
    )
