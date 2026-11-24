import asyncio
import logging
import math
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from clawsona.config import Settings
from clawsona.music_commands import MusicCommand
from clawsona.orchestrator import Orchestrator
from clawsona.prompts import VOICE_INPUT_INSTRUCTIONS
from clawsona.vad import CHUNK_SIZE, VADDetector
from clawsona.wakeword import WakeWordDetector


def make_orchestrator(**overrides):
    config = Settings(
        _env_file=None,
        **(
            {
                "llm_provider": "deepseek",
                "assistant_name": "Мира",
                "assistant_aliases": ["Mira", "Meera"],
                "barge_in_enabled": False,
            }
            | overrides
        ),
    )
    audio = MagicMock()
    audio.read_async = AsyncMock(return_value=np.zeros((CHUNK_SIZE, 1), dtype=np.int16))
    wake = WakeWordDetector(config.assistant_name, config.assistant_aliases)
    vad = MagicMock()
    stt = MagicMock(transcribe_buffer=AsyncMock(return_value="привет"))
    chat = MagicMock()

    async def stream(messages):
        yield "Привет. "
        yield "Давай поговорим!"

    chat.chat_stream = stream
    tts = MagicMock(speak=AsyncMock())
    return Orchestrator(config, audio, wake, vad, stt, chat, tts)


@pytest.mark.asyncio
async def test_barge_in_cancels_output_and_generation_then_handles_complete_new_input():
    orch = make_orchestrator(barge_in_enabled=True, follow_up_without_name=False)
    output_stopped, generator_closed = asyncio.Event(), asyncio.Event()
    input_complete = asyncio.Event()
    received = []

    async def stream(messages):
        received.append(messages)
        try:
            yield "Очень длинный старый ответ. "
            await asyncio.Event().wait()
        finally:
            generator_closed.set()

    async def speak(text):
        try:
            await asyncio.Event().wait()
        finally:
            output_stopped.set()

    async def listen(notify, reference):
        assert "старый ответ" in reference()
        notify()
        await asyncio.wait_for(output_stopped.wait(), 1)
        input_complete.set()
        return "Мира, теперь объясни дроби"

    orch._barge_listener = MagicMock(listen=listen)
    orch._chat.chat_stream = stream
    orch._tts.speak.side_effect = speak
    orch._listen_and_transcribe = AsyncMock(return_value="Мира, первый вопрос")
    turn = MagicMock()
    deadline = await asyncio.wait_for(orch._handle_turn(False, 0, False, turn), 2)
    assert input_complete.is_set() and generator_closed.is_set()
    assert orch._pending_transcript == "Мира, теперь объясни дроби"
    assert turn.result == "interrupted" and deadline > asyncio.get_running_loop().time()
    assert "Очень длинный" not in orch._conversation_history[-1]["content"]
    assert "interrupted" in orch._conversation_history[-1]["content"]

    # The already confirmed phrase goes through regular tool/command handling;
    # no second microphone recording and no repeated name are required.
    orch._config.barge_in_enabled = False
    orch._tts.speak.side_effect = None

    async def final_stream(messages):
        received.append(messages)
        yield "Объяснение дробей."

    orch._chat.chat_stream = final_stream
    await orch._handle_turn(False, 0, False, MagicMock())
    orch._listen_and_transcribe.assert_awaited_once()
    assert received[-1][-1]["content"] == "теперь объясни дроби"
    assert any("may not have heard" in m["content"] for m in received[-1])
    assert not orch._interruption_context


@pytest.mark.asyncio
@pytest.mark.parametrize("transcript", ["Мира", "Мира, стоп", "Mira, wait"])
async def test_name_or_silence_interrupts_without_ack_or_music_control(transcript):
    orch = make_orchestrator(barge_in_enabled=True)
    stopped = asyncio.Event()

    async def speak(text):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def listen(notify, reference):
        notify()
        await asyncio.wait_for(stopped.wait(), 1)
        return transcript

    orch._barge_listener = MagicMock(listen=listen)
    orch._tts.speak.side_effect = speak
    await asyncio.wait_for(orch._speak("Старый ответ"), 2)
    assert orch._pending_transcript is None
    assert orch._interrupted_reply
    orch._tts.speak.assert_awaited_once()


