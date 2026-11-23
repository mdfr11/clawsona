"""Provision the configured profile; never edit the main OpenClaw profile."""

import asyncio
import json
import os
import secrets
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from clawsona.prompts import AGENT_SYSTEM_PROMPT
from clawsona.timing import stage_timer


def update_env(values, path=Path(".env")):
    # Preserve all existing settings and credentials; only replace named entries.
    lines = path.read_text().splitlines() if path.exists() else []
    found = set()
    for index, line in enumerate(lines):
        key = line.partition("=")[0]
        if key in values:
            lines[index] = f"{key}={values[key]}"
            found.add(key)
    lines.extend(f"{key}={value}" for key, value in values.items() if key not in found)
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


def profile_dir(config):
    return Path.home() / f".openclaw-{config.openclaw_profile}"


def command(config):
    # Reuse the installed CLI; the profile and workspace are strictly separate.
    binary = shutil.which("openclaw")
    if not binary:
        raise FileNotFoundError("Установите OpenClaw: https://docs.openclaw.ai/install")
    return [binary, "--profile", config.openclaw_profile]


def child_env(config):
    return {
        **os.environ,
        "DEEPSEEK_API_KEY": config.deepseek_api_key,
        "OPENCLAW_GATEWAY_TOKEN": config.openclaw_gateway_token,
        "CLAWSONA_TOOLS_TOKEN": config.clawsona_tools_token,
        # Previously generated profiles can still refer to this placeholder.
        "LYUTIK_TOOLS_TOKEN": config.clawsona_tools_token,
    }


async def prepare_openclaw(config):
    command(config)
    if not config.deepseek_api_key:
        raise ValueError("Сначала заполните DEEPSEEK_API_KEY в .env")
    if not config.openclaw_gateway_token:
        config.openclaw_gateway_token = secrets.token_urlsafe(32)
    if not config.clawsona_tools_token:
        config.clawsona_tools_token = secrets.token_urlsafe(32)
    root = profile_dir(config)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / "openclaw.json"
    if target.exists():
        old = json.loads(target.read_text())
        if (
            old.get("agents", {}).get("list", [{}])[0].get("id")
            != config.openclaw_agent
        ):
            raise ValueError(
                f"Профиль {config.openclaw_profile} уже используется другим агентом"
            )
        shutil.copy2(target, target.with_suffix(".json.bak"))
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    plugin = repo / "openclaw" / "clawsona-tools"
    bundled = Path(__file__).parent / "openclaw_plugin"
    if bundled.is_dir():
        plugin = bundled
    if not (plugin / "index.js").is_file():
        raise FileNotFoundError(
            "Запускайте openclaw-setup из checkout проекта с папкой openclaw/clawsona-tools"
        )
    data = {
        "gateway": {
            "mode": "local",
            "bind": "loopback",
            "port": urlparse(config.openclaw_url).port or 18791,
            "auth": {"mode": "token", "token": "${OPENCLAW_GATEWAY_TOKEN}"},
            "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
        },
        "agents": {
            "defaults": {
                "workspace": str(workspace),
                "model": {"primary": "deepseek/deepseek-flash"},
                "models": {"deepseek/deepseek-flash": {"params": {"maxTokens": 1024}}},
                "thinkingDefault": "off",
                "heartbeat": {"every": "0m"},
                "memorySearch": {"enabled": False},
            },
            "list": [
                {
                    "id": config.openclaw_agent,
                    "name": config.assistant_name,
                    "default": True,
                    "workspace": str(workspace),
                }
            ],
        },
        "models": {
            "mode": "merge",
            "providers": {
                "deepseek": {
                    "baseUrl": "https://api.deepseek.com",
                    "apiKey": "${DEEPSEEK_API_KEY}",
                    "api": "openai-completions",
                    "models": [
                        {
                            "id": "deepseek-flash",
                            "name": "DeepSeek Flash",
                            "reasoning": True,
                            "input": ["text"],
                            "contextWindow": 1000000,
                            "maxTokens": 393216,
                        }
                    ],
                }
            },
        },
        "plugins": {
            "allow": ["clawsona-tools"],
            "slots": {"memory": "none"},
            "load": {"paths": [str(plugin)]},
            "entries": {
                "clawsona-tools": {
                    "enabled": True,
                    "config": {
                        "baseUrl": f"http://127.0.0.1:{config.clawsona_tools_port}",
                        "token": "${CLAWSONA_TOOLS_TOKEN}",
                    },
                }
            },
        },
        "tools": {
            "allow": [
                "session_status",
                "clawsona_weather",
                "clawsona_search",
            ],
            "deny": [
                "exec",
                "process",
                "read",
                "write",
                "edit",
                "browser",
                "message",
                "sessions_spawn",
                "cron",
                "gateway",
                "nodes",
            ],
        },
        "cron": {"enabled": False},
    }
    if config.music_enabled:
        data["tools"]["allow"].append("clawsona_music")
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    target.chmod(0o600)
    (workspace / "SOUL.md").write_text(AGENT_SYSTEM_PROMPT)
    (workspace / "AGENTS.md").write_text(
        "Следуй SOUL.md. Для погоды, поиска и музыки используй только доступные инструменты. Не заявляй об успехе при ошибке инструмента.\n"
    )
    update_env(
        {
            "LLM_PROVIDER": "openclaw",
            "LLM_MODEL": "",
            "LLM_BASE_URL": "",
            "OPENCLAW_GATEWAY_TOKEN": config.openclaw_gateway_token,
            "CLAWSONA_TOOLS_TOKEN": config.clawsona_tools_token,
            "ASSISTANT_NAME": config.assistant_name,
            "ASSISTANT_ALIASES": ",".join(config.assistant_aliases),
        }
    )
    process = await asyncio.create_subprocess_exec(
        *command(config), "config", "validate", env=child_env(config)
    )
    if await process.wait():
        raise RuntimeError("OpenClaw отклонил конфигурацию; смотрите сообщение выше")
    print(
        f"Профиль {config.openclaw_profile} подготовлен. Запуск: clawsona openclaw-gateway",
        flush=True,
    )


async def run_gateway(config):
    process = await asyncio.create_subprocess_exec(
        *command(config), "gateway", "run", env=child_env(config)
    )
    try:
        code = await process.wait()
        if code:
            raise RuntimeError(f"OpenClaw завершился с кодом {code}")
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except TimeoutError:
                process.kill()
                await process.wait()


@asynccontextmanager
async def ensure_gateway(config):
    """Start our profile on demand and stop only a process started by this app."""
    address = urlparse(config.openclaw_url)
    if address.hostname not in {"127.0.0.1", "localhost", "::1"}:
        yield
        return

    async def listening():
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(address.hostname, address.port or 18791), 0.5
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    with stage_timer("startup_gateway_probe") as metrics:
        already_running = await listening()
        metrics["already_running"] = already_running
    if already_running:
        yield
        return
    task = asyncio.create_task(run_gateway(config))
    try:
        with stage_timer("startup_gateway"):
            for _ in range(300):
                if task.done():
                    await task
                    raise RuntimeError("OpenClaw остановился до запуска HTTP API")
                if await listening():
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("OpenClaw не запустился за тридцать секунд")
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
