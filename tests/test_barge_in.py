import asyncio
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from clawsona.barge_in import BargeInListener, addressed_interruption, is_reply_echo
from clawsona.config import Settings
from clawsona.vad import CHUNK_SIZE
from clawsona.wakeword import WakeWordDetector


@pytest.mark.parametrize(
    "heard,reply,echo",
    [
        ("Лютик, привет!", "Лютик, привет! Давай поговорим.", True),
        ("Лютик", "Я Лютик, твой помощник.", True),
        ("Лютик, другой вопрос", "Привет, я Лютик.", False),
        ("Mira, wait, another question", "Welcome back to our lesson.", False),
        ("", "Привет!", False),
    ],
)
def test_reply_echo_guard(heard, reply, echo):
    assert is_reply_echo(heard, reply) is echo


def test_only_a_known_echo_prefix_can_be_removed_before_a_direct_address():
    wake = WakeWordDetector("Лютик")
    assert (
        addressed_interruption(
            "Объясняю дроби. Лютик, другой вопрос", "Объясняю дроби на примерах.", wake
        )
        == "Лютик, другой вопрос"
    )
    assert (
        addressed_interruption(
            "Мы вчера видели Лютик на улице", "Объясняю дроби.", wake
        )
        is None
    )


def test_echo_guard_normalizes_configured_aliases_across_languages():
    assert is_reply_echo("Lyutik", "Я Лютик.", ["Лютик", "Lyutik"])


def listener(mocker, *, mode="name", texts=(), frames=25, events=None, **overrides):
    config = Settings(
        _env_file=None,
        assistant_name="Лютик",
        assistant_aliases=["Lyutik"],
        barge_in_mode=mode,
        **({"barge_in_check_interval_ms": 500} | overrides),
    )
    vad = mocker.patch("clawsona.barge_in.VADDetector").return_value
    events = events or {1: "speech_start", frames: "speech_end"}
    counter = 0

    async def read():
        nonlocal counter
        await asyncio.sleep(0)
        counter += 1
        if counter > frames:
            await asyncio.Event().wait()
        return np.full((CHUNK_SIZE, 1), counter, dtype=np.int16)

    vad.process_chunk.side_effect = lambda chunk: events.get(int(chunk[0, 0]))
    audio = MagicMock(read_async=read)
    stt = MagicMock(transcribe_buffer=AsyncMock(side_effect=texts))
    return BargeInListener(config, audio, stt), audio, stt


@pytest.mark.asyncio
async def test_name_confirmation_stops_early_but_keeps_full_question_and_onset(mocker):
    watch, audio, stt = listener(
        mocker, texts=["Лютик", "Лютик, объясни другой пример"]
    )
    on_interrupt = MagicMock()
    result = await asyncio.wait_for(
        watch.listen(on_interrupt, lambda: "Старый ответ"), 1
    )
    assert result == "Лютик, объясни другой пример"
    on_interrupt.assert_called_once()
    assert stt.transcribe_buffer.await_count == 2
    partial, full = [
        np.frombuffer(c.args[0], dtype=np.int16)
        for c in stt.transcribe_buffer.call_args_list
    ]
    assert partial.size < full.size
    assert full[0] == 1 and full[-1] == 25
    audio.stop.assert_called_once()


@pytest.mark.asyncio
async def test_echo_and_unaddressed_speech_cannot_interrupt(mocker):
    watch, audio, stt = listener(
        mocker,
        frames=60,
        texts=[
            "Лютик, привет",
            "фоновый разговор",
            "Lyutik, another question",
            "Lyutik, another question please",
        ],
    )
    on_interrupt = MagicMock()
    result = await asyncio.wait_for(
        watch.listen(on_interrupt, lambda: "Лютик, привет! Чем помочь?"), 1
    )
    assert result == "Lyutik, another question please"
    on_interrupt.assert_called_once()
    assert stt.transcribe_buffer.await_count == 4


@pytest.mark.asyncio
async def test_headphone_mode_interrupts_on_vad_and_transcribes_once(mocker):
    watch, audio, stt = listener(mocker, mode="speech", texts=["Another question"])
    on_interrupt = MagicMock()
    assert (
        await asyncio.wait_for(watch.listen(on_interrupt, lambda: "Old answer"), 1)
        == "Another question"
    )
    on_interrupt.assert_called_once()
    stt.transcribe_buffer.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_stops_capture_and_pending_recognition(mocker):
    watch, audio, stt = listener(mocker, frames=1000)
    started, closed = asyncio.Event(), asyncio.Event()

    async def blocked(data):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    stt.transcribe_buffer.side_effect = blocked
    task = asyncio.create_task(watch.listen(MagicMock(), lambda: "Old answer"))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    audio.stop.assert_called_once()


@pytest.mark.asyncio
async def test_maximum_recording_length_is_respected(mocker):
    watch, audio, stt = listener(
        mocker,
        mode="speech",
        texts=["Full phrase"],
        frames=1000,
        max_utterance_s=1,
        events={1: "speech_start"},
    )
    await asyncio.wait_for(watch.listen(MagicMock(), lambda: "Old answer"), 1)
    assert len(stt.transcribe_buffer.call_args.args[0]) <= 16000 * 2


@pytest.mark.asyncio
async def test_rejected_final_recognition_does_not_forward_a_partial_question(mocker):
    watch, audio, stt = listener(mocker, texts=["Лютик, объясни", ""])
    assert (
        await asyncio.wait_for(watch.listen(MagicMock(), lambda: "Old answer"), 1)
        == "Лютик"
    )


@pytest.mark.asyncio
async def test_name_checks_work_when_max_utterance_is_shorter_than_check_interval(
    mocker,
):
    watch, audio, stt = listener(
        mocker,
        texts=["Лютик", "Лютик, другой вопрос"],
        frames=1000,
        events={1: "speech_start"},
        max_utterance_s=1,
        barge_in_check_interval_ms=3000,
    )
    on_interrupt = MagicMock()
    result = await asyncio.wait_for(
        watch.listen(on_interrupt, lambda: "Старый ответ"), 1
    )
    assert result == "Лютик, другой вопрос"
    on_interrupt.assert_called_once()
    assert len(stt.transcribe_buffer.call_args.args[0]) <= 16000 * 2


@pytest.mark.asyncio
async def test_name_spoken_during_slow_check_is_not_lost_in_a_cadence_gap(mocker):
    watch, audio, stt = listener(mocker, frames=70)
    original_read = audio.read_async
    latest, calls = 0, 0

    async def read():
        nonlocal latest
        chunk = await original_read()
        latest = int(chunk[0, 0])
        return chunk

    async def recognize(data):
        nonlocal calls
        calls += 1
        if calls == 1:
            while latest < 35:
                await asyncio.sleep(0)
            return "фоновая речь"
        if calls == 2:
            # Marker 20 represents the short name spoken during the first check.
            if 20 in np.frombuffer(data, dtype=np.int16):
                return "Лютик, другой вопрос"
            return "другой вопрос"
        return "Лютик, другой вопрос целиком"

    audio.read_async = read
    stt.transcribe_buffer.side_effect = recognize
    on_interrupt = MagicMock()
    result = await asyncio.wait_for(
        watch.listen(on_interrupt, lambda: "Старый ответ"), 1
    )
    assert result == "Лютик, другой вопрос целиком"
    on_interrupt.assert_called_once()