@pytest.mark.asyncio
async def test_monitor_failure_does_not_discard_reply_or_restart_output():
    orch = make_orchestrator(barge_in_enabled=True)
    orch._barge_listener = MagicMock(listen=AsyncMock(side_effect=RuntimeError("mic")))
    await orch._think_and_speak("вопрос")
    assert orch._tts.speak.await_count == 2
    assert orch._conversation_history[-1]["content"] == "Привет. Давай поговорим!"


@pytest.mark.asyncio
async def test_barge_in_does_not_open_microphone_until_speech_starts():
    orch = make_orchestrator(barge_in_enabled=True)
    orch._barge_listener = MagicMock(listen=AsyncMock())

    async def stream(messages):
        orch._barge_listener.listen.assert_not_awaited()
        raise RuntimeError("model unavailable")
        yield

    orch._chat.chat_stream = stream
    with pytest.raises(ExceptionGroup):
        await orch._think_and_speak("вопрос")
    orch._barge_listener.listen.assert_not_awaited()


@pytest.mark.asyncio
async def test_barge_in_preserves_music_speech_guard_until_user_finishes():
    orch = make_orchestrator(barge_in_enabled=True)
    depth = 0
    stopped = asyncio.Event()

    @asynccontextmanager
    async def guard():
        nonlocal depth
        depth += 1
        try:
            yield
        finally:
            depth -= 1

    async def speak(text):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def listen(notify, reference):
        notify()
        await asyncio.wait_for(stopped.wait(), 1)
        assert depth > 0
        return "Мира, другой вопрос"

    orch._music = MagicMock(pause_for_speech=guard, command=AsyncMock())
    orch._barge_listener = MagicMock(listen=listen)
    orch._tts.speak.side_effect = speak
    await asyncio.wait_for(orch._speak("Старый ответ"), 2)
    assert depth == 0
    orch._music.command.assert_not_awaited()


@pytest.mark.asyncio
async def test_music_stop_is_executed_locally_without_a_model_call():
    orch = make_orchestrator()
    orch._listen_and_transcribe = AsyncMock(return_value="Мира, стоп")
    orch._think_and_speak = AsyncMock()
    events = []

    @asynccontextmanager
    async def pause():
        events.append("pause")
        try:
            yield
        finally:
            events.append("resume")

    orch._music = MagicMock(
        pause_for_speech=pause,
        command=AsyncMock(
            return_value={"status": "paused", "track": {"title": "test"}}
        ),
    )
    turn = MagicMock()
    deadline = await orch._handle_turn(False, 0, False, turn)
    orch._music.command.assert_awaited_once_with("pause")
    orch._think_and_speak.assert_not_awaited()
    orch._tts.speak.assert_awaited_once_with("Музыка на паузе.")
    assert turn.result == "music_control"
    assert deadline > asyncio.get_running_loop().time()
    assert events[0] == "pause" and events[-1] == "resume"


@pytest.mark.asyncio
async def test_local_music_ack_keeps_the_language_of_english_practice():
    orch = make_orchestrator()
    orch._conversation_history = [
        {"role": "assistant", "content": "Let's keep practicing English."}
    ]
    orch._music = MagicMock(command=AsyncMock(return_value={"volume": 40}))
    orch._music.pause_for_speech = _empty_context
    await orch._control_music(MusicCommand("volume_down"), "тише")
    orch._tts.speak.assert_awaited_once_with("Music volume is 40 percent.")


@asynccontextmanager
async def _empty_context():
    yield


