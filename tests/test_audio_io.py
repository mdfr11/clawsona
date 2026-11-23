import asyncio
from unittest.mock import MagicMock

import numpy as np
import pytest


def test_audio_capture_start_opens_stream(mocker):
    mock_stream = MagicMock()
    mock_input_stream = mocker.patch(
        "sounddevice.InputStream", return_value=mock_stream
    )

    from clawsona.audio_io import AudioCapture

    cap = AudioCapture(sample_rate=16000, chunk_size=1024)
    cap.start()

    mock_input_stream.assert_called_once_with(
        samplerate=16000,
        channels=1,
        dtype="int16",
        blocksize=1024,
        callback=cap._sd_callback,
    )
    mock_stream.start.assert_called_once()
    cap.stop()


def test_audio_capture_stop_closes_stream(mocker):
    mock_stream = MagicMock()
    mocker.patch("sounddevice.InputStream", return_value=mock_stream)

    from clawsona.audio_io import AudioCapture

    cap = AudioCapture()
    cap.start()
    cap.stop()

    mock_stream.stop.assert_called_once()
    mock_stream.close.assert_called_once()


def test_audio_capture_callback_puts_to_queue(mocker):
    mocker.patch("sounddevice.InputStream")

    from clawsona.audio_io import AudioCapture

    cap = AudioCapture()
    chunk = np.zeros((1024, 1), dtype=np.int16)
    cap._sd_callback(chunk, 1024, None, None)

    result = cap._q.get_nowait()
    assert result.shape == chunk.shape


@pytest.mark.asyncio
async def test_read_async_returns_chunk(mocker):
    mocker.patch("sounddevice.InputStream")

    from clawsona.audio_io import AudioCapture

    cap = AudioCapture()
    chunk = np.zeros((1024, 1), dtype=np.int16)
    cap._q.put(chunk)

    result = await cap.read_async()
    np.testing.assert_array_equal(result, chunk)


def test_play_sync_calls_sounddevice(mocker):
    mock_play = mocker.patch("sounddevice.play")
    mock_wait = mocker.patch("sounddevice.wait")

    from clawsona.audio_io import _play_sync

    audio = np.zeros(1000, dtype=np.int16).tobytes()
    _play_sync(audio, sample_rate=44100)

    mock_play.assert_called_once()
    mock_wait.assert_called_once()


def test_capture_does_not_reuse_previous_session(mocker):
    mocker.patch("sounddevice.InputStream")
    from clawsona.audio_io import AudioCapture

    cap = AudioCapture()
    cap.start()
    cap._sd_callback(np.ones((480, 1), dtype=np.int16), 480, None, None)
    cap.stop()
    cap.start()
    assert cap._q.empty()
    cap.stop()


def test_callback_queue_is_bounded_and_keeps_newest():
    from clawsona.audio_io import AudioCapture

    cap = AudioCapture()
    for number in range(200):
        cap._sd_callback(np.full((480, 1), number, dtype=np.int16), 480, None, None)
    assert cap._q.qsize() == cap._q.maxsize
    latest = None
    while not cap._q.empty():
        latest = cap._q.get_nowait()
    assert latest[0, 0] == 199


@pytest.mark.asyncio
async def test_waiting_for_audio_is_cancellable():
    from clawsona.audio_io import AudioCapture

    cap = AudioCapture()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(cap.read_async(), timeout=0.02)


@pytest.mark.asyncio
async def test_callback_from_audio_thread_wakes_reader():
    import threading

    from clawsona.audio_io import AudioCapture

    cap = AudioCapture()
    task = asyncio.create_task(cap.read_async())
    await asyncio.sleep(0)
    chunk = np.full((480, 1), 42, dtype=np.int16)
    thread = threading.Thread(target=cap._sd_callback, args=(chunk, 480, None, None))
    thread.start()
    result = await asyncio.wait_for(task, 0.5)
    thread.join()
    np.testing.assert_array_equal(result, chunk)


@pytest.mark.asyncio
async def test_cancelled_reader_does_not_steal_next_recording():
    from clawsona.audio_io import AudioCapture

    cap = AudioCapture()
    task = asyncio.create_task(cap.read_async())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cap._sd_callback(np.full((480, 1), 7, dtype=np.int16), 480, None, None)
    result = await asyncio.wait_for(cap.read_async(), 0.5)
    assert result[0, 0] == 7
