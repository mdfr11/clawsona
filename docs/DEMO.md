# Recording a live ClawSona demo

The project page already includes real ElevenLabs voice samples. Its example
conversations are labeled illustrations. For a live microphone-to-speaker demo,
record the actual application; do not present scripted screen animations as
recognition or tool-performance evidence.

## A short recording outline

Aim for 30–45 seconds and use only public, non-personal content:

1. Launch the configured companion. Say its name and a request in one phrase:
   “Mira, can we practice English?” Let the real reply play.
2. Ask a short follow-up without repeating the name. Keep the thinking pause
   inside the sentence to show the endpoint behavior.
3. Ask a weather question with an explicit city. Let OpenClaw invoke the tool
   and return the real current result. Do not prefill or edit in a forecast.

Capture the speaker and the console timings, with transcript logging enabled
only for this public conversation. Never show `.env`, tokens, provider dashboards
or previous sessions. State the CPU, speech models, TTS backend and OpenClaw
version in the description. Preserve waiting time or label edits explicitly.

Upload the recording to the real public repository once it exists and link it
from the README. The built-in local voice samples remain useful for visitors
who want to hear the default voices before installing anything.