@pytest.mark.asyncio
async def test_local_music_controls_still_require_activation():
    orch = make_orchestrator()
    orch._listen_and_transcribe = AsyncMock(return_value="громче")
    orch._music = MagicMock(is_audible=False, command=AsyncMock())
    turn = MagicMock()
    await orch._handle_turn(False, 0, False, turn)
    orch._music.command.assert_not_awaited()
    orch._tts.speak.assert_not_awaited()
    assert turn.result == "not_addressed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,audible,active,phrase,expected",
    [
        ("commands", True, True, "Вечером мы идём домой", "ignore"),
        ("commands", True, True, "Давай следующий трек.", "control"),
        ("commands", True, True, "Мира, объясни дроби", "model"),
        ("commands", True, False, "Следующий трек", "control"),
        ("name", True, False, "Следующий трек", "ignore"),
        ("name", True, True, "Давай следующий трек", "ignore"),
        ("name", True, True, "Мира, давай следующий трек", "control"),
        ("all", True, True, "Объясни дроби", "model"),
        ("commands", False, True, "Объясни дроби", "model"),
    ],
)
async def test_music_follow_up_policy(mode, audible, active, phrase, expected, caplog):
    orch = make_orchestrator(music_follow_up=mode, log_transcripts=True)
    orch._music = MagicMock(is_audible=audible, has_playback_context=True)
    orch._listen_and_transcribe = AsyncMock(return_value=phrase)
    orch._think_and_speak = AsyncMock()
    orch._control_music = AsyncMock()
    turn = MagicMock()
    deadline = asyncio.get_running_loop().time() + 60
    with caplog.at_level(logging.INFO):
        result = await orch._handle_turn(active, deadline, False, turn)
    if expected == "control":
        assert orch._control_music.call_args.args[0] == MusicCommand("next")
        orch._think_and_speak.assert_not_awaited()
    elif expected == "model":
        orch._think_and_speak.assert_awaited_once_with(phrase.removeprefix("Мира, "))
        orch._control_music.assert_not_awaited()
    else:
        orch._think_and_speak.assert_not_awaited()
        orch._control_music.assert_not_awaited()
        assert result == deadline
        assert turn.result == "not_addressed"
        assert '"decision": "ignored_music"' in caplog.text


@pytest.mark.asyncio
async def test_music_name_policy_also_applies_to_continuous_activation():
    orch = make_orchestrator(activation="continuous", music_follow_up="name")
    orch._wakeword = None
    orch._music = MagicMock(is_audible=True, has_playback_context=True)
    orch._think_and_speak = AsyncMock()
    orch._listen_and_transcribe = AsyncMock(
        side_effect=["Фоновая песня", "Мира, привет"]
    )
    await orch._handle_turn(True, 0, True, MagicMock())
    orch._think_and_speak.assert_not_awaited()
    await orch._handle_turn(True, 0, True, MagicMock())
    orch._think_and_speak.assert_awaited_once_with("привет")


@pytest.mark.asyncio
async def test_confirmed_interruption_is_not_rejected_by_music_policy():
    orch = make_orchestrator(music_follow_up="name")
    orch._music = MagicMock(is_audible=True)
    orch._pending_transcript = "Объясни новый пример"
    orch._think_and_speak = AsyncMock()
    orch._listen_and_transcribe = AsyncMock()
    await orch._handle_turn(False, 0, False, MagicMock())
    orch._think_and_speak.assert_awaited_once_with("Объясни новый пример")
    orch._listen_and_transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_continue_without_a_music_context_stays_in_the_conversation():
    orch = make_orchestrator()
    orch._music = MagicMock(has_playback_context=False, command=AsyncMock())
    orch._listen_and_transcribe = AsyncMock(return_value="Мира, продолжить")
    orch._think_and_speak = AsyncMock()
    await orch._handle_turn(False, 0, False, MagicMock())
    orch._music.command.assert_not_awaited()
    orch._think_and_speak.assert_awaited_once_with("продолжить")


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_music_pause_spans_all_sentences_and_is_released_on_tts_failure(fail):
    orch = make_orchestrator()
    events = []
    depth = 0

    @asynccontextmanager
    async def pause():
        nonlocal depth
        if depth == 0:
            events.append("pause")
        depth += 1
        try:
            yield
        finally:
            depth -= 1
            if depth == 0:
                events.append("resume")

    orch._music = MagicMock(pause_for_speech=pause)

    async def speak(text):
        assert depth > 0
        if fail:
            raise RuntimeError("TTS unavailable")

    orch._tts.speak = AsyncMock(side_effect=speak)
    if fail:
        with pytest.raises(ExceptionGroup):
            await orch._think_and_speak("вопрос")
    else:
        await orch._think_and_speak("вопрос")
        assert orch._tts.speak.await_count == 2
    assert events == ["pause", "resume"]
    assert depth == 0


@pytest.mark.asyncio
async def test_transcribes_utterance_and_stops_recording():
    orch = make_orchestrator()
    orch._vad.process_chunk.side_effect = [None, "speech_start", None, "speech_end"]
    assert await orch._listen_and_transcribe() == "привет"
    orch._audio.stop.assert_called_once()
    data = orch._stt.transcribe_buffer.call_args.args[0]
    assert len(data) == CHUNK_SIZE * 2 * 4


