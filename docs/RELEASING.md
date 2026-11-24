# Preparing a source release

## Local checks

```bash
uv sync --frozen --all-extras
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
node --check openclaw/clawsona-tools/index.js
uv build
uv run python scripts/check_distribution.py dist
```

The distribution checker verifies the plugin, CLI entrypoint, license, source files
and exclusion of environment files, runtime state, models and recordings. Review
the actual source changes too; filename checks do not replace secret scanning.
For a new version, keep `pyproject.toml` and the plugin's `package.json` version
in sync, update `uv.lock`, and build into an empty output directory. Do not
publish files from previous builds by accident.

Physical audio, recognition quality and live provider compatibility need separate
integration checks. State the tested OpenClaw version and outstanding limitations
in release notes. GitHub Actions is configured for tests and artifact building;
it does not publish packages or deploy anything automatically.

## Repository and project page

The public repository is [mdfr11/clawsona](https://github.com/mdfr11/clawsona).
Publish only reviewed source commits. API keys, generated OpenClaw profiles,
accounts, logs and model weights are private runtime state; the intentional
public voice samples are documented in `website/media/README.md`.

GitHub Pages uses the manually triggered **Project page** workflow. Select
**Settings → Pages → Source: GitHub Actions** before its first run. The workflow
builds and validates the source archive, renders the static page, and publishes
it with the repository URL populated automatically. The site does not need
API keys, analytics, external fonts or a model connection.

For local preview, see [website/README.md](../website/README.md). The source
archive can also be unpacked independently of Git history. Check dependencies,
provider terms and model licenses before redistributing a complete installation;
see [third-party notices](THIRD_PARTY_NOTICES.md).
