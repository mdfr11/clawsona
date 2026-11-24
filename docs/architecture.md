# Architecture

ClawSona is the voice interface around an OpenClaw agent. The agent manages
model calls, session context and tool selection. The Python application manages
audio, activation, transcription, playback and the local tool HTTP server.

## Voice turn

1. `audio_io.py` captures mono PCM int16 at 16 kHz. `vad.py` uses the local
   Silero ONNX model shipped with faster-whisper to detect speech boundaries.
2. `orchestrator.py` retains pre-roll and records until the configured silence
   interval or utterance limit. It closes the microphone before processing.
3. `local_speech.py` transcribes through faster-whisper. Confidence, no-speech
   and repetition checks reject uncertain results. Language selection is RU/EN.
4. `wakeword.py` checks the configured name/aliases near the start of the phrase.
   During an active follow-up window, another name is not required. This is a
   text-based activation check, not speaker recognition or a dedicated wake model.
   After activation, `music_commands.py` routes explicit short playback controls
   directly to the shared music player. These commands do not call the model;
   other requests continue through OpenClaw. Playback acknowledgements preserve
   the language of an active English conversation.
5. `chat.py` selects direct model access or `openclaw_client.py`. In OpenClaw
   mode, the session is identified across turns; local history is not repeatedly
   replayed to the agent. `prompts.py` supplies voice-dialogue instructions and
   the configured identity on each request.
6. The final OpenClaw reply is spoken through local bilingual Piper or
   `elevenlabs_tts.py`. ElevenLabs can preconnect while the model thinks; no text
   is sent for synthesis until a reply is available. An optional Piper fallback
   handles failures before playback.
7. `barge_in.py` monitors the microphone only after speech starts. The default
   name mode runs bounded STT windows, checks the configured name/aliases and
   rejects text matching the answer. This is a text echo guard, not AEC.
   Headphone-only speech mode confirms on VAD instead. On confirmation the
   orchestrator cancels and joins the reply task (producer and TTS), keeps the
   music speech guard active, and finishes recording the new phrase without
   losing its buffered onset. A pending transcript enters the next regular turn
   without reopening the microphone or requiring activation again. Completed
   sentences and an interruption marker enter local history; unspoken text does
   not. A system note tells OpenClaw that its full stored reply was not necessarily
   heard. With interruption disabled the mic stays closed during playback.
   Piper/Whisper workers are joined on cancellation before their state is reused.

After playback, the follow-up window opens. Rejected noise does not extend it.
A goodbye closes the window; a new-conversation command resets the agent
session identifier. Resetting a conversation does not delete saved logs/sessions.

## OpenClaw integration

`openclaw_setup.py` generates the dedicated profile, provider configuration,
workspace instructions, plugin path and local tokens. The default provider is
the official DeepSeek API. It does not modify the primary OpenClaw profile.
Re-running setup rewrites the managed profile; custom edits need to be preserved
separately. Setup takes a configuration backup before replacing an existing file.

The application starts a gateway if the configured local address is not already
listening. On exit it terminates only a gateway it started. When using a separately
running gateway, ensure it is the intended profile before starting the application.

`openclaw/clawsona-tools/index.js` registers tools and forwards calls to
`tool_server.py` over authenticated loopback HTTP. `agent_tools.py` validates and
implements weather/search requests. `music.py` implements optional Yandex Music and a bounded track queue.
`music_playback.py` controls a private mpv process over a Unix socket in a mode-0700
temporary directory. The agent receives bounded music actions, never arbitrary
mpv commands or access to the IPC socket. Volume changes do not reload the track.
A persistent IPC observer identifies natural EOF by playlist entry and player
instance, so stale events and manual stops cannot advance another track. Queue
resolution runs outside the control lock; stop/pause remain available while the
provider responds. The queue does not repeat. Speech defaults to a short volume
fade to a configurable fraction of the selected level, then restores the latest
user level. Full speech pause remains available. Both policies preserve manual
pause/stop and share a nested, cancellation-safe speech context.
Tool results are data, not instructions. Network failures must not be reported
as successful actions. The generated tool allowlist enables weather/search,
session status and, only when configured, music.

## Configuration, models and observability

- `config.py`: typed `.env` settings, configurable name and explicit name aliases.
- `models.py`: explicit one-time downloads. Normal startup uses local models.
- `diagnostics.py`: configuration checks and opt-in live model/speech checks.
- `timing.py`: monotonic stage measurements and per-turn context. Some stages
  overlap; do not sum them to infer total latency.
- `main.py`: CLI, startup/shutdown, logging and diagnostics dispatch.

Generated credentials, models, logs and session histories are local runtime
state and excluded from source/release artifacts. Voice model cards are
downloaded alongside newly prepared Piper models; their terms are independent
of the application license.

## Testing boundaries

Tests use fake audio/model clients, temporary files and local HTTP servers.
They cover conversation state, VAD boundaries, uncertain transcription,
configuration, cancellation, provider protocols and tool authorization.
CI checks Python versions/platforms, lint, plugin syntax and package contents.
Real microphone behavior, acoustic conditions and hosted service availability
remain device/provider integration checks, not unit test guarantees.
