import io

import edge_tts
import numpy as np
from pydub import AudioSegment

from clawsona.audio_io import play_audio_async
from clawsona.timing import mark_first_audio, stage_timer

PLAYBACK_SAMPLE_RATE = 24000


class TTSClient:
    def __init__(self, voice: str | None = None, device=None):
        self._device = device
        if voice is not None:
            self.voice = voice
        else:
            try:
                from clawsona.config import Settings

                self.voice = Settings().tts_voice
            except Exception:
                self.voice = "ru-RU-DmitryNeural"

    async def synthesize_mp3(self, text: str) -> bytes:
        communicate = edge_tts.Communicate(text, self.voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    async def speak(self, text: str) -> None:
        with stage_timer("tts_cloud_synthesis", voice=self.voice):
            mp3_data = await self.synthesize_mp3(text)
        with stage_timer("tts_audio_decode"):
            segment = AudioSegment.from_mp3(io.BytesIO(mp3_data))
            segment = (
                segment.set_frame_rate(PLAYBACK_SAMPLE_RATE)
                .set_channels(1)
                .set_sample_width(2)
            )
            samples = np.array(segment.get_array_of_samples(), dtype=np.int16)
        with stage_timer("tts_playback", audio_ms=round(len(samples) / 24, 1)):
            mark_first_audio()
            if self._device is None:
                await play_audio_async(
                    samples.tobytes(), sample_rate=PLAYBACK_SAMPLE_RATE
                )
            else:
                await play_audio_async(
                    samples.tobytes(),
                    sample_rate=PLAYBACK_SAMPLE_RATE,
                    device=self._device,
                )
