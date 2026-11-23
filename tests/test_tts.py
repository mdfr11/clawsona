from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip(
    "edge_tts", reason="Install the cloud-speech extra to test edge-tts"
)
pytest.importorskip("pydub")


@pytest.mark.asyncio
async def test_synthesize_mp3_returns_bytes(mocker):
    mock_communicate = MagicMock()
    fake_audio = b"fake-audio-data-12345"

    async def fake_stream():
        yield {"type": "audio", "data": fake_audio[:10]}
        yield {"type": "audio", "data": fake_audio[10:]}
        yield {"type": "WordBoundary", "data": b""}

    mock_communicate.stream = fake_stream
    mocker.patch("edge_tts.Communicate", return_value=mock_communicate)

    from clawsona.tts import TTSClient

    client = TTSClient(voice="ru-RU-DmitryNeural")
    result = await client.synthesize_mp3("Привет")

    assert result == fake_audio


@pytest.mark.asyncio
async def test_speak_calls_play_audio(mocker):
    mock_communicate = MagicMock()

    async def fake_stream():
        yield {"type": "audio", "data": b"\x00" * 100}

    mock_communicate.stream = fake_stream
    mocker.patch("edge_tts.Communicate", return_value=mock_communicate)

    mock_segment = MagicMock()
    mock_segment.set_frame_rate.return_value = mock_segment
    mock_segment.set_channels.return_value = mock_segment
    mock_segment.set_sample_width.return_value = mock_segment
    mock_segment.get_array_of_samples.return_value = [0] * 100
    mocker.patch("pydub.AudioSegment.from_mp3", return_value=mock_segment)

    mock_play = mocker.patch("clawsona.tts.play_audio_async", new_callable=AsyncMock)

    from clawsona.tts import TTSClient

    client = TTSClient(voice="ru-RU-DmitryNeural")
    await client.speak("Привет")

    mock_play.assert_awaited_once()
    # Verify it was called with bytes and a sample_rate
    call_args = mock_play.call_args
    assert isinstance(call_args[0][0], bytes)
    assert call_args[1].get("sample_rate") == 24000 or call_args[0][1] == 24000
