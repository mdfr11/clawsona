import asyncio
import base64
import logging
import threading
import wave
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web

from clawsona.config import Settings
from clawsona.elevenlabs_tts import ElevenLabsError, ElevenLabsTTS, list_voices
from clawsona.local_speech import create_tts
from clawsona.timing import mark_capture_complete, trace_turn


@asynccontextmanager
async def server(handler, path="/v1/text-to-dialogue/stream-input"):
    app = web.Application()
    app.router.add_get(path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


async def handshake(request):
    socket = web.WebSocketResponse()
    await socket.prepare(request)
    frames = [await socket.receive_json() for _ in range(3)]
    return socket, frames


def audio(pcm):
    return {"audio": base64.b64encode(pcm).decode()}


class Output:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.writes = []
        self.started = self.drained = self.aborted = self.closed = False

    def start(self):
        self.started = True

    def write(self, pcm):
        assert self.started and not self.closed
        self.writes.append(pcm)

    def stop(self):
        self.drained = True

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


async def test_export_reassembles_odd_pcm_and_flushes_short_text(tmp_path, monkeypatch):
    received = []

    async def handler(request):
        assert request.headers["xi-api-key"] == "test-key"
        assert request.query["model_id"] == "eleven_v4_turbo"
        assert request.query["output_format"] == "pcm_24000"
        socket, frames = await handshake(request)
        received.extend(frames)
        await socket.send_json(audio(b"\x01"))
        await socket.send_json(audio(b"\x00\x02\x00"))
        await socket.send_json({"is_final": True})
        return socket

    speaker = Mock(side_effect=AssertionError("Export must not open a speaker"))
    monkeypatch.setattr("clawsona.elevenlabs_tts.sd.RawOutputStream", speaker)
    async with server(handler) as url:
        tts = ElevenLabsTTS("test-key", "voice", base_url=url)
        path = tmp_path / "sample.wav"
        await tts.save_wav("Да?", path)
    with wave.open(str(path)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (
            24000,
            1,
            2,
        )
        assert wav.readframes(10) == b"\x01\x00\x02\x00"
    assert received == [
        {"voices": ["voice"]},
        {"inputs": [{"text": "Да?", "voice_id": "voice"}]},
        {"close_socket": True},
    ]
    speaker.assert_not_called()


async def test_playback_starts_before_network_finishes_and_logs_timings(
    monkeypatch, caplog
):
    written = asyncio.Event()
    loop = asyncio.get_running_loop()

    class Stream(Output):
        def write(self, pcm):
            super().write(pcm)
            loop.call_soon_threadsafe(written.set)

    output = Stream()
    monkeypatch.setattr(
        "clawsona.elevenlabs_tts.sd.RawOutputStream", lambda **_: output
    )

    async def handler(request):
        socket, _ = await handshake(request)
        await asyncio.sleep(0.02)
        await socket.send_json(audio(b"\x01\x00"))
        await asyncio.wait_for(written.wait(), 2)
        await socket.send_json(audio(b"\x02\x00"))
        await socket.send_json({"is_final": True})
        return socket

    with caplog.at_level(logging.INFO), trace_turn():
        mark_capture_complete()
        async with server(handler) as url:
            await ElevenLabsTTS("key", "voice", base_url=url).speak("Hello")
    assert b"".join(output.writes) == b"\x01\x00\x02\x00"
    assert output.drained and output.closed and not output.aborted
    timings = [r.timing for r in caplog.records if hasattr(r, "timing")]
    by_stage = {event["stage"]: event for event in timings}
    assert {
        "elevenlabs_connect",
        "elevenlabs_first_chunk",
        "tts_first_pcm",
        "elevenlabs",
        "capture_to_first_audio",
    } <= by_stage.keys()
    assert by_stage["tts_first_pcm"]["duration_ms"] >= 20
    assert by_stage["elevenlabs"]["audio_ms"] == pytest.approx(4 / 48000 * 1000)
    assert len({event["turn"] for event in timings}) == 1


@pytest.mark.parametrize(
    "failure",
    ["handshake", "error", "timeout", "truncated", "invalid_json", "invalid_audio"],
)
async def test_failure_before_sound_uses_lazy_fallback_without_leaking_secrets(
    failure, caplog
):
    fallback = Mock(speak=AsyncMock())
    factory = Mock(return_value=fallback)

    async def handler(request):
        if failure == "handshake":
            return web.Response(status=401, text="secret-key user text")
        socket, _ = await handshake(request)
        if failure == "error":
            await socket.send_json({"error": "secret-key user text"})
        elif failure == "timeout":
            await socket.receive()  # Wait until the timed-out client closes.
        elif failure == "invalid_json":
            await socket.send_json(["secret-key user text"])
        elif failure == "invalid_audio":
            await socket.send_json({"audio": "invalid!"})
        return socket

    async with server(handler) as url:
        tts = ElevenLabsTTS(
            "secret-key", "voice", base_url=url, timeout_s=0.1, fallback_factory=factory
        )
        factory.assert_not_called()
        await tts.speak("hello")
    factory.assert_called_once()
    fallback.speak.assert_awaited_once_with("hello")
    assert "secret-key" not in caplog.text
    assert "user text" not in caplog.text


async def test_error_after_sound_does_not_repeat_answer(monkeypatch):
    fallback = Mock(speak=AsyncMock())
    output = Output()
    monkeypatch.setattr(
        "clawsona.elevenlabs_tts.sd.RawOutputStream", lambda **_: output
    )

    async def handler(request):
        socket, _ = await handshake(request)
        await socket.send_json(audio(b"\x01\x00"))
        await socket.send_json({"error": "bad"})
        return socket

    async with server(handler) as url:
        tts = ElevenLabsTTS(
            "key", "voice", base_url=url, fallback_factory=lambda: fallback
        )
        with pytest.raises(ElevenLabsError):
            await tts.speak("hello")
    fallback.speak.assert_not_awaited()
    assert output.aborted and output.closed and not output.drained


async def test_stop_during_network_wait_closes_socket_without_fallback():
    ready, closed = asyncio.Event(), asyncio.Event()
    fallback = Mock(speak=AsyncMock())

    async def handler(request):
        socket, _ = await handshake(request)
        ready.set()
        await socket.receive()
        closed.set()
        return socket

    async with server(handler) as url:
        tts = ElevenLabsTTS(
            "key", "voice", base_url=url, fallback_factory=lambda: fallback
        )
        task = asyncio.create_task(tts.speak("hello"))
        await asyncio.wait_for(ready.wait(), 2)
        tts.stop()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        await asyncio.wait_for(closed.wait(), 2)
    fallback.speak.assert_not_awaited()


async def test_stop_joins_blocking_device_writer_before_closing(monkeypatch):
    writing, release = threading.Event(), threading.Event()

    class Stream(Output):
        def write(self, pcm):
            writing.set()
            assert release.wait(2)
            assert not self.closed

        def abort(self):
            super().abort()
            release.set()

    output = Stream()
    monkeypatch.setattr(
        "clawsona.elevenlabs_tts.sd.RawOutputStream", lambda **_: output
    )

    async def handler(request):
        socket, _ = await handshake(request)
        await socket.send_json(audio(b"\x01\x00"))
        await socket.receive()
        return socket

    async with server(handler) as url:
        tts = ElevenLabsTTS("key", "voice", base_url=url)
        task = asyncio.create_task(tts.speak("hello"))
        assert await asyncio.to_thread(writing.wait, 2)
        tts.stop()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
    assert output.aborted and output.closed and not output.drained


async def test_failed_export_preserves_destination_without_fallback(tmp_path):
    async def handler(request):
        socket, _ = await handshake(request)
        await socket.send_json(audio(b"\x01\x00"))
        # An odd trailing byte is not a valid PCM sample.
        await socket.send_json(audio(b"\x01"))
        await socket.send_json({"is_final": True})
        return socket

    path = tmp_path / "sample.wav"
    path.write_bytes(b"original")
    fallback = Mock()
    async with server(handler) as url:
        tts = ElevenLabsTTS("key", "voice", base_url=url, fallback_factory=fallback)
        with pytest.raises(ElevenLabsError, match="неполное"):
            await tts.save_wav("hello", path)
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]
    fallback.assert_not_called()


async def test_voice_listing_paginates_without_requiring_write_permissions():
    async def handler(request):
        assert request.headers["xi-api-key"] == "key"
        if request.query.get("next_page_token") == "next":
            return web.json_response(
                {"voices": [{"voice_id": "two"}], "has_more": False}
            )
        return web.json_response(
            {
                "voices": [{"voice_id": "one"}],
                "has_more": True,
                "next_page_token": "next",
            }
        )

    async with server(handler, "/v2/voices") as url:
        assert await list_voices("key", base_url=url) == [
            {"voice_id": "one"},
            {"voice_id": "two"},
        ]


async def test_preconnect_is_reused_and_sends_no_text_before_reply(tmp_path, caplog):
    connected = asyncio.Event()
    connections, frames = [], []

    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        connections.append(socket)
        frames.append(await socket.receive_json())
        connected.set()
        frames.append(await socket.receive_json())
        frames.append(await socket.receive_json())
        await socket.send_json(audio(b"\x01\x00"))
        await socket.send_json({"is_final": True})
        return socket

    async with server(handler) as url:
        tts = ElevenLabsTTS("key", "voice", base_url=url)
        with caplog.at_level(logging.INFO):
            async with tts.prepare_reply():
                await asyncio.wait_for(connected.wait(), 2)
                # Registration alone does not trigger synthesis or send user text.
                assert frames == [{"voices": ["voice"]}]
                await tts.save_wav(
                    "First sentence. Second sentence!", tmp_path / "sample.wav"
                )
    assert len(connections) == 1
    assert frames[1]["inputs"][0]["text"] == "First sentence. Second sentence!"
    ready = next(
        r.timing
        for r in caplog.records
        if hasattr(r, "timing") and r.timing["stage"] == "elevenlabs_ready"
    )
    assert ready["preconnected"] is True


async def test_failed_model_cancels_pending_preconnect_and_closes_transport(
    monkeypatch,
):
    waiting, cancelled = asyncio.Event(), asyncio.Event()
    sessions = []

    class Session:
        def __init__(self, **kwargs):
            self.closed = False
            sessions.append(self)

        async def ws_connect(self, *args, **kwargs):
            waiting.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def close(self):
            self.closed = True

    monkeypatch.setattr("clawsona.elevenlabs_tts.aiohttp.ClientSession", Session)
    tts = ElevenLabsTTS("key", "voice")
    with pytest.raises(RuntimeError, match="model failed"):
        async with tts.prepare_reply():
            await asyncio.wait_for(waiting.wait(), 2)
            raise RuntimeError("model failed")
    assert cancelled.is_set()
    assert sessions[0].closed


async def test_unused_preconnect_keeps_alive_and_closes_after_model_failure(
    monkeypatch,
):
    ready, keepalive, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    received = []
    monkeypatch.setattr("clawsona.elevenlabs_tts.KEEP_ALIVE_INTERVAL_S", 0.01)

    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        received.append(await socket.receive_json())
        ready.set()
        async for frame in socket:
            received.append(frame.json())
            keepalive.set()
        closed.set()
        return socket

    async with server(handler) as url:
        tts = ElevenLabsTTS("key", "voice", base_url=url)
        with pytest.raises(RuntimeError, match="model failed"):
            async with tts.prepare_reply():
                await asyncio.wait_for(ready.wait(), 2)
                await asyncio.wait_for(keepalive.wait(), 2)
                raise RuntimeError("model failed")
        await asyncio.wait_for(closed.wait(), 2)
    assert received[0] == {"voices": ["voice"]}
    assert all(frame == {"keep_alive": True} for frame in received[1:])


async def test_preconnect_failure_defers_to_fallback_without_aborting_model():
    fallback = Mock(speak=AsyncMock())

    async def handler(request):
        return web.Response(status=503, text="secret")

    async with server(handler) as url:
        tts = ElevenLabsTTS(
            "key", "voice", base_url=url, fallback_factory=lambda: fallback
        )
        async with tts.prepare_reply():
            # Connection failure must not exit the context or cancel model work.
            await asyncio.sleep(0.02)
            await tts.speak("completed model reply")
    fallback.speak.assert_awaited_once_with("completed model reply")


def test_factory_validates_credentials_and_does_not_load_piper(monkeypatch):
    piper = Mock(side_effect=AssertionError("Piper must be lazy"))
    monkeypatch.setattr("clawsona.multilingual_tts.MultilingualPiperTTS", piper)
    config = Settings(
        _env_file=None,
        tts_provider="elevenlabs",
        elevenlabs_api_key="",
        elevenlabs_voice_id="",
    )
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        create_tts(config)
    config.elevenlabs_api_key = "key"
    with pytest.raises(ValueError, match="ELEVENLABS_VOICE_ID"):
        create_tts(config)
    config.elevenlabs_voice_id = "voice"
    assert isinstance(create_tts(config), ElevenLabsTTS)
    piper.assert_not_called()
    assert "elevenlabs_api_key=" not in repr(config)
