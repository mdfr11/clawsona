"""Print locally recognized direct addresses; no cloud requests."""

import asyncio
import time

from clawsona.audio_io import AudioCapture
from clawsona.config import Settings
from clawsona.local_speech import create_stt
from clawsona.orchestrator import Orchestrator
from clawsona.vad import CHUNK_SIZE, VADDetector
from clawsona.wakeword import WakeWordDetector


async def main():
    config = Settings()
    detector = WakeWordDetector(config.assistant_name, config.assistant_aliases)
    audio = AudioCapture(config.sample_rate, CHUNK_SIZE, config.input_device)
    vad = VADDetector(
        config.vad_silence_duration_ms, config.vad_min_speech_ms, config.vad_threshold
    )
    recorder = Orchestrator(
        config, audio, detector, vad, create_stt(config), None, None
    )
    print(f"Ожидаю обращение {config.wake_word}. Ctrl+C для выхода.", flush=True)
    while True:
        text = await recorder._listen_and_transcribe()
        if text is not None:
            addressed = detector.extract(text)
            print(
                f"[{time.strftime('%H:%M:%S')}] {text!r}; обращение: {addressed!r}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
