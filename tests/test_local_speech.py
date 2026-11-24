import asyncio
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from clawsona.local_speech import LocalSTT, PiperTTS
from clawsona.timing import trace_turn


def segment(text="Привет", **overrides):
    return SimpleNamespace(
        **dict(text=text, avg_logprob=-0.3, no_speech_prob=0.01, compression_ratio=1.2)
        | overrides
    )


@pytest.fixture
def local_stt(tmp_path, mocker):
    (tmp_path / "model.bin").write_bytes(b"placeholder")
    model_class = mocker.patch("faster_whisper.WhisperModel")
    model_class.return_value.detect_language.return_value = (
        "ru",
        0.98,
        [("ru", 0.98), ("en", 0.02)],
    )
    timestamps = mocker.patch("faster_whisper.vad.get_speech_timestamps")
    timestamps.side_effect = lambda audio, options: [{"start": 0, "end": len(audio)}]
    model_class.return_value.transcribe.return_value = (iter([segment()]), None)
    return LocalSTT(
        tmp_path, cpu_threads=2, wake_word="Лютик", name_aliases=["Lyutik", "Lutik"]
    )


@pytest.mark.asyncio
async def test_whisper_receives_correct_audio_format_and_offline_settings(local_stt):
    local_stt._model.transcribe.return_value = (
        iter([segment(" Привет "), segment(" мир ")]),
        None,
    )
    assert (
        await local_stt.transcribe_buffer(
            np.array([16384, -16384], dtype=np.int16).tobytes()
        )
        == "Привет мир"
    )
    # Inspect the constructor without loading a model or using the network.
    from faster_whisper import WhisperModel

    kwargs = WhisperModel.call_args.kwargs
    assert kwargs["local_files_only"] is True
    assert kwargs["compute_type"] == "int8"
    assert kwargs["cpu_threads"] == 2
    passed = local_stt._model.transcribe.call_args.args[0]
    np.testing.assert_allclose(passed, [0.5, -0.5])
    options = local_stt._model.transcribe.call_args.kwargs
    assert options["temperature"] == 0
    assert options["condition_on_previous_text"] is False
    assert options["initial_prompt"] == "Лютик."
    assert options["hotwords"] is None
    assert options["language"] == "ru"
    assert options["task"] == "transcribe"


@pytest.mark.asyncio
async def test_cancelled_whisper_check_finishes_before_model_can_be_reused(
    local_stt, mocker
):
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def decode(data):
        loop.call_soon_threadsafe(started.set)
        release.wait(3)
        finished.set()
        return "old result"

    mocker.patch.object(local_stt, "_transcribe", side_effect=decode)
    task = asyncio.create_task(local_stt.transcribe_buffer(b"\0\0"))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_no_speech_never_reaches_prompted_whisper(local_stt):
    local_stt._speech_timestamps.side_effect = None
    local_stt._speech_timestamps.return_value = []
    assert (
        await local_stt.transcribe_buffer(np.zeros(16000, dtype=np.int16).tobytes())
        == ""
    )
    assert local_stt.last_rejection_reason == "no_speech"
    local_stt._model.transcribe.assert_not_called()
    local_stt._model.detect_language.assert_not_called()


@pytest.mark.asyncio
async def test_english_is_transcribed_without_russian_language_or_name_prompt(
    local_stt,
):
    local_stt._model.detect_language.return_value = (
        "en",
        0.99,
        [("en", 0.99), ("ru", 0.01)],
    )
    local_stt._model.transcribe.return_value = (
        iter([segment("I want to practise English.")]),
        None,
    )
    text = await local_stt.transcribe_buffer(np.zeros(16000, dtype=np.int16).tobytes())
    assert text == "I want to practise English."
    options = local_stt._model.transcribe.call_args.kwargs
    assert options["language"] == "en"
    assert options["task"] == "transcribe"
    assert options["initial_prompt"] == "Lyutik."
    assert local_stt.last_language == "en"


