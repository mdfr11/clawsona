"""Correlated local diagnostics; transcript events are separate from timings."""

import asyncio
import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TurnTiming:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    started: float = field(default_factory=lambda: time.perf_counter())
    capture_completed: float | None = None
    first_audio: float | None = None
    result: str = "pending"


_turn: ContextVar[TurnTiming | None] = ContextVar("clawsona_turn", default=None)
_fields: ContextVar[dict] = ContextVar("clawsona_timing_fields", default={})


@contextmanager
def timing_context(**fields):
    token = _fields.set(_fields.get() | fields)
    try:
        yield
    finally:
        _fields.reset(token)


def format_duration(seconds: float) -> str:
    def number(value, precision):
        return f"{value:.{precision}f}".rstrip("0").rstrip(".").replace(".", ",")

    if seconds >= 60:
        minutes, rest = divmod(round(seconds, 1), 60)
        return f"{int(minutes)} мин {number(rest, 1)} с"
    if seconds >= 1:
        return f"{number(seconds, 2)} с"
    if 0 < seconds < 0.001:
        return f"{number(seconds * 1_000_000, 1)} мкс"
    return f"{number(seconds * 1000, 2)} мс"


def log_timing(stage: str, seconds: float, *, status="ok", **fields) -> None:
    turn = _turn.get()
    data = {
        "turn": turn.id if turn else "-",
        "stage": stage,
        "duration_ms": round(seconds * 1000, 3),
        "status": status,
        **_fields.get(),
        **fields,
    }
    # Keep numeric measurements on the log record for analysis; render all
    # durations with units in the console and rotating text file.
    display = {
        key.removesuffix("_ms")
        if key.endswith("_ms") and isinstance(value, (int, float))
        else key: format_duration(value / 1000)
        if key.endswith("_ms") and isinstance(value, (int, float))
        else value
        for key, value in data.items()
    }
    logger.info(
        "TIMING %s", json.dumps(display, ensure_ascii=False), extra={"timing": data}
    )


def log_dialogue(event: str, **fields) -> None:
    turn = _turn.get()
    data = {"turn": turn.id if turn else "-", **fields}
    logger.info(
        "%s %s",
        event,
        json.dumps(data, ensure_ascii=False),
        extra={"dialogue": {"event": event, **data}},
    )


@contextmanager
def stage_timer(stage: str, **fields):
    started = time.perf_counter()
    status = "ok"
    try:
        yield fields
    except BaseException as exc:
        status = (
            "cancelled"
            if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
            else "error"
        )
        raise
    finally:
        log_timing(stage, time.perf_counter() - started, status=status, **fields)


@contextmanager
def trace_turn():
    turn = TurnTiming()
    token = _turn.set(turn)
    status = "ok"
    try:
        yield turn
    except BaseException as exc:
        status = (
            "cancelled"
            if isinstance(exc, (asyncio.CancelledError, GeneratorExit))
            else "error"
        )
        raise
    finally:
        now = time.perf_counter()
        fields = {"result": turn.result}
        if turn.capture_completed is not None:
            fields["after_capture_ms"] = round((now - turn.capture_completed) * 1000, 3)
        if status == "ok" and turn.result == "error":
            status = "error"
        log_timing("turn_total", now - turn.started, status=status, **fields)
        _turn.reset(token)


def mark_capture_complete() -> None:
    if turn := _turn.get():
        turn.capture_completed = time.perf_counter()


def mark_first_audio() -> None:
    """First PCM handed to the output device; this excludes hardware latency."""
    turn = _turn.get()
    if turn is None or turn.first_audio is not None:
        return
    turn.first_audio = time.perf_counter()
    if turn.capture_completed is not None:
        log_timing("capture_to_first_audio", turn.first_audio - turn.capture_completed)
