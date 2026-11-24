import asyncio
import logging
import queue
import threading

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)
CHANNELS = 1


class AudioCapture:
    def __init__(self, sample_rate: int = 16000, chunk_size: int = 480, device=None):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.device = device
        self._q: queue.Queue = queue.Queue(
            maxsize=max(2, sample_rate * 2 // chunk_size)
        )
        self._stream = None
        self._loop = None
        self._ready = None

    def _sd_callback(self, indata, frames, time, status) -> None:
        if status:
            logger.debug("Audio input: %s", status)
        try:
            self._q.put_nowait(indata.copy())
        except queue.Full:
            # A slow consumer must not block PortAudio or grow memory indefinitely.
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(indata.copy())
            except queue.Full:
                pass
        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._ready.set)
            except RuntimeError:
                pass  # The loop can close between the check and the callback.

    def _clear_queue(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    def start(self) -> None:
        if self._stream is not None:
            return
        self._clear_queue()
        kwargs = {
            "samplerate": self.sample_rate,
            "channels": CHANNELS,
            "dtype": "int16",
            "blocksize": self.chunk_size,
            "callback": self._sd_callback,
        }
        if self.device is not None:
            kwargs["device"] = self.device
        stream = sd.InputStream(**kwargs)
        try:
            stream.start()
        except BaseException:
            stream.close()
            raise
        self._stream = stream

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        self._clear_queue()

    def read_sync(self, timeout=None) -> np.ndarray:
        return self._q.get(timeout=timeout)

    async def read_async(self) -> np.ndarray:
        # The callback wakes the event loop; cancellation leaves no queue reader
        # in a worker thread that could steal audio from the next recording.
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._ready = asyncio.Event()
            self._loop = loop
        while True:
            self._ready.clear()
            try:
                return self._q.get_nowait()
            except queue.Empty:
                await self._ready.wait()

    async def stream(self):
        while True:
            yield await self.read_async()


def _play_sync(
    audio_data: bytes, sample_rate: int = 44100, device=None, cancelled=None
) -> None:
    if cancelled is not None and cancelled.is_set():
        return
    sd.play(
        np.frombuffer(audio_data, dtype=np.int16), samplerate=sample_rate, device=device
    )
    if cancelled is not None and cancelled.is_set():
        sd.stop()
    sd.wait()


async def play_audio_async(
    audio_data: bytes, sample_rate: int = 44100, device=None
) -> None:
    cancelled = threading.Event()
    worker = asyncio.create_task(
        asyncio.to_thread(_play_sync, audio_data, sample_rate, device, cancelled)
    )
    try:
        await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancelled.set()
        sd.stop()
        await asyncio.gather(worker, return_exceptions=True)
        raise
