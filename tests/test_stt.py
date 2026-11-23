from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip(
    "deepgram", reason="Install the cloud-speech extra to test Deepgram"
)


@pytest.mark.asyncio
async def test_transcribe_buffer_returns_transcript(mocker):
    mock_response = MagicMock()
    mock_response.results.channels[0].alternatives[0].transcript = "привет мир"

    mock_media = MagicMock()
    mock_media.transcribe_file = AsyncMock(return_value=mock_response)

    mock_client = MagicMock()
    mock_client.listen.v1.media = mock_media

    mocker.patch("clawsona.stt.AsyncDeepgramClient", return_value=mock_client)

    from clawsona.stt import DeepgramSTT

    stt = DeepgramSTT(api_key="test-key")
    result = await stt.transcribe_buffer(b"\x00" * 3200)

    assert result == "привет мир"
    mock_media.transcribe_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_transcribe_buffer_returns_empty_on_no_speech(mocker):
    mock_response = MagicMock()
    mock_response.results.channels[0].alternatives[0].transcript = ""

    mock_media = MagicMock()
    mock_media.transcribe_file = AsyncMock(return_value=mock_response)

    mock_client = MagicMock()
    mock_client.listen.v1.media = mock_media

    mocker.patch("clawsona.stt.AsyncDeepgramClient", return_value=mock_client)

    from clawsona.stt import DeepgramSTT

    stt = DeepgramSTT(api_key="test-key")
    result = await stt.transcribe_buffer(b"\x00" * 3200)

    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_buffer_uses_russian_nova3(mocker):
    mock_response = MagicMock()
    mock_response.results.channels[0].alternatives[0].transcript = "тест"

    mock_media = MagicMock()
    mock_media.transcribe_file = AsyncMock(return_value=mock_response)

    mock_client = MagicMock()
    mock_client.listen.v1.media = mock_media

    mocker.patch("clawsona.stt.AsyncDeepgramClient", return_value=mock_client)
    mock_options = mocker.patch("clawsona.stt.PrerecordedOptions")

    from clawsona.stt import DeepgramSTT

    stt = DeepgramSTT(api_key="test-key")
    await stt.transcribe_buffer(b"\x00" * 3200)

    mock_options.assert_called_once()
    call_kwargs = mock_options.call_args.kwargs
    assert call_kwargs["language"] == "ru"
    assert call_kwargs["model"] == "nova-3"
