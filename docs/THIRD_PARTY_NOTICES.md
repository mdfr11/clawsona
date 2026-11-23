# Third-party components and models

The [ClawSona license](../LICENSE) covers the project's original code. It does
not replace the licenses of dependencies, model weights, datasets or services.
Dependencies are installed separately; model files are downloaded by `setup`
and are not bundled in the source distribution or wheel.

## Main components

| Component | Upstream / license |
| --- | --- |
| OpenClaw | [Repository](https://github.com/openclaw/openclaw), MIT |
| faster-whisper | [Repository](https://github.com/SYSTRAN/faster-whisper), MIT |
| Whisper models | [OpenAI Whisper](https://github.com/openai/whisper), MIT; converted models come from the configured faster-whisper repository |
| Silero VAD | [Repository](https://github.com/snakers4/silero-vad), MIT; ONNX model provided by faster-whisper |
| Piper (`piper-tts`) | [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl), GPL-3.0-or-later; see [COPYING](https://github.com/OHF-Voice/piper1-gpl/blob/main/COPYING) |
| sounddevice | [Repository](https://github.com/spatialaudio/python-sounddevice), MIT; PortAudio is a separate native dependency |
| aiohttp | [Repository](https://github.com/aio-libs/aiohttp), Apache-2.0 / MIT components |

This table is an overview, not a complete dependency license inventory. Installed
packages include their own metadata and license files. Optional integrations
and transitive/native libraries also retain their licenses. Include the relevant
notices and comply with their terms when redistributing a complete installation.

## Optional music playback

Music playback uses the separately installed [mpv player](https://mpv.io),
with its own [license and build notices](https://github.com/mpv-player/mpv/blob/master/Copyright).
It is not bundled with the Python wheel. The Python client controls only its own
local mpv process; no additional music-control cloud service is used.

## Piper voices

Do not infer a voice model's terms solely from the repository's top-level
license. Check the per-voice `MODEL_CARD`, dataset terms and any linked license.
`setup --only tts` saves the upstream card next to each voice as
`<voice>.MODEL_CARD`. Preparing an existing model also fetches its card if missing.

The default voices reference these cards:

- [`ru_RU-denis-medium`](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/denis/medium/MODEL_CARD): the card identifies a CC0 dataset.
- [`en_US-ljspeech-medium`](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD): the card identifies the public-domain LJ Speech dataset.

Other voices can have different restrictions. For example,
[`en_US-ryan-medium`](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ryan/medium/MODEL_CARD)
identifies a CC BY-NC-SA 4.0 dataset. An existing personal voice selection is
preserved; it is not a promise that the selected model permits every use.
Verify upstream terms before commercial use or redistributing weights.

## Hosted services

DeepSeek, ElevenLabs, Open-Meteo and Yandex Music are independent providers.
Their API/account/subscription terms, usage limits and pricing apply separately.
An open-source ClawSona license does not include free hosted API credits,
music rights or a provider subscription. Yandex Music uses an unofficial client
and is an experimental integration.
