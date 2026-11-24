import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from dotenv import dotenv_values

from clawsona.config import Settings
from clawsona.openclaw_setup import prepare_openclaw
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
        _env_file=env, assistant_aliases=["Mira"], deepseek_api_key="fixture-key"
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
