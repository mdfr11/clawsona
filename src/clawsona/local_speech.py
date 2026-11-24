import asyncio
import logging
import math
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from clawsona.timing import log_timing, mark_first_audio, stage_timer

logger = logging.getLogger(__name__)


class LocalSTT:
    def __init__(
        self,
        model_path,
        cpu_threads=4,
        wake_word="",
        name_aliases=(),
        hotwords="",
        beam_size=5,
        min_logprob=-1.0,
        max_no_speech_prob=0.5,
        max_compression_ratio=2.4,
        vad_threshold=0.6,
        min_speech_ms=180,
        language="auto",
    ):
        from faster_whisper import WhisperModel

        if not (model_path / "model.bin").is_file():
            raise FileNotFoundError(
                f"Нет модели Whisper {model_path.name}. Выполните clawsona setup --only stt"
            )
        self._model = WhisperModel(
            str(model_path),
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads,
            num_workers=1,
            local_files_only=True,
        )
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        self._speech_timestamps = get_speech_timestamps
        self._vad_options = VadOptions(
            threshold=vad_threshold,
            min_speech_duration_ms=min_speech_ms,
            min_silence_duration_ms=250,
            speech_pad_ms=120,
        )
        # Used only after the independent acoustic speech check below.
        names = [name for name in [wake_word, *name_aliases] if name]
        self._wake_prompt = f"{wake_word}." if wake_word else None
        english_name = next((name for name in names if name.isascii()), None)
        self._english_wake_prompt = f"{english_name}." if english_name else None
        self._hotwords = hotwords.strip() or None
        self._min_logprob = min_logprob
        self._max_no_speech_prob = max_no_speech_prob
        self._max_compression_ratio = max_compression_ratio
        self.last_rejection_reason = None
        self.last_transcript = ""
        self._beam_size = beam_size
        self._model_name = model_path.name
        self._language = language
        self.last_language = None
        self.last_language_probability = None

    def _transcribe(self, audio_data: bytes) -> str:
        audio = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
        self.last_rejection_reason = None
        self.last_transcript = ""
        self.last_language = None
        self.last_language_probability = None
        with stage_timer(
            "stt",
            audio_ms=round(len(audio) / 16, 1),
            model=self._model_name,
            beam_size=self._beam_size,
        ) as metrics:
            with stage_timer("stt_vad"):
                regions = self._speech_timestamps(audio, self._vad_options)
            if not regions:
                text = self._reject("no_speech")
            else:
                language = self._select_language(audio)
                # Decoding is lazy: consume segments inside the measured scope.
                with stage_timer("stt_decode"):
                    text = self._decode(audio, language)
            metrics["result"] = self.last_rejection_reason or "accepted"
            if self.last_language:
                metrics["language"] = self.last_language
                metrics["language_probability"] = self.last_language_probability
            return text

    def _select_language(self, audio: np.ndarray) -> str:
        language = self._language
        probability = 1.0
        if language == "auto":
            with stage_timer("stt_language"):
                detected, probability, alternatives = self._model.detect_language(
                    audio=audio
                )
                supported = [
                    (lang, prob) for lang, prob in alternatives if lang in {"ru", "en"}
                ]
                language, probability = (
                    max(supported, key=lambda item: item[1])
                    if supported
                    else (detected, probability)
                )
        self.last_language = language
        self.last_language_probability = round(probability, 3)
        return language

    def _decode(self, audio: np.ndarray, language: str) -> str:
        # Retain the recorder's pre-roll and pauses: trimming to exact VAD
        # boundaries can lose a short name or destabilize Whisper's decoding.
        segments, _ = self._model.transcribe(
            audio,
            language=language,
            task="transcribe",
            beam_size=self._beam_size,
            condition_on_previous_text=False,
            temperature=0.0,
            no_speech_threshold=self._max_no_speech_prob,
            log_prob_threshold=self._min_logprob,
            compression_ratio_threshold=self._max_compression_ratio,
            vad_filter=False,
            initial_prompt=self._wake_prompt
            if language == "ru"
            else self._english_wake_prompt,
            hotwords=self._hotwords,
        )
        accepted = []
        for segment in segments:
            self.last_transcript = " ".join([*accepted, segment.text.strip()]).strip()
            metrics = (
                segment.avg_logprob,
                segment.no_speech_prob,
                segment.compression_ratio,
            )
            if not all(math.isfinite(value) for value in metrics):
                return self._reject("invalid_confidence")
            if segment.avg_logprob < self._min_logprob:
                return self._reject("low_confidence")
            if segment.no_speech_prob > self._max_no_speech_prob:
                return self._reject("likely_silence")
            if segment.compression_ratio > self._max_compression_ratio:
                return self._reject("repetitive_decoding")
            accepted.append(segment.text.strip())
        text = " ".join(accepted).strip()
        return text if text else self._reject("empty_transcript")

    def _reject(self, reason):
        self.last_rejection_reason = reason
        logger.debug("Speech candidate ignored: %s", reason)
        return ""

    async def transcribe_buffer(self, audio_data: bytes) -> str:
        if not audio_data:
            self.last_transcript = ""
            self.last_rejection_reason = "empty_audio"
            self.last_language = None
            self.last_language_probability = None
            return ""
        worker = asyncio.create_task(asyncio.to_thread(self._transcribe, audio_data))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Whisper's CPU work cannot be cancelled. Join it before a subsequent
            # recording can reuse the model or its recognition diagnostics.
            await asyncio.gather(worker, return_exceptions=True)
            raise


