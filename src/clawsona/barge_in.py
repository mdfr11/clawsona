"""Bounded microphone monitoring during speech, with optional name confirmation."""

import asyncio
import re
import time
from collections import deque
from difflib import SequenceMatcher

import numpy as np

from clawsona.timing import log_dialogue, log_timing, stage_timer
from clawsona.vad import CHUNK_SIZE, FRAME_MS, VADDetector
from clawsona.wakeword import WakeWordDetector


def is_reply_echo(transcript, reply, names=()):
    """Conservative text guard, not acoustic echo cancellation."""
    if names:
        pattern = (
            r"(?<!\w)(?:"
            + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
            + r")(?!\w)"
        )
        transcript = re.sub(pattern, "__assistant__", transcript, flags=re.IGNORECASE)
        reply = re.sub(pattern, "__assistant__", reply, flags=re.IGNORECASE)
    heard = re.findall(r"\w+", transcript.casefold().replace("ё", "е"))
    spoken = re.findall(r"\w+", reply.casefold().replace("ё", "е"))
    if not heard or not spoken:
        return False
    match = SequenceMatcher(None, heard, spoken, autojunk=False).find_longest_match()
    return match.size / len(heard) >= 0.8


def addressed_interruption(transcript, reply, wake, names=()):
    names = names or (wake.name,)
    if is_reply_echo(transcript, reply, names):
        return None
    if wake.extract(transcript) is not None:
        return transcript
    # A microphone may hear the tail of playback before the direct address.
    # Strip that prefix only when it matches the known answer text.
    for word in re.finditer(r"\b\w+", transcript):
        suffix = transcript[word.start() :]
        if wake.extract(suffix) is not None and is_reply_echo(
            transcript[: word.start()], reply, names
        ):
            return suffix
    return None


class BargeInListener:
    def __init__(self, config, audio, stt):
        self._config, self._audio, self._stt = config, audio, stt
        self._wake = WakeWordDetector(config.assistant_name, config.assistant_aliases)
        self._names = [config.assistant_name, *config.assistant_aliases]
        self._vad = VADDetector(
            config.vad_silence_duration_ms,
            config.barge_in_min_speech_ms,
            max(0.7, config.vad_threshold),
        )

    async def _transcribe(self, chunks, stage):
        with stage_timer(stage, provider=self._config.stt_provider):
            return (
                await self._stt.transcribe_buffer(np.concatenate(chunks).tobytes())
            ).strip()

    async def listen(self, notify, reply_text):
        """Notify promptly on confirmation; keep recording the rest of the phrase."""
        config = self._config
        maximum = int(config.max_utterance_s * config.sample_rate / CHUNK_SIZE)
        interval = min(maximum, max(1, config.barge_in_check_interval_ms // FRAME_MS))
        recent = deque(maxlen=min(maximum, max(interval * 2, 32)))
        self._vad.reset()
        check = None
        snapshot, tail, recorded = [], [], []
        confirmed = speaking = False
        frames, next_check = 0, interval
        check_started = None
        candidate = ""
        try:
            self._audio.start()
            while True:
                chunk = await asyncio.wait_for(
                    self._audio.read_async(), config.audio_read_timeout_s
                )
                event = self._vad.process_chunk(chunk)
                frames += 1
                recent.append(chunk)
                if check is not None:
                    tail.append(chunk)
                    if len(snapshot) + len(tail) >= maximum and not check.done():
                        # Never grow a recording while a slow recognizer catches up.
                        await check
                if confirmed:
                    recorded.append(chunk)
                if event == "speech_start":
                    speaking = True
                    if config.barge_in_mode == "speech" and not confirmed:
                        recorded = list(recent)
                        confirmed = True
                        notify()
                        log_timing(
                            "barge_in_detect",
                            config.barge_in_min_speech_ms / 1000,
                            mode="speech",
                            estimated=True,
                        )
                elif event == "speech_end":
                    speaking = False
                if check is not None and check.done():
                    candidate = check.result()
                    addressed = addressed_interruption(
                        candidate, reply_text(), self._wake, self._names
                    )
                    decision = (
                        "echo"
                        if is_reply_echo(candidate, reply_text(), self._names)
                        else "accepted"
                        if addressed is not None
                        else "not_addressed"
                    )
                    if config.log_transcripts:
                        log_dialogue(
                            "BARGE_IN_TRANSCRIPT", text=candidate, decision=decision
                        )
                    check = None
                    if decision == "accepted":
                        recorded = (snapshot + tail)[:maximum]
                        confirmed = True
                        notify()
                        log_timing(
                            "barge_in_confirm",
                            time.perf_counter() - check_started,
                            mode="name",
                            window_audio_ms=len(snapshot) * FRAME_MS,
                        )
                    snapshot, tail = [], []
                if confirmed and (not speaking or len(recorded) >= maximum):
                    break
                if (
                    not confirmed
                    and config.barge_in_mode == "name"
                    and check is None
                    and len(recent) >= interval
                    and (speaking and frames >= next_check or event == "speech_end")
                ):
                    snapshot, tail = list(recent), []
                    check_started = time.perf_counter()
                    # Count recognition time toward the cadence. Adding another
                    # whole interval afterwards creates gaps in rolling windows
                    # and can lose a name spoken while Whisper was busy.
                    next_check = frames + interval
                    check = asyncio.create_task(
                        self._transcribe(snapshot, "barge_in_check")
                    )
        finally:
            self._audio.stop()
            if check is not None:
                check.cancel()
                await asyncio.gather(check, return_exceptions=True)
        # Full endpointing remains the usual conversation silence setting. A
        # partial name check must never become a truncated question to the model.
        text = await self._transcribe(recorded, "barge_in_stt")
        if config.barge_in_mode == "name" and text:
            text = (
                addressed_interruption(text, reply_text(), self._wake, self._names)
                or text
            )
        return text or (config.assistant_name if candidate else "")
