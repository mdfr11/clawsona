"""Keep unit tests independent of native audio initialization and devices."""

import sys
from types import ModuleType


def _unexpected_audio_io(*args, **kwargs):
    raise AssertionError("Unit tests must explicitly mock audio device operations")


# Importing sounddevice initializes PortAudio, which can try to connect to a
# PulseAudio server even before any stream opens. Tests already replace streams
# with fakes; replace the module before collection as well, on every platform.
# Unmocked I/O fails loudly instead of silently claiming to play or record audio.
audio = ModuleType("sounddevice")
for name in (
    "InputStream",
    "OutputStream",
    "RawOutputStream",
    "play",
    "wait",
    "stop",
    "query_devices",
    "check_input_settings",
    "check_output_settings",
):
    setattr(audio, name, _unexpected_audio_io)
sys.modules["sounddevice"] = audio
