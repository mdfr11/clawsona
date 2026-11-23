import uuid
from collections.abc import AsyncIterator

import aiohttp


class OpenClawClient:
    """One private Gateway session per conversation; only finalized agent replies."""

    def __init__(self, base_url, api_key, agent="clawsona", timeout_s=180):
        self.base_url = base_url.rstrip("/")
        self.model = f"openclaw/{agent}"
        self._key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout_s, connect=10)
        self.reset_session()

    def reset_session(self):
        self._session_id = f"clawsona:{uuid.uuid4()}"

    async def chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        # Gateway owns tool history. Replaying the complete local history into
        # an existing Gateway session duplicates turns and tool side effects.
        latest = next((m for m in reversed(messages) if m.get("role") == "user"), None)
        if latest is None:
            raise ValueError("Нет реплики пользователя")
        request_messages = [m for m in messages if m.get("role") == "system"] + [latest]
        payload = {
            "model": self.model,
            "user": self._session_id,
            "stream": False,
            "messages": request_messages,
        }
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json=payload,
                ) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"OpenClaw HTTP {response.status}; проверьте clawsona openclaw-setup и gateway"
                        )
                    data = await response.json()
            text = data["choices"][0]["message"].get("content")
            if not isinstance(text, str) or not text.strip():
                raise RuntimeError("OpenClaw не вернул окончательный текст ответа")
            yield text
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise RuntimeError(
                "OpenClaw недоступен или не закончил запрос вовремя"
            ) from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Некорректный ответ OpenClaw") from exc
