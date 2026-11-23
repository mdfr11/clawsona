import numpy as np

SAMPLE_RATE = 16000
FRAME_MS = 32
CHUNK_SIZE = SAMPLE_RATE * FRAME_MS // 1000


class VADDetector:
    """Stateful Silero ONNX speech detector using faster-whisper's bundled model."""

    def __init__(self, silence_duration_ms=1800, min_speech_ms=180, threshold=0.6):
        from faster_whisper.vad import get_vad_model

        self._session = get_vad_model().session
        self._threshold = threshold
        self._silence_duration_ms = silence_duration_ms
        self._min_speech_ms = min_speech_ms
        self.reset()

    def process_chunk(self, chunk: np.ndarray) -> str | None:
        if chunk.dtype != np.int16 or chunk.size != CHUNK_SIZE:
            raise ValueError(
                f"VAD expects {CHUNK_SIZE} mono int16 samples (32 ms at 16 kHz)"
            )
        audio = chunk.reshape(1, -1).astype(np.float32) / 32768.0
        # Keep recurrent state and 64-sample context between frames. Resetting
        # the network on each frame loses the evidence needed to distinguish noise.
        probability, self._h, self._c = self._session.run(
            None,
            {
                "input": np.concatenate((self._context, audio), axis=1),
                "h": self._h,
                "c": self._c,
            },
        )
        self._context = audio[:, -64:].copy()
        self.last_probability = float(np.asarray(probability).reshape(-1)[-1])
        threshold = (
            max(0.01, self._threshold - 0.15) if self._speaking else self._threshold
        )
        is_speech = self.last_probability >= threshold
        if is_speech:
            self._silence_ms = 0
            self._speech_ms += FRAME_MS
            if not self._speaking and self._speech_ms >= self._min_speech_ms:
                self._speaking = True
                return "speech_start"
        elif not self._speaking:
            self._speech_ms = 0
        else:
            self._silence_ms += FRAME_MS
            if self._silence_ms >= self._silence_duration_ms:
                self.last_end_silence_ms = self._silence_ms
                self._speaking = False
                self._speech_ms = 0
                self._silence_ms = 0
                return "speech_end"
        return None

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, 64), dtype=np.float32)
        self._speaking = False
        self._speech_ms = 0
        self._silence_ms = 0
        self.last_probability = 0.0
        self.last_end_silence_ms = 0
