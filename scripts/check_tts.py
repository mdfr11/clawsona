"""Speak a Russian phrase with the configured TTS provider."""

import asyncio

from clawsona.config import Settings
from clawsona.local_speech import create_tts


async def main():
    config = Settings()
    client = create_tts(config)
    await client.speak(
        f"Привет, я {config.assistant_name}! Давай сегодня научимся чему-нибудь новому."
    )


if __name__ == "__main__":
    asyncio.run(main())
