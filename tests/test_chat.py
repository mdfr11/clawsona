import asyncio
import json
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from clawsona.chat import ChatClient


@asynccontextmanager
async def server(handler):
    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/v1"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_real_http_stream_split_across_network_writes():
    captured = {}

    async def handler(request):
        captured["body"] = await request.json()
        captured["auth"] = request.headers.get("Authorization")
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        event = json.dumps(
            {"choices": [{"delta": {"content": "Привет, мир!"}}]}, ensure_ascii=False
        )
        data = f': keepalive\r\ndata:{event}\r\n\r\ndata: {{"choices": []}}\r\ndata: [DONE]\r\n'.encode()
        # Includes partial UTF-8 sequences and lines across actual socket writes.
        for offset in range(0, len(data), 7):
            await response.write(data[offset : offset + 7])
            await asyncio.sleep(0)
        return response

    async with server(handler) as url:
        client = ChatClient(url, "test-model", "secret")
        parts = [
            part
            async for part in client.chat_stream(
                [{"role": "user", "content": "Привет"}]
            )
        ]
    assert parts == ["Привет, мир!"]
    assert captured["auth"] == "Bearer secret"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["stream"] is True


@pytest.mark.asyncio
async def test_http_error_does_not_expose_provider_response():
    async def handler(request):
        return web.Response(status=401, text="echoed-secret-key")

    async with server(handler) as url:
        with pytest.raises(RuntimeError, match="HTTP 401") as error:
            _ = [part async for part in ChatClient(url, "model").chat_stream([])]
    assert "echoed-secret-key" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ['{"error":{"message":"failure"}}', "invalid json"])
async def test_stream_error_is_reported(data):
    async def handler(request):
        return web.Response(text=f"data: {data}\n\n", content_type="text/event-stream")

    async with server(handler) as url:
        with pytest.raises(RuntimeError):
            _ = [part async for part in ChatClient(url, "model").chat_stream([])]


@pytest.mark.asyncio
async def test_network_timeout_is_bounded():
    async def handler(request):
        await asyncio.sleep(0.1)
        return web.Response(text="data: [DONE]\n")

    async with server(handler) as url:
        with pytest.raises(RuntimeError, match="вовремя"):
            _ = [
                part
                async for part in ChatClient(url, "model", timeout_s=0.01).chat_stream(
                    []
                )
            ]


@pytest.mark.asyncio
async def test_abrupt_stream_end_is_not_committed_as_complete_response():
    async def handler(request):
        return web.Response(
            text='data: {"choices": [{"delta": {"content": "partial"}}]}\n',
            content_type="text/event-stream",
        )

    async with server(handler) as url:
        with pytest.raises(RuntimeError, match="до завершения"):
            _ = [part async for part in ChatClient(url, "model").chat_stream([])]


@pytest.mark.asyncio
@pytest.mark.parametrize("thinking", [False, True])
async def test_deepseek_official_contract_and_reasoning_is_not_spoken(thinking):
    from clawsona.chat import create_chat_client
    from clawsona.config import Settings

    captured = {}

    async def handler(request):
        captured.update(await request.json())
        events = [
            {"choices": [{"delta": {"reasoning_content": "Internal reasoning"}}]},
            {"choices": [{"delta": {"content": "Готово."}}]},
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return web.Response(
            text=body + "data: [DONE]\n\n", content_type="text/event-stream"
        )

    config = Settings(
        _env_file=None,
        llm_provider="deepseek",
        deepseek_api_key="test",
        deepseek_thinking=thinking,
    )
    assert config.chat_url == "https://api.deepseek.com"
    async with server(handler) as url:
        config.llm_base_url = url
        response = [part async for part in create_chat_client(config).chat_stream([])]
    assert response == ["Готово."]
    assert captured["model"] == "deepseek-flash"
    assert captured["thinking"] == {"type": "enabled" if thinking else "disabled"}