@pytest.mark.asyncio
async def test_capture_keeps_both_phrases_across_thinking_pause_and_logs_endpoint(
    mocker, caplog
):
    orch = make_orchestrator()
    session = mocker.patch("faster_whisper.vad.get_vad_model").return_value.session
    probabilities = [0.9] * 6 + [0.1] * 40 + [0.9] * 6 + [0.1] * 57
    session.run.side_effect = [
        (
            np.array([[p]], dtype=np.float32),
            np.zeros((1, 1, 128)),
            np.zeros((1, 1, 128)),
        )
        for p in probabilities
    ]
    orch._vad = VADDetector(
        orch._config.vad_silence_duration_ms,
        orch._config.vad_min_speech_ms,
        orch._config.vad_threshold,
    )
    # Distinct PCM markers stand in for speech on either side of a 1.28 s pause.
    amplitudes = [1000] * 6 + [0] * 40 + [2000] * 6 + [0] * 57
    orch._audio.read_async.side_effect = [
        np.full((CHUNK_SIZE, 1), value, dtype=np.int16) for value in amplitudes
    ]
    with caplog.at_level(logging.INFO):
        await orch._listen_and_transcribe()
    orch._stt.transcribe_buffer.assert_awaited_once()
    pcm = np.frombuffer(orch._stt.transcribe_buffer.call_args.args[0], dtype=np.int16)
    assert (pcm == 1000).sum() == 6 * CHUNK_SIZE
    assert (pcm == 2000).sum() == 6 * CHUNK_SIZE
    assert orch._audio.read_async.await_count == len(amplitudes)
    orch._audio.stop.assert_called_once()
    capture = next(
        r.timing
        for r in caplog.records
        if hasattr(r, "timing") and r.timing["stage"] == "capture_record"
    )
    assert capture["end_reason"] == "silence"
    assert capture["end_silence_ms"] == 1824
    assert capture["end_silence_config_ms"] == 1800


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting_frames", [25, 100])
async def test_delayed_speech_detection_keeps_name_onset_and_bounds_preroll(
    waiting_frames,
):
    orch = make_orchestrator(vad_pre_roll_ms=1000)
    orch._audio.read_async.side_effect = [
        np.full((CHUNK_SIZE, 1), i, dtype=np.int16) for i in range(waiting_frames + 2)
    ]
    orch._vad.process_chunk.side_effect = [None] * waiting_frames + [
        "speech_start",
        "speech_end",
    ]
    await orch._listen_and_transcribe()
    pcm = np.frombuffer(orch._stt.transcribe_buffer.call_args.args[0], dtype=np.int16)
    # One second of history survives late VAD activation, but an arbitrarily
    # long idle period must not grow the recording or preserve stale audio.
    assert pcm[0] == max(0, waiting_frames - 31)
    assert pcm[-1] == waiting_frames + 1
    assert len(pcm) <= 33 * CHUNK_SIZE


@pytest.mark.asyncio
async def test_stalled_microphone_times_out_and_closes():
    orch = make_orchestrator(audio_read_timeout_s=0.02, conversation_timeout_s=10)

    async def blocked():
        await asyncio.Event().wait()

    orch._audio.read_async = blocked
    with pytest.raises(RuntimeError, match="Микрофон"):
        await orch._listen_and_transcribe()
    orch._audio.stop.assert_called_once()


@pytest.mark.asyncio
async def test_silence_deadline_even_when_microphone_stalls():
    orch = make_orchestrator(audio_read_timeout_s=1, conversation_timeout_s=0.02)

    async def blocked():
        await asyncio.Event().wait()

    orch._audio.read_async = blocked
    assert await orch._listen_and_transcribe() is None
    orch._audio.stop.assert_called_once()


@pytest.mark.asyncio
async def test_continuous_speech_has_bounded_recording():
    orch = make_orchestrator(max_utterance_s=1)
    orch._vad.process_chunk.side_effect = lambda chunk: "speech_start"
    await orch._listen_and_transcribe()
    assert orch._audio.read_async.await_count == math.ceil(16000 / CHUNK_SIZE)


