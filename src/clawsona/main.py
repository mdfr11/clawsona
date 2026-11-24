import argparse
import asyncio
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from clawsona.chat import create_chat_client
from clawsona.config import Settings
from clawsona.timing import format_duration, stage_timer, trace_turn

logger = logging.getLogger(__name__)


def setup_logging(level="INFO", log_file=None) -> None:
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
        )
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    # Keep signed download URLs and low-level HTTP chatter out of normal logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)


async def async_main(config: Settings | None = None, *, music=None) -> None:
    from clawsona.audio_io import AudioCapture
    from clawsona.local_speech import create_stt, create_tts
    from clawsona.orchestrator import Orchestrator
    from clawsona.vad import CHUNK_SIZE, VADDetector
    from clawsona.wakeword import WakeWordDetector

    config = config or Settings()
    chat = create_chat_client(config)
    # Fail early with actionable messages before opening any audio streams.
    with stage_timer("startup_stt", provider=config.stt_provider):
        stt = create_stt(config)
    with stage_timer("startup_tts", provider=config.tts_provider):
        tts = create_tts(config)
    wakeword = (
        WakeWordDetector(config.assistant_name, config.assistant_aliases)
        if config.activation == "name"
        else None
    )
    audio = AudioCapture(config.sample_rate, CHUNK_SIZE, device=config.input_device)
    with stage_timer("startup_vad"):
        vad = VADDetector(
            config.vad_silence_duration_ms,
            config.vad_min_speech_ms,
            config.vad_threshold,
        )
    orch = Orchestrator(config, audio, wakeword, vad, stt, chat, tts, music=music)
    logger.info(
        "STT=%s, TTS=%s, LLM=%s/%s",
        config.stt_provider,
        config.tts_provider,
        config.llm_provider,
        config.chat_model,
    )
    if config.stt_provider == "local":
        logger.info(
            "Whisper %s: язык %s, CPU int8, потоков %d, beam %d, "
            "буфер начала речи %s, пауза завершения реплики %s",
            config.whisper_model,
            config.stt_language,
            config.whisper_cpu_threads,
            config.whisper_beam_size,
            format_duration(config.vad_pre_roll_ms / 1000),
            format_duration(config.vad_silence_duration_ms / 1000),
        )
    if config.tts_provider == "elevenlabs":
        logger.info(
            "ElevenLabs %s, голос %s, резерв Piper: %s",
            config.elevenlabs_model,
            config.elevenlabs_voice_id,
            "включён" if config.elevenlabs_fallback else "отключён",
        )
    activation = (
        f"Скажи «{config.assistant_name}»" if wakeword else "Говори после ответа"
    )
    if config.barge_in_enabled:
        logger.info(
            "Прерывание ответа: %s",
            f"обращением по имени «{config.assistant_name}»"
            if config.barge_in_mode == "name"
            else "любой фразой (для наушников)",
        )
    print(
        f"{config.assistant_name}: можно говорить. {activation}. Для выхода — Ctrl+C.",
        flush=True,
    )
    await orch.run()


class ConsoleTTS:
    async def speak(self, text):
        print(text, flush=True)


async def text_main(config: Settings) -> None:
    from clawsona.orchestrator import Orchestrator

    orch = Orchestrator(
        config, None, None, None, None, create_chat_client(config), ConsoleTTS()
    )
    print(
        f"{config.assistant_name}: текстовый режим. /reset — новый разговор, /quit — выход."
    )
    # input() is only called while no background model/audio work is active.
    while True:
        try:
            text = input("Ты: ").strip()
        except EOFError:
            return
        if text == "/quit":
            return
        if text == "/reset":
            orch.reset_conversation()
            continue
        if not text:
            continue
        print(f"{config.assistant_name}: ", end="", flush=True)
        try:
            with trace_turn() as turn:
                await orch._think_and_speak(text)
                turn.result = "reply"
        except Exception as exc:
            logger.error("Не удалось получить ответ: %s", exc)


