import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from clawsona.models import download_file


@pytest.mark.asyncio
async def test_completed_download_is_atomic_and_reused(tmp_path):
    calls = []

    async def model(request):
        calls.append(1)
        return web.Response(body=b"valid-model-bytes")

    app = web.Application()
    app.router.add_get("/model", model)
    destination = tmp_path / "models/voice.onnx"
    async with TestServer(app) as server:
        await download_file(str(server.make_url("/model")), destination)
        await download_file(str(server.make_url("/model")), destination)
    assert destination.read_bytes() == b"valid-model-bytes"
    assert len(calls) == 1
    assert not destination.with_suffix(".onnx.part").exists()


@pytest.mark.asyncio
async def test_interrupted_download_cannot_be_mistaken_for_ready_model(tmp_path):
    async def interrupted(request):
        response = web.StreamResponse(headers={"Content-Length": "1000"})
        await response.prepare(request)
        await response.write(b"truncated")
        request.transport.close()
        return response

    app = web.Application()
    app.router.add_get("/model", interrupted)
    destination = tmp_path / "voice.onnx"
    async with TestServer(app) as server:
        with pytest.raises(aiohttp.ClientPayloadError):
            await download_file(str(server.make_url("/model")), destination)
    assert not destination.exists()
    assert not destination.with_suffix(".onnx.part").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["piper", "elevenlabs"])
async def test_speech_setup_prepares_both_local_voice_models(
    tmp_path, mocker, provider
):
    from clawsona.config import Settings
    from clawsona.models import prepare_models

    download = mocker.patch(
        "clawsona.models.download_file", new_callable=mocker.AsyncMock
    )
    config = Settings(_env_file=None, models_dir=tmp_path, tts_provider=provider)
    await prepare_models(config, only="tts")
    names = [c.args[1].name for c in download.await_args_list]
    assert names == [
        f"{config.piper_voice}.onnx",
        f"{config.piper_voice}.onnx.json",
        f"{config.piper_voice}.MODEL_CARD",
        f"{config.piper_english_voice}.onnx",
        f"{config.piper_english_voice}.onnx.json",
        f"{config.piper_english_voice}.MODEL_CARD",
    ]
    for call in download.await_args_list:
        if call.args[1].name.endswith(".MODEL_CARD"):
            assert call.args[0].endswith("/MODEL_CARD")