@pytest.mark.asyncio
async def test_tts_begins_before_model_finishes_and_generation_continues():
    orch = make_orchestrator()
    speaking = asyncio.Event()
    generated = asyncio.Event()

    async def stream(messages):
        yield "Первое предложение. "
        await asyncio.wait_for(speaking.wait(), 0.5)
        yield "Второе предложение."
        generated.set()

    async def speak(text):
        speaking.set()
        await asyncio.wait_for(generated.wait(), 0.5)

    orch._chat.chat_stream = stream
    orch._tts.speak.side_effect = speak
    await orch._think_and_speak("вопрос")
    assert orch._tts.speak.await_count == 2
    assert (
        orch._conversation_history[-1]["content"]
        == "Первое предложение. Второе предложение."
    )


@pytest.mark.asyncio
async def test_openclaw_final_reply_uses_one_tts_call_and_prepares_while_model_waits():
    orch = make_orchestrator(tts_provider="elevenlabs")
    orch._config.llm_provider = "openclaw"
    prepared = asyncio.Event()
    closed = asyncio.Event()

    class TTS:
        speak = AsyncMock()

        @asynccontextmanager
        async def prepare_reply(self):
            prepared.set()
            try:
                yield
            finally:
                closed.set()

    orch._tts = TTS()
    # Longer than the old 240-character splitting limit, including decimals.
    final = "Hello! Привет. Температура 12.5 градуса. " + "Подробное объяснение. " * 15

    async def stream(messages):
        await asyncio.wait_for(prepared.wait(), 0.5)
        assert not closed.is_set()
        yield final

    orch._chat.chat_stream = stream
    await orch._think_and_speak("вопрос")
    orch._tts.speak.assert_awaited_once_with(final.strip())
    assert closed.is_set()
    assert orch._conversation_history[-1]["content"] == final


@pytest.mark.asyncio
async def test_custom_name_and_alias_are_used_throughout_a_conversation():
    orch = make_orchestrator(assistant_name="Атлас", assistant_aliases=["Atlas"])
    orch._listen_and_transcribe = AsyncMock(
        side_effect=["Atlas", "Атлас, привет", asyncio.CancelledError()]
    )
    received = []

    async def stream(messages):
        received.append(messages)
        yield "Привет!"

    orch._chat.chat_stream = stream
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert [messages[-1]["content"] for messages in received] == ["Атлас", "привет"]
    for messages in received:
        assert '"Атлас"' in messages[0]["content"]
        assert "Мира" not in messages[0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("voice", [True, False])
async def test_model_receives_voice_transcript_context_only_for_microphone(voice):
    orch = make_orchestrator()
    if not voice:
        orch._audio = None
    received = []

    async def stream(messages):
        received.extend(messages)
        yield "Let's practise English. How was your day?"

    orch._chat.chat_stream = stream
    transcript = "Ай went to the парк yesterday"
    await orch._think_and_speak(transcript)
    system = [m["content"] for m in received if m["role"] == "system"]
    assert (VOICE_INPUT_INSTRUCTIONS in system) is voice
    assert received[-1]["content"] == transcript


@pytest.mark.asyncio
async def test_system_prompt_history_limit_and_failed_turn_rollback():
    orch = make_orchestrator(max_history_turns=2)
    captured = []

    async def stream(messages):
        captured.append(messages)
        yield "Ответ."

    orch._chat.chat_stream = stream
    for question in ("первый", "второй", "третий"):
        await orch._think_and_speak(question)
    assert captured[-1][0]["role"] == "system"
    assert "первый" not in str(captured[-1])
    assert "второй" in str(captured[-1])
    assert len(orch._conversation_history) == 4
    before = list(orch._conversation_history)
    orch._tts.speak.side_effect = RuntimeError("speaker unavailable")
    with pytest.raises(ExceptionGroup):
        await orch._think_and_speak("неудачный вопрос")
    assert orch._conversation_history == before


@pytest.mark.asyncio
async def test_tts_failure_closes_incomplete_llm_stream():
    orch = make_orchestrator()
    closed = asyncio.Event()

    async def stream(messages):
        try:
            for _ in range(20):
                yield "Предложение. "
        finally:
            closed.set()

    orch._chat.chat_stream = stream
    orch._tts.speak.side_effect = RuntimeError("speaker unavailable")
    with pytest.raises(ExceptionGroup):
        await asyncio.wait_for(orch._think_and_speak("вопрос"), timeout=1)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_error_recovers_and_context_survives_next_activation():
    orch = make_orchestrator(error_retry_delay_s=0.001)
    orch._conversation_history = [
        {"role": "user", "content": "тема урока"},
        {"role": "assistant", "content": "хорошо"},
    ]
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[RuntimeError("mic unavailable"), asyncio.CancelledError()]
    )
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert orch._listen_and_transcribe.await_count == 2
    assert orch._conversation_history[0]["content"] == "тема урока"
    orch._tts.stop.assert_called_once()


