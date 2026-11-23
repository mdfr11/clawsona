"""Eleven v4 dialogue WebSocket → streaming mono PCM, without an extra SDK."""

import asyncio
import base64
import binascii
import logging
import os
import tempfile
import threading
import time
import wave
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
import sounddevice as sd

from clawsona.timing import log_timing, mark_first_audio, stage_timer

logger = logging.getLogger(__name__)
API_URL = "https://api.elevenlabs.io"
SAMPLE_RATE = 24000
KEEP_ALIVE_INTERVAL_S = 10


class ElevenLabsError(RuntimeError):
    """Safe to log: provider payloads and credentials never enter the message."""


@dataclass
class _Connection:
    session: aiohttp.ClientSession
    socket: aiohttp.ClientWebSocketResponse
    keepalive: asyncio.Task = field(init=False)

    def __post_init__(self):
        self.keepalive = asyncio.create_task(self._keep_alive())

    async def _keep_alive(self):
        try:
            while True:
                await asyncio.sleep(KEEP_ALIVE_INTERVAL_S)
                await self.socket.send_json({"keep_alive": True})
        except (aiohttp.ClientError, ConnectionError):
            # The receiving code handles a closed socket; no provider text is logged.
            return

    async def stop_keepalive(self):
        self.keepalive.cancel()
        await asyncio.gather(self.keepalive, return_exceptions=True)

    async def close(self):
        await self.stop_keepalive()
        try:
            await asyncio.wait_for(self.socket.close(), 1)
        except (TimeoutError, aiohttp.ClientError):
            pass
        finally:
            await self.session.close()


def _http_error(status):
    hint = {
        401: "проверьте ELEVENLABS_API_KEY",
        402: "проверьте баланс и тариф",
        403: "проверьте права Text to Speech / Voices",
        429: "лимит запросов или доступных кредитов",
    }.get(status, "проверьте доступность сервиса")
    return ElevenLabsError(f"ElevenLabs: HTTP {status}; {hint}")


