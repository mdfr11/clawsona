import asyncio
import json
import logging

import pytest

from clawsona.timing import (
    format_duration,
    log_timing,
    mark_capture_complete,
    mark_first_audio,
    stage_timer,
    trace_turn,
)


def timings(caplog):
    return [record.timing for record in caplog.records if hasattr(record, "timing")]


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0 мс"),
        (0.00000825, "8,2 мкс"),
        (0.125, "125 мс"),
        (9.878732, "9,88 с"),
        (65.432, "1 мин 5,4 с"),
        (119.9999, "2 мин 0 с"),
    ],
)
def test_duration_units_are_readable(seconds, expected):
    assert format_duration(seconds) == expected


def test_log_formats_nested_durations_but_keeps_numeric_measurements(caplog):
    caplog.set_level(logging.INFO, logger="clawsona.timing")
    log_timing("llm", 9.878732, provider_wait_ms=9750, chars=120)
    record = caplog.records[-1]
    display = json.loads(record.getMessage().removeprefix("TIMING "))
    assert display["duration"] == "9,88 с"
    assert display["provider_wait"] == "9,75 с"
    assert display["chars"] == 120
    assert "9878.732" not in record.getMessage()
    assert record.timing["duration_ms"] == 9878.732


@pytest.mark.parametrize(
    "error,status",
    [
        (RuntimeError("failed"), "error"),
        (asyncio.CancelledError(), "cancelled"),
    ],
)
def test_failed_stages_keep_elapsed_time(caplog, mocker, error, status):
    caplog.set_level(logging.INFO, logger="clawsona.timing")
    mocker.patch("clawsona.timing.time.perf_counter", side_effect=[100, 100.25])
    with pytest.raises(type(error)), stage_timer("example"):
        raise error
    event = timings(caplog)[0]
    assert event["status"] == status
    assert event["duration_ms"] == 250


@pytest.mark.asyncio
async def test_turn_correlation_survives_tasks_and_threads_and_first_audio_is_once(
    caplog,
):
    caplog.set_level(logging.INFO, logger="clawsona.timing")
    with trace_turn() as turn:
        mark_capture_complete()
        await asyncio.to_thread(log_timing, "stt_decode", 0.1)

        async def playback():
            await asyncio.to_thread(mark_first_audio)
            mark_first_audio()
            log_timing("tts_total", 0.2)

        await asyncio.create_task(playback())
        turn.result = "reply"
    events = timings(caplog)
    assert {e["turn"] for e in events} == {turn.id}
    assert [e["stage"] for e in events].count("capture_to_first_audio") == 1
    assert events[-1]["stage"] == "turn_total"
    assert events[-1]["after_capture_ms"] >= 0
    # Timings outside the turn must not retain the previous conversation ID.
    log_timing("startup", 0.01)
    assert timings(caplog)[-1]["turn"] == "-"