@pytest.mark.asyncio
async def test_auto_language_is_limited_to_supported_russian_and_english(local_stt):
    local_stt._model.detect_language.return_value = (
        "uk",
        0.6,
        [("uk", 0.6), ("ru", 0.35), ("en", 0.05)],
    )
    await local_stt.transcribe_buffer(np.zeros(16000, dtype=np.int16).tobytes())
    assert local_stt._model.transcribe.call_args.kwargs["language"] == "ru"


@pytest.mark.parametrize("language,expected_prompt", [("ru", "Мира."), ("en", "Mira.")])
@pytest.mark.asyncio
async def test_custom_identity_reaches_language_specific_asr_prompt(
    local_stt, tmp_path, mocker, language, expected_prompt
):
    mocker.patch("faster_whisper.WhisperModel", return_value=local_stt._model)
    stt = LocalSTT(tmp_path, wake_word="Мира", name_aliases=["Mira"], language=language)
    await stt.transcribe_buffer(np.zeros(16000, dtype=np.int16).tobytes())
    assert stt._model.transcribe.call_args.kwargs["initial_prompt"] == expected_prompt


@pytest.mark.asyncio
async def test_explicit_language_skips_detection(local_stt):
    local_stt._language = "en"
    await local_stt.transcribe_buffer(np.zeros(16000, dtype=np.int16).tobytes())
    local_stt._model.detect_language.assert_not_called()
    assert local_stt._model.transcribe.call_args.kwargs["language"] == "en"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metrics,reason",
    [
        ({"avg_logprob": -1.2}, "low_confidence"),
        ({"no_speech_prob": 0.9}, "likely_silence"),
        ({"compression_ratio": 3.0}, "repetitive_decoding"),
        ({"avg_logprob": float("nan")}, "invalid_confidence"),
    ],
)
async def test_uncertain_decoding_is_not_forwarded(local_stt, metrics, reason):
    local_stt._model.transcribe.return_value = (iter([segment(**metrics)]), None)
    assert (
        await local_stt.transcribe_buffer(np.zeros(16000, dtype=np.int16).tobytes())
        == ""
    )
    assert local_stt.last_rejection_reason == reason
    assert local_stt.last_transcript == "Привет"


@pytest.mark.asyncio
async def test_confirmed_speech_keeps_preroll_and_pauses_for_name_recognition(
    local_stt,
):
    local_stt._speech_timestamps.side_effect = None
    local_stt._speech_timestamps.return_value = [
        {"start": 1, "end": 3},
        {"start": 5, "end": 6},
    ]
    audio = np.arange(8, dtype=np.int16)
    assert await local_stt.transcribe_buffer(audio.tobytes()) == "Привет"
    np.testing.assert_allclose(
        local_stt._model.transcribe.call_args.args[0], audio / 32768.0
    )


@pytest.mark.asyncio
async def test_decode_timing_includes_lazy_whisper_inference(local_stt, mocker, caplog):
    caplog.set_level("INFO", logger="clawsona.timing")
    clock = SimpleNamespace(now=10.0)
    mocker.patch("clawsona.timing.time.perf_counter", side_effect=lambda: clock.now)

    def detect_language(**kwargs):
        clock.now += 0.4
        return "ru", 0.98, [("ru", 0.98), ("en", 0.02)]

    def segments():
        clock.now += 0.25
        yield segment()

    local_stt._model.transcribe.return_value = (segments(), None)
    local_stt._model.detect_language.side_effect = detect_language
    with trace_turn() as turn:
        assert (
            await local_stt.transcribe_buffer(np.zeros(16000, dtype=np.int16).tobytes())
            == "Привет"
        )
    events = [r.timing for r in caplog.records if hasattr(r, "timing")]
    decode = next(e for e in events if e["stage"] == "stt_decode")
    assert decode["duration_ms"] == 250
    assert decode["turn"] == turn.id
    assert next(e for e in events if e["stage"] == "stt_language")["duration_ms"] == 400
    assert next(e for e in events if e["stage"] == "stt")["duration_ms"] == 650


