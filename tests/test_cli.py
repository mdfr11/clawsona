import asyncio
import json
import os
import sys

import pytest
from aiohttp import web


@pytest.mark.asyncio
@pytest.mark.parametrize("module", ["clawsona", "lyutik"])
async def test_text_cli_with_actual_http_server_and_no_speech_keys(tmp_path, module):
    received = []

    async def handler(request):
        received.append(await request.json())
        event = json.dumps(
            {"choices": [{"delta": {"content": "Начнём с простого примера."}}]}
        )
        return web.Response(
            text=f"data: {event}\n\ndata: [DONE]\n\n", content_type="text/event-stream"
        )

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    env = {
        **os.environ,
        "LLM_PROVIDER": "custom",
        "LLM_MODEL": "fixture-model",
        "LLM_BASE_URL": f"http://127.0.0.1:{port}/v1",
        "LLM_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "DEEPGRAM_API_KEY": "",
        "LOG_FILE": str(tmp_path / "logs/clawsona.log"),
    }
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            module,
            "--text",
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate("Объясни дроби\n/quit\n".encode()), 15
            )
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, stderr.decode()
        assert "Начнём с простого примера." in stdout.decode()
        assert received[0]["messages"][0]["role"] == "system"
        assert received[0]["messages"][-1]["content"] == "Объясни дроби"
        events = [
            json.loads(line.partition("TIMING ")[2])
            for line in (tmp_path / "logs/clawsona.log").read_text().splitlines()
            if "TIMING " in line
        ]
        assert {e["stage"] for e in events} >= {
            "llm_first_text",
            "llm",
            "tts_total",
            "turn_total",
        }
        assert len({e["turn"] for e in events}) == 1
        assert "Объясни дроби" not in json.dumps(events, ensure_ascii=False)
    finally:
        await runner.cleanup()
