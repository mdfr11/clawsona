import asyncio
import io
import threading
import wave
from pathlib import Path

import numpy as np

from clawsona.languages import speech_parts
from clawsona.local_speech import PiperTTS
from clawsona.timing import stage_timer


class MultilingualPiperTTS:
    """Route Russian and English spans to their local Piper models."""

    def __init__(self, russian_path, english_path, device=None):
        self._paths = {"ru": russian_path, "en": english_path}
        self._device = device
        self._voices = {"ru": PiperTTS(russian_path, device=device)}
        self._cancelled = threading.Event()
        self._last_language = "ru"

    async def _voice(self, language):
        if language not in self._voices:
            with stage_timer("startup_tts_language", language=language):
                self._voices[language] = await asyncio.to_thread(
                    PiperTTS, self._paths[language], device=self._device
                )
        return self._voices[language]

    async def speak(self, text: str) -> None:
        self._cancelled.clear()
        try:
            for language, part in speech_parts(text, self._last_language):
                if self._cancelled.is_set():
                    return
                voice = await self._voice(language)
                if self._cancelled.is_set():
                    return
                await voice.speak(part.strip())
                self._last_language = language
        except asyncio.CancelledError:
            self.stop()
            raise

    def stop(self):
        self._cancelled.set()
        for voice in self._voices.values():
            voice.stop()

    async def save_wav(self, text: str, path: Path) -> None:
        from faster_whisper.audio import decode_audio

        parts = speech_parts(text, self._last_language)
        for language, _ in parts:
            await self._voice(language)

        def synthesize():
            sample_rate = self._voices["ru"]._voice.config.sample_rate
            with stage_timer(
                "tts_export", chars=len(text), languages=[p[0] for p in parts]
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                with wave.open(str(path), "wb") as output:
                    output.setnchannels(1)
                    output.setsampwidth(2)
                    output.setframerate(sample_rate)
                    for language, part in parts:
                        buffer = io.BytesIO()
                        with wave.open(buffer, "wb") as wav:
                            self._voices[language]._voice.synthesize_wav(
                                part.strip(), wav
                            )
                        buffer.seek(0)
                        pcm = (
                            decode_audio(buffer, sampling_rate=sample_rate) * 32767
                        ).astype(np.int16)
                        output.writeframes(pcm.tobytes())

        await asyncio.to_thread(synthesize)
