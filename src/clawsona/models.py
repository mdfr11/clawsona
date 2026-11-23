"""Explicit one-time model preparation. Normal startup never downloads models."""

import asyncio
import os
from pathlib import Path

import aiohttp


async def download_file(url: str, destination: Path) -> None:
    if destination.is_file() and destination.stat().st_size:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        timeout = aiohttp.ClientTimeout(total=600, connect=20, sock_read=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                with partial.open("wb") as output:
                    async for data in response.content.iter_chunked(128 * 1024):
                        output.write(data)
        if not partial.stat().st_size:
            raise RuntimeError(f"Пустой файл модели: {destination.name}")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


async def prepare_models(config, only="all") -> None:
    needs_piper = config.tts_provider == "piper" or (
        config.tts_provider == "elevenlabs" and config.elevenlabs_fallback
    )
    if only in {"all", "tts"} and needs_piper:
        for voice in dict.fromkeys([config.piper_voice, config.piper_english_voice]):
            locale, speaker, quality = voice.split("-")
            language = locale.split("_")[0]
            base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{language}/{locale}/{speaker}/{quality}/{voice}"
            for suffix in (".onnx", ".onnx.json"):
                path = config.piper_model_path.parent / f"{voice}{suffix}"
                print(f"Подготовка {path.name}", flush=True)
                await download_file(base + suffix, path)
            card = config.piper_model_path.parent / f"{voice}.MODEL_CARD"
            print(f"Условия голоса: {card.name}", flush=True)
            await download_file(base.rsplit("/", 1)[0] + "/MODEL_CARD", card)
    if only in {"all", "stt"} and config.stt_provider == "local":
        # Plain HTTPS avoids an additional CAS/Xet transport and its network
        # requirements. Users can opt back in with HF_HUB_DISABLE_XET=0.
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        from faster_whisper.utils import download_model

        print(f"Подготовка Whisper {config.whisper_model}", flush=True)
        await asyncio.to_thread(
            download_model,
            config.whisper_model,
            output_dir=str(config.whisper_model_path),
        )
    print("Модели подготовлены. Следующий шаг: clawsona doctor", flush=True)
