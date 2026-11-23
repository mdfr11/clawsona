"""Print speech start/end events from the configured microphone."""

import time

from clawsona.audio_io import AudioCapture
from clawsona.config import Settings
from clawsona.vad import CHUNK_SIZE, VADDetector


def main():
    config = Settings()
    cap = AudioCapture(config.sample_rate, CHUNK_SIZE, config.input_device)
    vad = VADDetector(
        config.vad_silence_duration_ms, config.vad_min_speech_ms, config.vad_threshold
    )
    print("Ожидаю речь. Ctrl+C для выхода.", flush=True)
    try:
        cap.start()
        while True:
            event = vad.process_chunk(
                cap.read_sync(timeout=config.audio_read_timeout_s)
            )
            if event:
                print(f"[{time.strftime('%H:%M:%S')}] {event}", flush=True)
    finally:
        cap.stop()


if __name__ == "__main__":
    main()