@pytest.mark.parametrize(
    "text,command",
    [
        ("Стоп!", "stop"),
        ("Новый разговор.", "reset"),
        ("Объясни слово стоп", None),
        ("Goodbye!", "stop"),
        ("Explain the word goodbye", None),
    ],
)
def test_local_commands_require_complete_phrase(text, command):
    assert Orchestrator.command(text) == command


@pytest.mark.asyncio
async def test_full_conversation_preserves_context_until_explicit_reset():
    orch = make_orchestrator()
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[
            "Мира, что такое дробь?",
            None,
            "Мира, приведи пример",
            "Мира, новый разговор",
            "Стоп",
            asyncio.CancelledError(),
        ]
    )
    received = []

    async def stream(messages):
        received.append(messages)
        yield "Простой ответ."

    orch._chat.chat_stream = stream
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert len(received) == 3  # two questions + model-selected reset greeting
    assert any(m["content"] == "что такое дробь?" for m in received[1])
    assert not any(m["content"] == "что такое дробь?" for m in received[2])


@pytest.mark.asyncio
async def test_name_and_question_need_no_acknowledgment_barrier():
    orch = make_orchestrator()
    orch._listen_and_transcribe = AsyncMock(
        side_effect=["Мира, привет, какая погода в Крымске?", asyncio.CancelledError()]
    )
    received = []

    async def stream(messages):
        received.append(messages)
        yield "Ответ на вопрос."

    orch._chat.chat_stream = stream
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert received[0][-1]["content"] == "привет, какая погода в Крымске?"
    assert [call.args[0] for call in orch._tts.speak.await_args_list] == [
        "Ответ на вопрос."
    ]


@pytest.mark.asyncio
async def test_name_only_ack_is_generated_by_model_and_background_stays_local():
    orch = make_orchestrator()
    orch._listen_and_transcribe = AsyncMock(
        side_effect=["Включи телевизор", "Мира", asyncio.CancelledError()]
    )
    received = []

    async def stream(messages):
        received.append(messages)
        yield "Да, я здесь!"

    orch._chat.chat_stream = stream
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert len(received) == 1
    assert received[0][-1]["content"] == "Мира"
    orch._tts.speak.assert_awaited_once_with("Да, я здесь!")


@pytest.mark.asyncio
async def test_name_only_acknowledgment_is_one_model_selected_phrase():
    orch = make_orchestrator()

    async def stream(messages):
        yield "Да, что хотел?\n\nДа, что хотел?"

    orch._chat.chat_stream = stream
    await orch._think_and_speak("Мира")
    orch._tts.speak.assert_awaited_once_with("Да, что хотел?")
    assert orch._conversation_history[-1]["content"] == "Да, что хотел?"


@pytest.mark.asyncio
async def test_answer_returns_to_name_activation_and_noise_never_reaches_model():
    orch = make_orchestrator(follow_up_without_name=False)
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[
            "Мира, объясни дроби",
            "",
            "длинный длинный длинный",
            "Субтитры сделал автор",
            "Мира, приведи пример",
            asyncio.CancelledError(),
        ]
    )
    orch._think_and_speak = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert [c.args[0] for c in orch._think_and_speak.await_args_list] == [
        "объясни дроби",
        "приведи пример",
    ]


@pytest.mark.asyncio
async def test_name_alone_opens_one_question_window_and_rejected_noise_is_ignored():
    orch = make_orchestrator(follow_up_without_name=False)
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[
            "Мира",
            "",
            "объясни дроби",
            "посторонняя речь",
            asyncio.CancelledError(),
        ]
    )
    orch._think_and_speak = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert [c.args[0] for c in orch._think_and_speak.await_args_list] == [
        "Мира",
        "объясни дроби",
    ]


