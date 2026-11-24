import asyncio
import enum
import logging
import re
import time
from collections import deque
from contextlib import AsyncExitStack, aclosing, nullcontext

import numpy as np

from clawsona.music_commands import music_reply, parse_music_command
from clawsona.prompts import VOICE_INPUT_INSTRUCTIONS, build_system_prompt
from clawsona.timing import (
    log_dialogue,
    log_timing,
    mark_capture_complete,
    stage_timer,
    trace_turn,
)
from clawsona.vad import CHUNK_SIZE, FRAME_MS

logger = logging.getLogger(__name__)
STOP_PHRASES = {
    "стоп",
    "хватит",
    "спасибо пока",
    "до свидания",
    "пока",
    "bye",
    "goodbye",
    "see you",
}
RESET_PHRASES = {"новый разговор", "забудь разговор", "начнём заново", "начнем заново"}


class State(enum.Enum):
    IDLE = "IDLE"
    WAKE = "WAKE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"


class Orchestrator:
    def __init__(self, config, audio, wakeword, vad, stt, chat, tts, *, music=None):
        self._config = config
        self._audio = audio
        self._wakeword = wakeword
        self._vad = vad
        self._stt = stt
        self._chat = chat
        self._tts = tts
        self._music = music
        self._state = State.IDLE
        self._conversation_history: list[dict] = []
        self._pending_transcript = None
        self._interrupted_reply = False
        self._interruption_context = False
        self._barge_listener = None

    def _transition(self, new_state: State) -> None:
        logger.debug("State: %s → %s", self._state.value, new_state.value)
        self._state = new_state

    def reset_conversation(self) -> None:
        self._conversation_history.clear()
        self._interruption_context = False
        if self._config.llm_provider == "openclaw":
            self._chat.reset_session()

    @staticmethod
    def command(text: str) -> str | None:
        normalized = re.sub(r"[^\w\s]", "", text.lower()).strip()
        normalized = " ".join(normalized.split())
        if normalized in STOP_PHRASES:
            return "stop"
        if normalized in RESET_PHRASES:
            return "reset"
        return None

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        active_until = 0.0
        continuous = self._config.activation == "continuous"
        try:
            while True:
                active = continuous or loop.time() < active_until
                self._transition(State.LISTENING if active else State.IDLE)
                with trace_turn() as turn:
                    try:
                        active_until = await self._handle_turn(
                            active, active_until, continuous, turn
                        )
                    except Exception:
                        turn.result = "error"
                        logger.exception("Ошибка реплики; возвращаюсь к ожиданию")
                        try:
                            await self._speak(
                                "Не получилось ответить. Попробуй ещё раз."
                            )
                        except Exception:
                            logger.warning("Не удалось озвучить сообщение об ошибке")
                        active_until = 0.0
                        await asyncio.sleep(self._config.error_retry_delay_s)
        finally:
            self._audio.stop()
            stop_tts = getattr(self._tts, "stop", None)
            if stop_tts:
                stop_tts()

    async def _handle_turn(self, active, active_until, continuous, turn) -> float:
        loop = asyncio.get_running_loop()
        self._interrupted_reply = False
        timeout = self._config.conversation_timeout_s
        if active and not continuous:
            timeout = max(0.001, active_until - loop.time())
        if self._pending_transcript is not None:
            transcript, self._pending_transcript = self._pending_transcript, None
            active = True  # The interruption has already passed activation.
        else:
            transcript = await self._listen_and_transcribe(timeout_s=timeout)
        if transcript is None:
            if active and not continuous:
                logger.info(
                    "Пауза диалога превысила %g с; снова жду обращение по имени",
                    self._config.conversation_timeout_s,
                )
            turn.result = "timeout"
            return 0.0
        if not transcript:
            # Rejected noise must neither invoke the model nor extend a window.
            turn.result = "rejected_audio"
            if self._config.log_transcripts:
                candidate = getattr(self._stt, "last_transcript", "")
                reason = getattr(self._stt, "last_rejection_reason", None)
                log_dialogue(
                    "TRANSCRIPT",
                    text=candidate if isinstance(candidate, str) else "",
                    decision="rejected",
                    reason=reason if isinstance(reason, str) else "empty_transcript",
                )
            return active_until
        with stage_timer("activation") as metrics:
            addressed = self._wakeword.extract(transcript) if self._wakeword else None
            metrics["result"] = (
                "addressed"
                if addressed is not None
                else "follow_up"
                if active
                else "ignored"
            )
        if self._config.log_transcripts:
            log_dialogue("TRANSCRIPT", text=transcript, decision=metrics["result"])
        if not active and addressed is None:
            turn.result = "not_addressed"
            return active_until
        name_only = addressed == ""
        if addressed is not None:
            self._transition(State.WAKE)
            logger.info("Распознано обращение по имени")
            transcript = addressed or self._config.wake_word
        control = parse_music_command(transcript) if self._music is not None else None
        if control is not None and not (
            self._music.has_playback_context
            or re.search(
                r"\b(?:музык\w*|трек\w*|песн\w*|music|song|track)\b",
                transcript.casefold(),
            )
        ):
            # An enabled integration alone must not turn a lesson's "continue"
            # or "next" into a music action when no track has been selected.
            control = None
        if control is not None:
            await self._control_music(control, transcript)
            turn.result = "music_control"
            return (
                loop.time() + self._config.conversation_timeout_s
                if self._config.follow_up_without_name or self._interrupted_reply
                else 0.0
            )
        command = self.command(transcript)
        if self._config.llm_provider == "openclaw" and transcript.lower().strip(
            " .!?"
        ) in {"стоп", "хватит"}:
            command = None
        if command == "stop":
            await self._speak(
                "See you." if re.search(r"[A-Za-z]", transcript) else "До встречи."
            )
            turn.result = "stop"
            return 0.0
        if command == "reset":
            self.reset_conversation()
            await self._think_and_speak("Давай начнём новый разговор.")
            turn.result = "reset"
            return loop.time() + self._config.conversation_timeout_s
        await self._think_and_speak(transcript)
        turn.result = "interrupted" if self._interrupted_reply else "reply"
        return (
            loop.time() + self._config.conversation_timeout_s
            if name_only
            or self._config.follow_up_without_name
            or self._interrupted_reply
            else 0.0
        )

    async def _speak(self, text, *, interruptible=True):
        async def speak():
            async with self._pause_music():
                with stage_timer(
                    "tts_total", provider=self._config.tts_provider, chars=len(text)
                ):
                    await self._tts.speak(text)

        if interruptible:
            await self._with_barge_in(speak, lambda: text)
        else:
            await speak()

    async def _with_barge_in(self, deliver, reply_text, speaking=None):
        if not self._config.barge_in_enabled or self._audio is None:
            await deliver()
            return False
        if self._barge_listener is None:
            from clawsona.barge_in import BargeInListener

            try:
                self._barge_listener = BargeInListener(
                    self._config, self._audio, self._stt
                )
            except Exception:
                logger.warning(
                    "Не удалось включить прерывание голосом для этого ответа"
                )
                await deliver()
                return False
        interrupted = asyncio.Event()

        async def listen():
            if speaking is not None:
                await speaking.wait()
            return await self._barge_listener.listen(interrupted.set, reply_text)

        reply = asyncio.create_task(deliver())
        listener = asyncio.create_task(listen())
        signal = asyncio.create_task(interrupted.wait())
        try:
            done, _ = await asyncio.wait(
                {reply, listener, signal}, return_when=asyncio.FIRST_COMPLETED
            )
            if interrupted.is_set():
                self._interrupted_reply = self._interruption_context = True
                logger.info("Ответ прерван пользователем; дослушиваю новую реплику")
                async with self._pause_music():
                    with stage_timer("barge_in_stop"):
                        reply.cancel()
                        await asyncio.gather(reply, return_exceptions=True)
                    self._transition(State.LISTENING)
                    try:
                        transcript = await listener
                    except Exception:
                        logger.warning(
                            "Не удалось распознать прерывание; жду следующую реплику"
                        )
                        transcript = ""
                if transcript:
                    from clawsona.barge_in import is_reply_echo
                    from clawsona.wakeword import WakeWordDetector

                    wake = WakeWordDetector(
                        self._config.assistant_name, self._config.assistant_aliases
                    )
                    addressed = wake.extract(transcript)
                    command = re.sub(
                        r"[^\w\s]",
                        "",
                        (addressed if addressed is not None else transcript).casefold(),
                    ).strip()
                    # Saying only the name or asking for silence just opens the
                    # listening window; it must not pause music or trigger an ack.
                    silence = {
                        "",
                        "стоп",
                        "хватит",
                        "замолчи",
                        "подожди",
                        "помолчи",
                        "stop",
                        "wait",
                        "be quiet",
                        "quiet",
                    }
                    if command not in silence and (
                        self._config.barge_in_mode == "speech"
                        or not is_reply_echo(
                            transcript,
                            reply_text(),
                            [
                                self._config.assistant_name,
                                *self._config.assistant_aliases,
                            ],
                        )
                    ):
                        self._pending_transcript = transcript
                    if self._config.log_transcripts:
                        log_dialogue("BARGE_IN_INPUT", text=transcript)
                return True
            if listener in done:
                # A broken monitoring microphone must not discard a valid reply.
                try:
                    listener.result()
                except Exception:
                    logger.warning("Прерывание голосом недоступно для этого ответа")
            await reply
            return False
        finally:
            for task in (reply, listener, signal):
                if not task.done():
                    task.cancel()
            await asyncio.gather(reply, listener, signal, return_exceptions=True)

    async def _control_music(self, command, transcript):
        from clawsona.music import MusicControlError
        from clawsona.music_playback import PlaybackError

        english = bool(re.search(r"[a-zA-Z]", transcript))
        previous_reply = next(
            (
                message["content"]
                for message in reversed(self._conversation_history)
                if message["role"] == "assistant"
            ),
            "",
        )
        if re.search(r"[a-zA-Z]", previous_reply) and not re.search(
            r"[а-яА-ЯёЁ]", previous_reply
        ):
            english = True
        async with self._pause_music():
            try:
                with stage_timer("music_control", action=command.action):
                    async with asyncio.timeout(40):
                        result = await self._music.command(
                            command.action, **command.options()
                        )
                reply = music_reply(command, result, english=english)
            except (MusicControlError, PlaybackError, TimeoutError) as exc:
                if english:
                    reply = "I couldn't complete the music command. Please try again."
                else:
                    reply = (
                        str(exc)
                        or "Музыкальная команда не завершилась вовремя. Попробуй ещё раз."
                    )
            await self._speak(reply)

    def _pause_music(self):
        if self._music is not None and self._config.music_pause_during_speech:
            return self._music.pause_for_speech()
        return nullcontext()

    async def _listen_and_transcribe(
        self, timeout_s: float | None = None
    ) -> str | None:
        self._transition(State.LISTENING)
        self._vad.reset()
        pre_roll_ms = max(
            self._config.vad_pre_roll_ms, self._config.vad_min_speech_ms + 4 * FRAME_MS
        )
        pre_roll = deque(maxlen=(pre_roll_ms + FRAME_MS - 1) // FRAME_MS)
        chunks = []
        speech_started = False
        speech_started_at = None
        capture_started = time.perf_counter()
        vad_s = 0.0
        frames = 0
        end_reason = "interrupted"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + (
            self._config.conversation_timeout_s if timeout_s is None else timeout_s
        )
        recorded_samples = 0
        with stage_timer("capture_total") as metrics:
            try:
                with stage_timer("audio_open"):
                    self._audio.start()
                while True:
                    if not speech_started and loop.time() >= deadline:
                        metrics["result"] = "timeout"
                        return None
                    timeout = self._config.audio_read_timeout_s
                    if not speech_started:
                        timeout = min(timeout, max(0.001, deadline - loop.time()))
                    try:
                        chunk = await asyncio.wait_for(
                            self._audio.read_async(), timeout
                        )
                    except TimeoutError as exc:
                        if not speech_started and loop.time() >= deadline:
                            metrics["result"] = "timeout"
                            return None
                        raise RuntimeError("Микрофон перестал передавать звук") from exc
                    before = time.perf_counter()
                    event = self._vad.process_chunk(chunk)
                    vad_s += time.perf_counter() - before
                    frames += 1
                    if not speech_started:
                        pre_roll.append(chunk)
                        if event != "speech_start":
                            continue
                        speech_started = True
                        speech_started_at = time.perf_counter()
                        chunks.extend(pre_roll)
                        recorded_samples = len(pre_roll) * CHUNK_SIZE
                    else:
                        chunks.append(chunk)
                        recorded_samples += chunk.size
                    if event == "speech_end":
                        metrics["result"] = "speech"
                        end_reason = metrics["end_reason"] = "silence"
                        end_silence = getattr(self._vad, "last_end_silence_ms", None)
                        if isinstance(end_silence, (int, float)):
                            metrics["end_silence_ms"] = end_silence
                        break
                    if (
                        recorded_samples
                        >= self._config.max_utterance_s * self._config.sample_rate
                    ):
                        metrics["result"] = "max_length"
                        end_reason = metrics["end_reason"] = "max_length"
                        logger.info("Достигнута максимальная длина реплики")
                        break
            finally:
                with stage_timer("audio_close"):
                    self._audio.stop()
                finished = time.perf_counter()
                log_timing(
                    "capture_wait", (speech_started_at or finished) - capture_started
                )
                log_timing("vad_stream", vad_s, processed_audio_ms=frames * FRAME_MS)
                if speech_started_at is not None:
                    mark_capture_complete()
                    log_timing(
                        "capture_record",
                        finished - speech_started_at,
                        audio_ms=round(recorded_samples / 16, 1),
                        end_silence_config_ms=self._config.vad_silence_duration_ms,
                        preroll_config_ms=self._config.vad_pre_roll_ms,
                        end_reason=end_reason,
                        **(
                            {"end_silence_ms": metrics["end_silence_ms"]}
                            if "end_silence_ms" in metrics
                            else {}
                        ),
                    )
        if not chunks:
            return None
        self._transition(State.TRANSCRIBING)
        with stage_timer("stt_total", provider=self._config.stt_provider):
            text = await self._stt.transcribe_buffer(np.concatenate(chunks).tobytes())
        return text.strip()

    async def _model_chunks(self, messages):
        started = time.perf_counter()
        provider_wait = 0.0
        chars = 0
        first = True
        with stage_timer(
            "llm", provider=self._config.llm_provider, model=self._config.chat_model
        ) as metrics:
            async with aclosing(self._chat.chat_stream(messages)) as stream:
                try:
                    while True:
                        before = time.perf_counter()
                        try:
                            chunk = await anext(stream)
                        except StopAsyncIteration:
                            break
                        finally:
                            provider_wait += time.perf_counter() - before
                        chars += len(chunk)
                        if first and chunk.strip():
                            first = False
                            log_timing("llm_first_text", time.perf_counter() - started)
                        yield chunk
                finally:
                    metrics["provider_wait_ms"] = round(provider_wait * 1000, 3)
                    metrics["chars"] = chars

    async def _think_and_speak(self, transcript: str) -> None:
        self._transition(State.THINKING)
        if self._config.log_transcripts:
            log_dialogue(
                "MODEL_INPUT",
                text=transcript,
                input_mode="voice" if self._audio is not None else "text",
            )
        reply_started = time.perf_counter()
        name_only = transcript.strip().casefold() == self._config.wake_word.casefold()
        history = (
            self._conversation_history[-2 * (self._config.max_history_turns - 1) :]
            if self._config.max_history_turns > 1
            else []
        )
        messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self._config.assistant_name,
                    agent=self._config.llm_provider == "openclaw",
                ),
            },
            *history,
            {"role": "user", "content": transcript},
        ]
        if self._audio is not None:
            messages.insert(1, {"role": "system", "content": VOICE_INPUT_INSTRUCTIONS})
        if self._interruption_context:
            messages.insert(
                1,
                {
                    "role": "system",
                    "content": (
                        "The user interrupted the previous spoken answer and may not "
                        "have heard it in full. Respond to the new request; do not resume "
                        "the interrupted answer unless asked."
                    ),
                },
            )
        sentences: asyncio.Queue = asyncio.Queue(maxsize=4)
        response = []
        completed_speech = []
        speaking = asyncio.Event()
        first_sentence = True
        # OpenClaw supplies an already finalized reply. Splitting it into separate
        # cloud TTS calls adds a handshake and generation pause after every sentence.
        whole_reply = (
            self._config.llm_provider == "openclaw"
            and self._config.tts_provider == "elevenlabs"
        )

        async def enqueue(sentence):
            nonlocal first_sentence
            if first_sentence:
                first_sentence = False
                log_timing("reply_first_sentence", time.perf_counter() - reply_started)
            await sentences.put(sentence)

        async def produce():
            buffer = ""
            async with aclosing(self._model_chunks(messages)) as stream:
                async for chunk in stream:
                    response.append(chunk)
                    buffer += chunk
                    if name_only or whole_reply:
                        continue
                    parts = re.split(r"(?<=[.!?…])\s+", buffer)
                    for sentence in parts[:-1]:
                        if sentence.strip():
                            await enqueue(sentence.strip())
                    buffer = parts[-1]
                    while len(buffer) > 240:
                        cut = buffer.rfind(" ", 0, 240)
                        cut = cut if cut > 0 else 240
                        await enqueue(buffer[:cut].strip())
                        buffer = buffer[cut:].lstrip()
            if name_only and buffer.strip():
                acknowledgment = re.split(
                    r"(?<=[.!?…])\s+", buffer.strip(), maxsplit=1
                )[0]
                if len(acknowledgment) > 160:
                    cut = acknowledgment.rfind(" ", 0, 160)
                    acknowledgment = acknowledgment[: cut if cut > 0 else 160].rstrip()
                response[:] = [acknowledgment]
                buffer = acknowledgment
            if buffer.strip():
                await enqueue(buffer.strip())
            if not "".join(response).strip():
                raise RuntimeError("Модель вернула пустой ответ")
            await sentences.put(None)

        async def consume():
            async with AsyncExitStack() as speech:
                started = False
                while (sentence := await sentences.get()) is not None:
                    if not started:
                        await speech.enter_async_context(self._pause_music())
                        started = True
                    self._transition(State.SPEAKING)
                    speaking.set()
                    await self._speak(sentence, interruptible=False)
                    completed_speech.append(sentence)
            self._transition(State.THINKING)

        async def deliver():
            async with AsyncExitStack() as stack:
                prepare = getattr(self._tts, "prepare_reply", None)
                if prepare is not None:
                    await stack.enter_async_context(prepare())
                async with asyncio.TaskGroup() as group:
                    group.create_task(produce())
                    group.create_task(consume())

        with stage_timer("reply_total"):
            interrupted = await self._with_barge_in(
                deliver, lambda: "".join(response), speaking
            )
        if not interrupted:
            self._interruption_context = False
        self._conversation_history = [
            *history,
            {"role": "user", "content": transcript},
            {
                "role": "assistant",
                "content": (
                    " ".join(
                        [*completed_speech, "[Spoken answer interrupted by the user.]"]
                    )
                    if interrupted
                    else "".join(response)
                ),
            },
        ]
