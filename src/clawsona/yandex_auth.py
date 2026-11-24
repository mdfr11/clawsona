import asyncio
import json
import threading
import time
from pathlib import Path


def token_path():
    return Path.home() / ".local/share/clawsona/yandex-auth.json"


def saved_token():
    path = token_path()
    if not path.is_file():
        return ""
    return json.loads(path.read_text()).get("access_token", "")


async def login():
    from yandex_music import Client

    cancelled = threading.Event()

    def show_code(code):
        print(
            f"Откройте {code.verification_url} и введите код: {code.user_code}",
            flush=True,
        )
        print(
            "Ожидаю подтверждения входа в Яндекс. Токен будет сохранён только локально.",
            flush=True,
        )

    try:
        token = await asyncio.to_thread(
            Client().device_auth,
            on_code=show_code,
            timeout=300,
            should_cancel=cancelled.is_set,
            device_name="ClawSona voice companion",
        )
    except asyncio.CancelledError:
        cancelled.set()
        raise
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "expires_at": time.time() + (token.expires_in or 3600),
    }
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    print(
        "Яндекс Музыка подключена. Перезапустите ClawSona, если приложение уже запущено.",
        flush=True,
    )
