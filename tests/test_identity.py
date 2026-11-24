import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from dotenv import dotenv_values

from clawsona.config import Settings
from clawsona.openclaw_setup import (
    archive_default_workspace_templates,
    prepare_openclaw,
)
from clawsona.prompts import AGENT_SYSTEM_PROMPT, build_system_prompt


@pytest.mark.parametrize("name", ["Мира", "Atlas", "Жан Люк"])
@pytest.mark.parametrize("agent", [False, True])
def test_model_identity_is_configured_in_all_modes(name, agent):
    prompt = build_system_prompt(name, agent=agent)
    assert json.dumps(name, ensure_ascii=False) in prompt
    assert "только по твоему имени" in prompt
    assert ("clawsona_weather" in prompt) is agent
    # The stored workspace instructions are name-neutral. A changed config
    # takes effect in the next request without an old SOUL overriding it.
    assert "Твоё имя:" not in AGENT_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_openclaw_setup_preserves_configured_name_and_activation(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "profile"
    monkeypatch.setattr("clawsona.openclaw_setup.profile_dir", lambda config: root)
    monkeypatch.setattr(
        "clawsona.openclaw_setup.command", lambda config: ["fixture-gateway"]
    )
    process = AsyncMock()
    process.wait.return_value = 0
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    env = tmp_path / ".env"
    env.write_text("ACTIVATION=continuous\nASSISTANT_NAME=Мира\nOTHER_SETTING=keep\n")
    config = Settings(
        _env_file=env,
        assistant_aliases=["Mira"],
        deepseek_api_key="fixture-key",
        llm_max_tokens=512,
    )
    await prepare_openclaw(config)
    saved = dotenv_values(env)
    assert saved["ASSISTANT_NAME"] == "Мира"
    assert saved["ASSISTANT_ALIASES"] == "Mira"
    assert saved["ACTIVATION"] == "continuous"
    assert saved["OTHER_SETTING"] == "keep"
    assert (
        json.loads((root / "openclaw.json").read_text())["agents"]["list"][0]["name"]
        == "Мира"
    )
    assert (root / "workspace/SOUL.md").read_text() == AGENT_SYSTEM_PROMPT
    prepared = json.loads((root / "openclaw.json").read_text())
    assert prepared["agents"]["list"][0]["skills"] == []
    assert prepared["agents"]["defaults"]["skipBootstrap"] is True
    assert (
        prepared["agents"]["defaults"]["models"]["deepseek/deepseek-flash"]["params"][
            "maxTokens"
        ]
        == 512
    )


def test_context_cleanup_only_archives_exact_unmodified_placeholders(tmp_path):
    workspace, templates = tmp_path / "workspace", tmp_path / "templates"
    workspace.mkdir()
    templates.mkdir()
    for name in ("USER.md", "TOOLS.md", "BOOTSTRAP.md", "SOUL.md"):
        (templates / name).write_text(
            "---\nsummary: fixture\n---\n\nDefault placeholder\n"
        )
        (workspace / name).write_text("Default placeholder\n")
    (workspace / "USER.md").write_text("My personalized instructions\n")
    assert archive_default_workspace_templates(workspace, templates) == [
        "TOOLS.md",
        "BOOTSTRAP.md",
    ]
    assert (workspace / "USER.md").read_text() == "My personalized instructions\n"
    assert (workspace / "SOUL.md").read_text() == "Default placeholder\n"
    assert not (workspace / "BOOTSTRAP.md").exists()
    assert (
        workspace / ".clawsona-template-backup/BOOTSTRAP.md"
    ).read_text() == "Default placeholder\n"
    assert archive_default_workspace_templates(workspace, templates) == []


def test_context_cleanup_never_overwrites_an_existing_backup(tmp_path):
    workspace, templates = tmp_path / "workspace", tmp_path / "templates"
    (workspace / ".clawsona-template-backup").mkdir(parents=True)
    templates.mkdir()
    (workspace / "TOOLS.md").write_text("Default")
    (templates / "TOOLS.md").write_text("Default")
    (workspace / ".clawsona-template-backup/TOOLS.md").write_text("Previous backup")
    assert archive_default_workspace_templates(workspace, templates) == []
    assert (workspace / "TOOLS.md").read_text() == "Default"
    assert (
        workspace / ".clawsona-template-backup/TOOLS.md"
    ).read_text() == "Previous backup"
