"""Record five seconds from the configured mic to /tmp/test_audio.wav."""

import wave

import numpy as np

from clawsona.audio_io import AudioCapture
from clawsona.config import Settings


def main():
    config = Settings()
    capture = AudioCapture(config.sample_rate, 480, config.input_device)
    target_samples = config.sample_rate * 5
    collected = 0
    chunks = []
    print("Запись пяти секунд. Говорите.", flush=True)
    try:
        capture.start()
        while collected < target_samples:
            chunk = capture.read_sync(timeout=config.audio_read_timeout_s)
            chunks.append(chunk)
            collected += chunk.size
    finally:
        capture.stop()
    output = "/tmp/test_audio.wav"
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(config.sample_rate)
        wav.writeframes(np.concatenate(chunks).tobytes())
    print(f"Сохранено: {output}")


if __name__ == "__main__":
    main()