async def dispatch(args) -> int:
    from clawsona.models import prepare_models

    config = Settings(
        **({"piper_voice": args.voice, "tts_provider": "piper"} if args.voice else {})
    )
    setup_logging(config.log_level, config.log_file)
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
    except (NotImplementedError, RuntimeError):
        pass
    if args.command == "openclaw-setup":
        from clawsona.openclaw_setup import prepare_openclaw

        await prepare_openclaw(config)
    elif args.command == "openclaw-gateway":
        from clawsona.openclaw_setup import run_gateway

        await run_gateway(config)
    elif args.command == "yandex-login":
        from clawsona.yandex_auth import login

        await login()
    elif args.command == "tools":
        from clawsona.tool_server import serve_tools

        async with serve_tools(config):
            print("Локальные инструменты OpenClaw запущены.", flush=True)
            await asyncio.Event().wait()
    elif args.command == "setup":
        await prepare_models(config, args.only)
    elif args.command == "elevenlabs-voices":
        from clawsona.elevenlabs_tts import list_voices

        for voice in await list_voices(config.elevenlabs_api_key):
            labels = voice.get("labels", {})
            print(
                f"{voice['voice_id']}  {voice['name']}  "
                f"({labels.get('gender', '?')}, {labels.get('language', '?')})"
            )
    elif args.command == "voice-test":
        from clawsona.local_speech import PiperTTS, create_tts

        with stage_timer(
            "startup_tts", provider="piper" if args.voice else config.tts_provider
        ):
            tts = (
                PiperTTS(config.piper_model_path, device=config.output_device)
                if args.voice
                else create_tts(config)
            )
        phrase = (
            args.say
            if args.say is not None
            else (
                f"Привет! Я {config.assistant_name}. Давай поговорим или вместе разберёмся в чём-нибудь новом."
            )
        )
        if args.output:
            if not hasattr(tts, "save_wav"):
                raise ValueError("Экспорт WAV поддерживают Piper и ElevenLabs")
            path = args.output.expanduser().resolve()
            await tts.save_wav(phrase, path)
            print(f"Озвучка {'piper' if args.voice else config.tts_provider}: {path}")
        else:
            await tts.speak(phrase)
    elif args.command == "doctor":
        from clawsona.diagnostics import doctor

        return await doctor(
            config,
            check_llm=args.check_llm,
            check_audio=not args.no_audio,
            check_speech=args.check_speech,
        )
    elif args.command == "devices":
        import sounddevice as sd

        print(sd.query_devices())
    elif args.command == "text" or args.text:
        if config.llm_provider == "openclaw":
            from clawsona.openclaw_setup import ensure_gateway
            from clawsona.tool_server import serve_tools

            async with serve_tools(config), ensure_gateway(config):
                await text_main(config)
        else:
            await text_main(config)
    else:
        if config.llm_provider == "openclaw":
            from clawsona.openclaw_setup import ensure_gateway
            from clawsona.tool_server import serve_tools

            async with serve_tools(config) as music, ensure_gateway(config):
                await async_main(config, music=music)
        else:
            await async_main(config)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ClawSona — голосовой компаньон для OpenClaw"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=[
            "run",
            "setup",
            "doctor",
            "devices",
            "text",
            "openclaw-setup",
            "openclaw-gateway",
            "tools",
            "yandex-login",
            "voice-test",
            "elevenlabs-voices",
        ],
    )
    parser.add_argument(
        "--text", action="store_true", help="Текстовый диалог без микрофона"
    )
    parser.add_argument(
        "--only",
        choices=["all", "stt", "tts"],
        default="all",
        help="Какие модели подготовить (setup)",
    )
    parser.add_argument(
        "--check-llm",
        action="store_true",
        help="Проверить реальный ответ модели (doctor)",
    )
    parser.add_argument(
        "--check-speech",
        action="store_true",
        help="Проверить локальную озвучку и распознавание без микрофона (doctor)",
    )
    parser.add_argument(
        "--no-audio", action="store_true", help="Пропустить проверку устройств (doctor)"
    )
    parser.add_argument(
        "--voice", help="Разовый выбор модели Piper (setup, voice-test, run)"
    )
    parser.add_argument(
        "--output", type=Path, help="Сохранить WAV вместо воспроизведения (voice-test)"
    )
    parser.add_argument(
        "--say",
        default=None,
        help="Текст для проверки голоса (voice-test)",
    )
    args = parser.parse_args()
    try:
        code = asyncio.run(dispatch(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nГолосовой помощник завершает работу.", flush=True)
        code = 0
    except Exception as exc:
        print(
            f"Ошибка запуска: {exc}\nПроверка настройки: clawsona doctor",
            file=sys.stderr,
        )
        code = 1
    raise SystemExit(code)
