from dataclasses import dataclass

from deepgram import AsyncDeepgramClient
from deepgram.core.request_options import RequestOptions

SAMPLE_RATE = 16000


@dataclass
class PrerecordedOptions:
    language: str
    model: str
    encoding: str
    sample_rate: int
    channels: int


class DeepgramSTT:
    def __init__(self, api_key: str | None = None):
        if api_key is None:
            from clawsona.config import Settings

            api_key = Settings().deepgram_api_key
        self._client = AsyncDeepgramClient(api_key=api_key)

    async def transcribe_buffer(self, audio_data: bytes) -> str:
        """Send raw PCM audio (int16, 16kHz, mono) to Deepgram, return transcript."""
        options = PrerecordedOptions(
            language="ru",
            model="nova-3",
            encoding="linear16",
            sample_rate=SAMPLE_RATE,
            channels=1,
        )
        response = await self._client.listen.v1.media.transcribe_file(
            request=audio_data,
            encoding=options.encoding,
            language=options.language,
            model=options.model,
            request_options=RequestOptions(
                additional_query_parameters={"sample_rate": options.sample_rate}
            ),
        )
        return response.results.channels[0].alternatives[0].transcript