async def list_voices(api_key, *, base_url=API_URL, timeout_s=30):
    if not api_key:
        raise ValueError("Задайте ELEVENLABS_API_KEY в .env")
    voices = []
    params = {"page_size": "100", "include_total_count": "false"}
    seen = set()
    try:
        async with aiohttp.ClientSession(
            headers={"xi-api-key": api_key},
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as session:
            while True:
                async with session.get(
                    f"{base_url}/v2/voices", params=params
                ) as response:
                    if response.status != 200:
                        raise _http_error(response.status)
                    data = await response.json()
                voices.extend(data.get("voices", []))
                if not data.get("has_more"):
                    return voices
                token = data.get("next_page_token")
                if not token or token in seen:
                    raise ElevenLabsError("ElevenLabs: некорректная пагинация голосов")
                seen.add(token)
                params["next_page_token"] = token
    except (aiohttp.ClientError, TimeoutError):
        raise ElevenLabsError(
            "ElevenLabs: не удалось получить голоса; проверьте сеть"
        ) from None


class ElevenLabsTTS:
    def __init__(
        self,
        api_key,
        voice_id,
        model="eleven_v4_turbo",
        device=None,
        timeout_s=45,
        fallback_factory=None,
        *,
        base_url=API_URL,
    ):
        if not api_key:
            raise ValueError("Для TTS_PROVIDER=elevenlabs задайте ELEVENLABS_API_KEY")
        if not voice_id:
            raise ValueError(
                "Задайте ELEVENLABS_VOICE_ID; список: clawsona elevenlabs-voices"
            )
        self._api_key = api_key
        self._voice_id = voice_id
        self._model = model
        self._device = device
        self._timeout_s = timeout_s
        self._base_url = base_url.rstrip("/")
        self._fallback_factory = fallback_factory
        self._fallback = None
        self._stopped = threading.Event()
        self._output_lock = threading.Lock()
        self._output = None
        self._task = None
        self._loop = None
        self._serial = asyncio.Lock()
        self._preparation = None

    async def _connect(self):
        session = aiohttp.ClientSession(
            headers={"xi-api-key": self._api_key},
            timeout=aiohttp.ClientTimeout(total=self._timeout_s),
        )
        try:
            with stage_timer("elevenlabs_connect"):
                socket = await session.ws_connect(
                    f"{self._base_url}/v1/text-to-dialogue/stream-input",
                    params={"model_id": self._model, "output_format": "pcm_24000"},
                )
                await socket.send_json({"voices": [self._voice_id]})
            return _Connection(session, socket)
        except BaseException:
            await session.close()
            raise

    @asynccontextmanager
    async def prepare_reply(self):
        """Overlap connection setup with model work; never send text speculatively."""
        preparation = asyncio.create_task(self._connect())
        self._preparation = preparation
        try:
            yield
        finally:
            self._preparation = None
            if not preparation.done():
                preparation.cancel()
            # Retrieve failures even when the LLM fails before TTS consumes the task.
            (result,) = await asyncio.gather(preparation, return_exceptions=True)
            if isinstance(result, _Connection):
                await result.close()

    async def _pcm(self, text):
        started = time.perf_counter()
        pending = b""
        received = False
        connection = None
        try:
            preparation, self._preparation = self._preparation, None
            connection = (
                await preparation if preparation is not None else await self._connect()
            )
            preconnected = preparation is not None
            await connection.stop_keepalive()
            if connection.socket.closed:
                await connection.close()
                connection = await self._connect()
                await connection.stop_keepalive()
                preconnected = False
            log_timing(
                "elevenlabs_ready",
                time.perf_counter() - started,
                preconnected=preconnected,
            )
            socket = connection.socket
            await socket.send_json(
                {"inputs": [{"text": text, "voice_id": self._voice_id}]}
            )
            # Also flushes short acknowledgements below the buffer threshold.
            await socket.send_json({"close_socket": True})
            while True:
                message = await asyncio.wait_for(socket.receive(), self._timeout_s)
                if message.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    break
                if message.type != aiohttp.WSMsgType.TEXT:
                    raise ElevenLabsError("ElevenLabs: поток прерван")
                try:
                    data = message.json()
                except ValueError:
                    raise ElevenLabsError(
                        "ElevenLabs: неверный ответ сервера"
                    ) from None
                if not isinstance(data, dict):
                    raise ElevenLabsError("ElevenLabs: неверный ответ сервера")
                if data.get("error") or data.get("message") or data.get("code"):
                    # Do not echo upstream errors: they can contain input or secrets.
                    raise ElevenLabsError(
                        "ElevenLabs отклонил синтез; проверьте голос, модель, "
                        "права Text to Speech и баланс в кабинете"
                    )
                if data.get("audio"):
                    try:
                        pending += base64.b64decode(data["audio"], validate=True)
                    except (ValueError, binascii.Error):
                        raise ElevenLabsError(
                            "ElevenLabs: неверные аудиоданные"
                        ) from None
                    size = len(pending) - len(pending) % 2
                    if size:
                        if not received:
                            log_timing(
                                "elevenlabs_first_chunk",
                                time.perf_counter() - started,
                            )
                        received = True
                        chunk, pending = pending[:size], pending[size:]
                        yield chunk
                if data.get("is_final"):
                    if pending or not received:
                        raise ElevenLabsError("ElevenLabs: пустое или неполное аудио")
                    return
            raise ElevenLabsError(
                "ElevenLabs: поток завершился без финального сообщения"
            )
        except aiohttp.WSServerHandshakeError as exc:
            raise _http_error(exc.status) from None
        except (aiohttp.ClientError, TimeoutError):
            raise ElevenLabsError(
                "ElevenLabs: ошибка сети или превышено время ожидания"
            ) from None
        finally:
            if connection is not None:
                await connection.close()

    def _abort(self):
        with self._output_lock:
            output = self._output
        if output is not None:
            try:
                output.abort()
            except sd.PortAudioError:
                pass

    async def _device_call(self, action, *args):
        # Cancellation must join the worker before the stream can be closed/reused.
        worker = asyncio.create_task(asyncio.to_thread(action, *args))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            self._stopped.set()
            self._abort()
            try:
                await worker
            except Exception:
                pass
            raise

    def _open(self):
        output = sd.RawOutputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=self._device
        )
        with self._output_lock:
            self._output = output
        if not self._stopped.is_set():
            output.start()

    def _close(self, completed):
        with self._output_lock:
            output = self._output
        if output is not None:
            try:
                if completed and not self._stopped.is_set():
                    output.stop()
                else:
                    output.abort()
            finally:
                try:
                    output.close()
                finally:
                    with self._output_lock:
                        self._output = None

    async def speak(self, text):
        if not text.strip():
            return
        async with self._serial:
            self._stopped.clear()
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.current_task()
            audible = completed = False
            started = time.perf_counter()
            samples = 0
            write_s = 0.0
            try:
                try:
                    with stage_timer(
                        "elevenlabs", voice=self._voice_id, model=self._model
                    ) as metrics:
                        try:
                            async with aclosing(self._pcm(text)) as chunks:
                                async for chunk in chunks:
                                    if self._output is None:
                                        before = time.perf_counter()
                                        await self._device_call(self._open)
                                        metrics["device_open_ms"] = (
                                            time.perf_counter() - before
                                        ) * 1000
                                    for offset in range(0, len(chunk), 4800):
                                        if self._stopped.is_set():
                                            raise asyncio.CancelledError
                                        if not audible:
                                            log_timing(
                                                "tts_first_pcm",
                                                time.perf_counter() - started,
                                                provider="elevenlabs",
                                            )
                                            mark_first_audio()
                                            audible = True
                                        part = chunk[offset : offset + 4800]
                                        before = time.perf_counter()
                                        await self._device_call(
                                            self._output.write, part
                                        )
                                        write_s += time.perf_counter() - before
                                        samples += len(part) // 2
                            completed = True
                        finally:
                            before = time.perf_counter()
                            await self._device_call(self._close, completed)
                            metrics.update(
                                output_write_ms=write_s * 1000,
                                output_drain_ms=(time.perf_counter() - before) * 1000,
                                audio_ms=samples / SAMPLE_RATE * 1000,
                            )
                except ElevenLabsError as exc:
                    if (
                        audible
                        or self._fallback_factory is None
                        or self._stopped.is_set()
                    ):
                        raise
                    logger.warning("%s. Резервная локальная озвучка Piper.", exc)
                    if self._fallback is None:
                        self._fallback = await asyncio.to_thread(self._fallback_factory)
                    await self._fallback.speak(text)
            finally:
                self._task = self._loop = None

    def stop(self):
        self._stopped.set()
        self._abort()
        if self._fallback is not None:
            self._fallback.stop()
        if self._task is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)

    async def save_wav(self, text, path):
        """Explicit provider test: atomic export, no speaker and no local fallback."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(suffix=".wav", dir=path.parent)
        os.close(fd)
        try:
            with stage_timer(
                "tts_export",
                provider="elevenlabs",
                voice=self._voice_id,
                model=self._model,
            ):
                with wave.open(temporary, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(SAMPLE_RATE)
                    async with aclosing(self._pcm(text)) as chunks:
                        async for chunk in chunks:
                            wav.writeframesraw(chunk)
                os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