class PiperTTS:
    def __init__(self, model_path, device=None):
        from piper import PiperVoice

        if (
            not model_path.is_file()
            or not model_path.with_suffix(".onnx.json").is_file()
        ):
            raise FileNotFoundError(
                f"Нет голоса Piper {model_path.stem}. "
                f"Выполните clawsona setup --only tts --voice {model_path.stem}"
            )
        self._voice = PiperVoice.load(str(model_path), use_cuda=False)
        self._voice_name = model_path.stem
        self._device = device
        self._cancelled = threading.Event()
        self._output_lock = threading.Lock()
        self._output = None

    def _speak(self, text: str) -> None:
        # Streaming PCM: no FFmpeg, MP3 conversion, temporary file or cloud call.
        started = time.perf_counter()
        synthesis_s = write_s = 0.0
        samples = 0
        first_pcm_s = None
        drain_started = None
        completed = False
        with stage_timer("piper", voice=self._voice_name, chars=len(text)) as metrics:
            try:
                with sd.OutputStream(
                    samplerate=self._voice.config.sample_rate,
                    channels=1,
                    dtype="int16",
                    device=self._device,
                ) as stream:
                    metrics["device_open_ms"] = round(
                        (time.perf_counter() - started) * 1000, 3
                    )
                    with self._output_lock:
                        self._output = stream
                    chunks = iter(self._voice.synthesize(text))
                    try:
                        while not self._cancelled.is_set():
                            before = time.perf_counter()
                            try:
                                chunk = next(chunks)
                            except StopIteration:
                                break
                            finally:
                                synthesis_s += time.perf_counter() - before
                            if self._cancelled.is_set():
                                break
                            pcm = np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
                            if first_pcm_s is None:
                                first_pcm_s = time.perf_counter() - started
                                log_timing(
                                    "tts_first_pcm", first_pcm_s, voice=self._voice_name
                                )
                                mark_first_audio()
                            before = time.perf_counter()
                            try:
                                stream.write(pcm)
                            finally:
                                write_s += time.perf_counter() - before
                            samples += pcm.size
                    finally:
                        # OutputStream.__exit__ drains remaining buffered PCM.
                        drain_started = time.perf_counter()
                completed = True
            finally:
                with self._output_lock:
                    self._output = None
                metrics.update(
                    synthesis_ms=round(synthesis_s * 1000, 3),
                    output_write_ms=round(write_s * 1000, 3),
                    output_drain_ms=round(
                        (time.perf_counter() - drain_started) * 1000, 3
                    )
                    if drain_started is not None
                    else 0.0,
                    audio_ms=round(samples / self._voice.config.sample_rate * 1000, 3),
                    result="cancelled"
                    if self._cancelled.is_set()
                    else "completed"
                    if completed
                    else "failed",
                )

    async def save_wav(self, text: str, path: Path) -> None:
        """Export a voice sample without opening a speaker or starting an LLM."""

        def synthesize():
            with stage_timer("tts_export", voice=self._voice_name, chars=len(text)):
                path.parent.mkdir(parents=True, exist_ok=True)
                with wave.open(str(path), "wb") as wav:
                    self._voice.synthesize_wav(text, wav)

        await asyncio.to_thread(synthesize)

    async def speak(self, text: str) -> None:
        self._cancelled.clear()
        worker = asyncio.create_task(asyncio.to_thread(self._speak, text))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            self.stop()
            await asyncio.gather(worker, return_exceptions=True)
            raise

    def stop(self) -> None:
        self._cancelled.set()
        with self._output_lock:
            if self._output is not None:
                self._output.abort()


def create_stt(config):
    if config.stt_provider == "local":
        return LocalSTT(
            config.whisper_model_path,
            cpu_threads=config.whisper_cpu_threads,
            wake_word=config.wake_word,
            name_aliases=config.assistant_aliases,
            hotwords=config.stt_hotwords,
            beam_size=config.whisper_beam_size,
            min_logprob=config.stt_min_logprob,
            max_no_speech_prob=config.stt_max_no_speech_prob,
            max_compression_ratio=config.stt_max_compression_ratio,
            vad_threshold=config.vad_threshold,
            min_speech_ms=config.vad_min_speech_ms,
            language=config.stt_language,
        )
    if not config.deepgram_api_key:
        raise ValueError("Для STT_PROVIDER=deepgram задайте DEEPGRAM_API_KEY")
    from clawsona.stt import DeepgramSTT

    return DeepgramSTT(api_key=config.deepgram_api_key)


def create_tts(config):
    if config.tts_provider == "elevenlabs":
        from clawsona.elevenlabs_tts import ElevenLabsTTS

        def fallback():
            from clawsona.multilingual_tts import MultilingualPiperTTS

            return MultilingualPiperTTS(
                config.piper_model_path,
                config.piper_english_model_path,
                device=config.output_device,
            )

        return ElevenLabsTTS(
            config.elevenlabs_api_key,
            config.elevenlabs_voice_id,
            model=config.elevenlabs_model,
            device=config.output_device,
            timeout_s=config.elevenlabs_timeout_s,
            fallback_factory=fallback if config.elevenlabs_fallback else None,
        )
    if config.tts_provider == "piper":
        from clawsona.multilingual_tts import MultilingualPiperTTS

        return MultilingualPiperTTS(
            config.piper_model_path,
            config.piper_english_model_path,
            device=config.output_device,
        )
    from clawsona.tts import TTSClient

    return TTSClient(voice=config.tts_voice, device=config.output_device)