@pytest.mark.asyncio
async def test_piper_streams_pcm_to_configured_device(tmp_path, mocker):
    path = tmp_path / "voice.onnx"
    path.write_bytes(b"placeholder")
    path.with_suffix(".onnx.json").write_text("{}")
    voice_class = mocker.patch("piper.PiperVoice")
    voice = voice_class.load.return_value
    voice.config.sample_rate = 22050
    voice.synthesize.return_value = iter(
        [
            SimpleNamespace(
                audio_int16_bytes=np.array([100, -100], dtype=np.int16).tobytes()
            )
        ]
    )
    stream_class = mocker.patch("clawsona.local_speech.sd.OutputStream")
    tts = PiperTTS(path, device=3)
    await tts.speak("Привет")
    stream_class.assert_called_once_with(
        samplerate=22050, channels=1, dtype="int16", device=3
    )
    stream_class.return_value.__enter__.return_value.write.assert_called_once()


@pytest.mark.asyncio
async def test_piper_reports_compute_separately_from_audio_wait(
    tmp_path, mocker, caplog
):
    caplog.set_level("INFO", logger="clawsona.timing")
    path = tmp_path / "voice.onnx"
    path.write_bytes(b"placeholder")
    path.with_suffix(".onnx.json").write_text("{}")
    voice = mocker.patch("piper.PiperVoice").load.return_value
    voice.config.sample_rate = 16000
    clock = SimpleNamespace(now=0.0)
    mocker.patch("clawsona.timing.time.perf_counter", side_effect=lambda: clock.now)

    def synthesize(text):
        clock.now += 0.2
        yield SimpleNamespace(
            audio_int16_bytes=np.zeros(16000, dtype=np.int16).tobytes()
        )

    def advance(seconds):
        clock.now += seconds

    voice.synthesize.side_effect = synthesize
    stream = mocker.patch("clawsona.local_speech.sd.OutputStream").return_value
    stream.__enter__.return_value.write.side_effect = lambda pcm: advance(1.0)
    stream.__exit__.side_effect = lambda *args: advance(0.05)
    tts = PiperTTS(path)
    await tts.speak("Привет")
    result = next(
        r.timing
        for r in caplog.records
        if hasattr(r, "timing") and r.timing["stage"] == "piper"
    )
    assert result["duration_ms"] == 1250
    assert result["synthesis_ms"] == 200
    assert result["output_write_ms"] == 1000
    assert result["output_drain_ms"] == 50
    assert result["audio_ms"] == 1000


@pytest.mark.asyncio
async def test_wav_export_never_opens_speakers(tmp_path, mocker):
    path = tmp_path / "voice.onnx"
    path.write_bytes(b"placeholder")
    path.with_suffix(".onnx.json").write_text("{}")
    voice = mocker.patch("piper.PiperVoice").load.return_value

    def synthesize_wav(text, wav):
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(np.zeros(1600, dtype=np.int16).tobytes())

    voice.synthesize_wav.side_effect = synthesize_wav
    stream = mocker.patch("clawsona.local_speech.sd.OutputStream")
    destination = tmp_path / "previews/example.wav"
    await PiperTTS(path).save_wav("Привет", destination)
    assert destination.read_bytes().startswith(b"RIFF")
    stream.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_piper_joins_its_output_worker_before_returning(
    tmp_path, mocker
):
    path = tmp_path / "voice.onnx"
    path.write_bytes(b"placeholder")
    path.with_suffix(".onnx.json").write_text("{}")
    mocker.patch("piper.PiperVoice")
    tts = PiperTTS(path)
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def output(text):
        loop.call_soon_threadsafe(started.set)
        release.wait(3)
        finished.set()

    mocker.patch.object(tts, "_speak", side_effect=output)
    task = asyncio.create_task(tts.speak("Старый ответ"))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        assert tts._cancelled.is_set() and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


def test_missing_local_models_have_actionable_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match="clawsona setup"):
        LocalSTT(tmp_path)
    with pytest.raises(FileNotFoundError, match="clawsona setup"):
        PiperTTS(tmp_path / "missing.onnx")


def test_installed_audio_decoder_is_compatible_with_whisper():
    import io
    import wave

    from faster_whisper.audio import decode_audio

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(np.zeros(1600, dtype=np.int16).tobytes())
    output.seek(0)
    decoded = decode_audio(output, sampling_rate=16000)
    assert decoded.shape == (1600,)
    assert decoded.dtype == np.float32
