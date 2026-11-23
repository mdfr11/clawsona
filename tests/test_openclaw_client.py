import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from clawsona.openclaw_client import OpenClawClient


@pytest.mark.asyncio
async def test_gateway_session_history_reset_and_final_only_reply():
    received = []

    async def handler(request):
        received.append(await request.json())
        assert request.headers["Authorization"] == "Bearer gateway-test"
        return web.json_response(
            {"choices": [{"message": {"content": "Готовый ответ."}}]}
        )

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    async with TestServer(app) as server:
        client = OpenClawClient(str(server.make_url("/v1")), "gateway-test")
        history = [
            {"role": "system", "content": "prompt"},
            {"role": "system", "content": "User messages are microphone transcripts."},
            {"role": "user", "content": "первый"},
        ]
        assert [part async for part in client.chat_stream(history)] == [
            "Готовый ответ."
        ]
        history += [
            {"role": "assistant", "content": "старый ответ"},
            {"role": "user", "content": "второй"},
        ]
        _ = [part async for part in client.chat_stream(history)]
        assert received[0]["user"] == received[1]["user"]
        assert received[1]["messages"] == [*history[:2], history[-1]]
        assert received[1]["stream"] is False
        client.reset_session()
        _ = [part async for part in client.chat_stream(history)]
        assert received[2]["user"] != received[1]["user"]


@pytest.mark.asyncio
async def test_gateway_errors_are_not_spoken_as_success():
    async def handler(request):
        return web.Response(status=503, text="secret from gateway")

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    async with TestServer(app) as server:
        client = OpenClawClient(str(server.make_url("/v1")), "token")
        with pytest.raises(RuntimeError, match="503") as exc:
            _ = [
                p async for p in client.chat_stream([{"role": "user", "content": "hi"}])
            ]
        assert "secret" not in str(exc.value)