@pytest.mark.asyncio
async def test_noise_does_not_extend_follow_up_deadline(mocker):
    orch = make_orchestrator(conversation_timeout_s=15)
    clock = mocker.Mock()
    clock.time.side_effect = [0, 0, 1, 2, 3, 4, 16, 17]
    mocker.patch(
        "clawsona.orchestrator.asyncio", wraps=asyncio
    ).get_running_loop.return_value = clock
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[
            "Мира",
            "",
            "",
            "посторонняя речь",
            asyncio.CancelledError(),
        ]
    )
    orch._think_and_speak = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    orch._think_and_speak.assert_awaited_once_with("Мира")


@pytest.mark.asyncio
async def test_default_free_follow_up_remains_available():
    orch = make_orchestrator()
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[
            "Мира, объясни дроби",
            "приведи пример",
            None,
            "посторонняя речь",
            asyncio.CancelledError(),
        ]
    )
    orch._think_and_speak = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert [c.args[0] for c in orch._think_and_speak.await_args_list] == [
        "объясни дроби",
        "приведи пример",
    ]


@pytest.mark.asyncio
async def test_english_goodbye_ends_conversation_with_english_farewell():
    orch = make_orchestrator()
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[
            "Мира, давай говорить на английском",
            "Goodbye!",
            "Background speech",
            asyncio.CancelledError(),
        ]
    )
    orch._think_and_speak = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    orch._think_and_speak.assert_awaited_once()
    orch._tts.speak.assert_awaited_once_with("See you.")


@pytest.mark.asyncio
async def test_learning_dialogue_needs_name_once_and_goodbye_closes_it():
    orch = make_orchestrator()
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[
            "Посторонний разговор",
            "Мира, помоги с английским",
            "Я совсем с нуля",
            "",
            "Хочу понимать речь на слух",
            "Пока",
            "Посторонняя речь",
            asyncio.CancelledError(),
        ]
    )
    received = []

    async def stream(messages):
        received.append(messages)
        yield "Давай разберёмся вместе."

    orch._chat.chat_stream = stream
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert [m[-1]["content"] for m in received] == [
        "помоги с английским",
        "Я совсем с нуля",
        "Хочу понимать речь на слух",
    ]
    assert any(m["content"] == "Я совсем с нуля" for m in received[-1][:-1])
    assert orch._tts.speak.await_args_list[-1].args[0] == "До встречи."


@pytest.mark.asyncio
async def test_transcript_logs_show_routing_and_actual_model_input(caplog):
    caplog.set_level("INFO", logger="clawsona.timing")
    orch = make_orchestrator(log_transcripts=True)
    orch._stt.last_transcript = "Неуверенный кандидат"
    orch._stt.last_rejection_reason = "low_confidence"
    orch._listen_and_transcribe = AsyncMock(
        side_effect=[
            "Посторонняя речь",
            "Мира, объясни дроби",
            "Приведи пример",
            "",
            asyncio.CancelledError(),
        ]
    )
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    events = [r.dialogue for r in caplog.records if hasattr(r, "dialogue")]
    transcripts = [e for e in events if e["event"] == "TRANSCRIPT"]
    model_inputs = [e for e in events if e["event"] == "MODEL_INPUT"]
    assert [e["decision"] for e in transcripts] == [
        "ignored",
        "addressed",
        "follow_up",
        "rejected",
    ]
    assert transcripts[1]["text"] == "Мира, объясни дроби"
    assert [e["text"] for e in model_inputs] == ["объясни дроби", "Приведи пример"]
    assert model_inputs[0]["turn"] == transcripts[1]["turn"]
    assert model_inputs[1]["turn"] == transcripts[2]["turn"]
    assert transcripts[-1]["text"] == "Неуверенный кандидат"
    assert transcripts[-1]["reason"] == "low_confidence"


@pytest.mark.asyncio
async def test_transcript_logging_can_be_disabled_without_losing_timings(caplog):
    caplog.set_level("INFO", logger="clawsona.timing")
    orch = make_orchestrator(log_transcripts=False)
    orch._listen_and_transcribe = AsyncMock(
        side_effect=["Мира, привет", asyncio.CancelledError()]
    )
    with pytest.raises(asyncio.CancelledError):
        await orch.run()
    assert not any(hasattr(r, "dialogue") for r in caplog.records)
    assert any(hasattr(r, "timing") for r in caplog.records)
