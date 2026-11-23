import asyncio
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from clawsona.languages import speech_parts
from clawsona.multilingual_tts import MultilingualPiperTTS


@pytest.mark.parametrize(
    "text,languages",
    [
        ("", []),
        ("Привет, как дела?", ["ru"]),
        ("Hello, how are you?", ["en"]),
        ('Скажи "Hello, I am fine!" и переведи.', ["ru", "en", "ru"]),
        ("Let's talk about café.", ["en"]),
        ("У меня 42 яблока.", ["ru"]),
    ],
)
def test_language_spans_preserve_every_word_and_punctuation(text, languages):
    parts = speech_parts(text)
    assert [p[0] for p in parts] == languages
    assert "".join(p[1] for p in parts) == text


@pytest.mark.asyncio
async def test_mixed_sentence_uses_correct_voices_and_reuses_loaded_english(mocker):
    russian = MagicMock(speak=AsyncMock())
    english = MagicMock(speak=AsyncMock())
    factory = mocker.patch(
        "clawsona.multilingual_tts.PiperTTS", side_effect=[russian, english]
    )
    tts = MultilingualPiperTTS(Path("ru.onnx"), Path("en.onnx"), device=2)
    assert factory.call_count == 1
    await tts.speak("Привет! How are you? Хорошо.")
    assert [c.args[0] for c in russian.speak.await_args_list] == ["Привет!", "Хорошо."]
    english.speak.assert_awaited_once_with("How are you?")
    await tts.speak("Let's continue.")
    assert factory.call_count == 2
    assert factory.call_args.kwargs["device"] == 2
    assert speech_parts("42.", default="en") == [("en", "42.")]


@pytest.mark.asyncio
async def test_cancellation_stops_both_loaded_voices(mocker):
    russian = MagicMock(speak=AsyncMock(side_effect=asyncio.CancelledError()))
    english = MagicMock(speak=AsyncMock())
    mocker.patch("clawsona.multilingual_tts.PiperTTS", side_effect=[russian, english])
    tts = MultilingualPiperTTS(Path("ru.onnx"), Path("en.onnx"))
    await tts._voice("en")
    with pytest.raises(asyncio.CancelledError):
        await tts.speak("Привет. Hello.")
    russian.stop.assert_called_once()
    english.stop.assert_called_once()
    english.speak.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_wav_export_handles_different_voice_sample_rates(tmp_path, mocker):
    class Voice:
        def __init__(self, rate, value):
            self.config = SimpleNamespace(sample_rate=rate)
            self.value = value

        def synthesize_wav(self, text, output):
            output.setframerate(self.config.sample_rate)
            output.setnchannels(1)
            output.setsampwidth(2)
            output.writeframes(
                np.full(
                    self.config.sample_rate // 10, self.value, dtype=np.int16
                ).tobytes()
            )

    ru = SimpleNamespace(_voice=Voice(16000, 5000))
    en = SimpleNamespace(_voice=Voice(22050, -5000))
    mocker.patch("clawsona.multilingual_tts.PiperTTS", side_effect=[ru, en])
    speaker = mocker.patch("clawsona.local_speech.sd.OutputStream")
    tts = MultilingualPiperTTS(Path("ru.onnx"), Path("en.onnx"))
    path = tmp_path / "mixed.wav"
    await tts.save_wav("Привет. Hello.", path)
    with wave.open(str(path)) as wav:
        assert wav.getframerate() == 16000
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    assert np.mean(pcm[:1000]) > 4000
    assert np.mean(pcm[-1000:]) < -4000
    speaker.assert_not_called()
