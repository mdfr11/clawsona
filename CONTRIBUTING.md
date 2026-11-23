# Contributing to ClawSona

Bug reports, documentation fixes and focused pull requests are welcome.
For a substantial change, open an issue first to discuss the behavior and scope.
Release preparation is documented in [RELEASING](docs/RELEASING.md).

## Local setup

Install Python 3.11–3.13 and uv. Linux needs `libportaudio2` for sounddevice;
on macOS use `brew install portaudio` if required by your installation.

```bash
uv sync --frozen --all-extras
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
node --check openclaw/clawsona-tools/index.js
uv build
uv run python scripts/check_distribution.py dist
```

Node.js is used for the plugin syntax check. Use the Node.js version required
by your OpenClaw release for live integration tests. Automated tests do not
require OpenClaw, microphones, downloaded models or paid service credentials.
After testing optional integrations, `uv sync --frozen` restores the base setup.

## Making changes

- Keep local speech processing and optional cloud integrations separable.
- Read [architecture](docs/architecture.md) for the voice pipeline and plugin boundary.
- Read configuration through `Settings`; keep `.env.example` and documentation
  current when adding a setting. Never hardcode a user's name, city or account.
- Keep tools bounded and validate parameters. Do not introduce shell execution
  or enable additional agent permissions as part of an unrelated change.
- Add focused regression tests for behavior changes. Use mocks/local HTTP
  servers for external services; keep paid calls and model downloads opt-in.
- Keep the lockfile current with `uv lock` when dependencies change.
- Explain the resulting behavior and validation in your pull request.

For manual checks, copy `.env.example` to your private `.env`, prepare models,
and use the commands in the README. A configured `OPENCLAW_PROFILE` belongs to
ClawSona: `openclaw-setup` rewrites its generated configuration and workspace.

## Reporting bugs

Include OS/architecture, Python/OpenClaw versions, relevant non-secret settings,
steps to reproduce and the expected/actual behavior. Timing events can help
identify latency without sharing conversation text. Sanitize logs before
attaching them; do not upload `.env`, account tokens, session histories or
recordings of other people. Report security issues through [SECURITY.md](SECURITY.md).

## License

By submitting a contribution, you agree to license it under the project's
[GPL-3.0-or-later license](LICENSE). Dependencies and model weights retain their
own licenses; see [third-party notices](docs/THIRD_PARTY_NOTICES.md).
