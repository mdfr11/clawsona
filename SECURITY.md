# Security and privacy

## Reporting a vulnerability

If GitHub private vulnerability reporting is enabled for this repository,
use **Security → Report a vulnerability**. Otherwise, open an issue asking
for a private reporting channel without publishing exploit details or secrets.
Include the affected version, prerequisites, impact and a minimal reproduction
when a private channel is available. This project does not promise a response SLA.

Do not post API keys, `.env` files, gateway tokens, account tokens, session
histories or unredacted conversation logs in public issues. If credentials have
been disclosed, revoke them at the provider and replace the local values.

## Deployment boundaries

The generated gateway and tool server bind to loopback and use separate bearer
tokens. They are intended for a trusted local machine, not public exposure.
Treat those tokens as credentials even on a shared computer. `openclaw-setup`
manages a dedicated profile; do not point it at a workspace you manage separately.

OpenClaw and external service accounts are separate dependencies. Keep them
updated and report vulnerabilities in those components to their maintainers.
The tested OpenClaw version in the README is a compatibility reference, not a
security endorsement of an old release.

## Data handling

Default speech detection/transcription and Piper synthesis run locally.
Recognized user requests go to the configured model backend. Tool requests
contact their respective providers. ElevenLabs receives reply text when enabled;
optional Deepgram/edge-tts integrations also send data to their services.

Normal conversation does not save microphone audio. Logs may contain recognized
phrases and model input if `LOG_TRANSCRIPTS=true`. OpenClaw separately stores
sessions in its profile; turning off transcript logs does not erase these.
Voice-test and manual diagnostic commands can explicitly write WAV files.

The project's Git ignore rules exclude credentials, logs and local media.
Review what you attach to bug reports and what you add to Git, especially when
overriding ignore rules. Model weights and generated runtime profiles should
not be committed or bundled with release artifacts.
