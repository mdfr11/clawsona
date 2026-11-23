"""Record one Russian utterance and transcribe with the configured STT provider."""

import asyncio

from clawsona.audio_io import AudioCapture
from clawsona.config import Settings
from clawsona.local_speech import create_stt
from clawsona.orchestrator import Orchestrator
from clawsona.vad import CHUNK_SIZE, VADDetector


async def main():
    config = Settings()
    audio = AudioCapture(config.sample_rate, CHUNK_SIZE, config.input_device)
    vad = VADDetector(
        config.vad_silence_duration_ms, config.vad_min_speech_ms, config.vad_threshold
    )
    orch = Orchestrator(config, audio, None, vad, create_stt(config), None, None)
    print("Говорите по-русски. После паузы появится текст.", flush=True)
    print(f"Распознано: {await orch._listen_and_transcribe()!r}")


if __name__ == "__main__":
    asyncio.run(main())
