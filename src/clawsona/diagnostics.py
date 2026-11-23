import asyncio
import importlib
import io
import time
import wave

from clawsona.chat import create_chat_client


async def doctor(config, check_llm=False, check_audio=True, check_speech=False) -> int:
    failed = False

    def report(label, action):
        nonlocal failed
        try:
            result = action()
            print(f"OK    {label}" + (f": {result}" if result else ""))
        except Exception as exc:
            failed = True
            print(f"ERROR {label}: {exc}")

    def check_file(path):
        if not path.is_file() or not path.stat().st_size:
            raise FileNotFoundError(f"{path}; выполните clawsona setup")

    report("Настройки модели", lambda: create_chat_client(config).model)
    if config.stt_provider == "local":
        report(
            "faster-whisper", lambda: importlib.import_module("faster_whisper") and None
        )
        for filename in ("model.bin", "config.json", "tokenizer.json"):
            report(
                f"Whisper {filename}",
                lambda name=filename: check_file(config.whisper_model_path / name),
            )
    else:
        report("Deepgram SDK", lambda: importlib.import_module("deepgram") and None)
        report(
            "Deepgram key",
            lambda: require(config.deepgram_api_key, "Задайте DEEPGRAM_API_KEY"),
        )
    if config.tts_provider == "piper":
        report("Piper", lambda: importlib.import_module("piper") and None)
        report("Голос Piper", lambda: check_file(config.piper_model_path))
        report(
            "Конфигурация Piper",
            lambda: check_file(config.piper_model_path.with_suffix(".onnx.json")),
        )
        report(
            "Английский голос Piper",
            lambda: check_file(config.piper_english_model_path),
        )
        report(
            "Конфигурация английского Piper",
            lambda: check_file(
                config.piper_english_model_path.with_suffix(".onnx.json")
            ),
        )
    elif config.tts_provider == "elevenlabs":
        from clawsona.local_speech import create_tts

        report(
            "ElevenLabs: ключ, голос и модель",
            lambda: create_tts(config) and config.elevenlabs_model,
        )
        if config.elevenlabs_fallback:
            for path in (config.piper_model_path, config.piper_english_model_path):
                report(f"Резерв Piper {path.stem}", lambda p=path: check_file(p))
                report(
                    f"Конфигурация {path.stem}",
                    lambda p=path: check_file(p.with_suffix(".onnx.json")),
                )
    else:
        import shutil

        report("edge-tts", lambda: importlib.import_module("edge_tts") and None)
        report("FFmpeg", lambda: require(shutil.which("ffmpeg"), "Установите ffmpeg"))
    report("Имя ассистента", lambda: config.assistant_name)
    report("Варианты обращения", lambda: ", ".join(config.assistant_aliases) or "нет")
    if check_audio:
        import sounddevice as sd

        report(
            "Микрофон 16 кГц mono",
            lambda: sd.check_input_settings(
                device=config.input_device, channels=1, dtype="int16", samplerate=16000
            ),
        )
        report(
            "Динамик",
            lambda: sd.check_output_settings(device=config.output_device, channels=1),
        )
    if check_speech:
        try:
            result = await check_local_speech(config)
            print(f"OK    Локальная речь: {result}")
        except Exception as exc:
            failed = True
            print(f"ERROR Локальная речь: {exc}")
    if check_llm:
        try:
            client = create_chat_client(config)
            response = "".join(
                [
                    part
                    async for part in client.chat_stream(
                        [{"role": "user", "content": "Ответь одним словом: готово"}]
                    )
                ]
            )
            require(response.strip(), "Модель вернула пустой ответ")
            print("OK    Реальный ответ модели")
        except Exception as exc:
            failed = True
            print(f"ERROR Реальный ответ модели: {exc}")
    print("Настройка требует исправлений." if failed else "Проверки пройдены.")
    return int(failed)


def require(value, message):
    if not value:
        raise ValueError(message)


async def check_local_speech(config) -> str:
    """Exercise real TTS → PCM resampling → STT without speakers or a microphone."""
    from faster_whisper.audio import decode_audio

    from clawsona.local_speech import LocalSTT, PiperTTS

    def synthesize():
        started = time.perf_counter()
        english = config.stt_language == "en"
        tts = PiperTTS(
            config.piper_english_model_path if english else config.piper_model_path
        )
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            tts._voice.synthesize_wav(
                "Hello. Today we are learning English."
                if english
                else "Привет. Сегодня мы изучаем русский язык.",
                wav,
            )
        output.seek(0)
        import numpy as np

        pcm = (decode_audio(output, sampling_rate=16000) * 32767).astype(np.int16)
        from clawsona.vad import CHUNK_SIZE, VADDetector

        vad = VADDetector(
            config.vad_silence_duration_ms,
            config.vad_min_speech_ms,
            config.vad_threshold,
        )
        padded = np.concatenate(
            (pcm, np.zeros((config.vad_silence_duration_ms + 600) * 16, dtype=np.int16))
        )
        events = [
            vad.process_chunk(padded[offset : offset + CHUNK_SIZE])
            for offset in range(0, len(padded) - CHUNK_SIZE + 1, CHUNK_SIZE)
        ]
        require(
            "speech_start" in events and "speech_end" in events,
            "VAD не выделил тестовую речь; проверьте настройки VAD",
        )
        return pcm.tobytes(), time.perf_counter() - started

    pcm, synthesis_s = await asyncio.to_thread(synthesize)
    stt = await asyncio.to_thread(
        LocalSTT,
        config.whisper_model_path,
        cpu_threads=config.whisper_cpu_threads,
        wake_word=config.wake_word,
        name_aliases=config.assistant_aliases,
        hotwords=config.stt_hotwords,
        beam_size=config.whisper_beam_size,
        min_logprob=config.stt_min_logprob,
        max_no_speech_prob=config.stt_max_no_speech_prob,
        max_compression_ratio=config.stt_max_compression_ratio,
        vad_threshold=config.vad_threshold,
        min_speech_ms=config.vad_min_speech_ms,
        language=config.stt_language,
    )
    started = time.perf_counter()
    transcript = await stt.transcribe_buffer(pcm)
    require(
        ("hello" if config.stt_language == "en" else "привет") in transcript.lower(),
        f"Не распознана тестовая фраза: {transcript!r}",
    )
    return f"{transcript!r}; TTS {synthesis_s:.1f} с, STT {time.perf_counter() - started:.1f} с"
