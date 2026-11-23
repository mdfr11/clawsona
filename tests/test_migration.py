from pathlib import Path

from clawsona.config import Settings
from clawsona.openclaw_setup import child_env
from clawsona.yandex_auth import token_path


def test_previous_env_keeps_tokens_ports_profile_and_assistant(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "LYUTIK_TOOLS_TOKEN=legacy-test-secret\nLYUTIK_TOOLS_PORT=18801\n"
        "OPENCLAW_PROFILE=lyutik\nOPENCLAW_AGENT=lyutik\nWAKE_WORD=Лютик\n"
    )
    config = Settings(_env_file=env)
    assert config.clawsona_tools_token == "legacy-test-secret"
    assert config.clawsona_tools_port == 18801
    assert config.openclaw_profile == config.openclaw_agent == "lyutik"
    assert config.assistant_name == "Лютик"
    assert child_env(config)["LYUTIK_TOOLS_TOKEN"] == "legacy-test-secret"
    assert child_env(config)["CLAWSONA_TOOLS_TOKEN"] == "legacy-test-secret"


def test_existing_models_and_music_auth_are_reused_until_new_locations_exist(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    legacy = tmp_path / ".local/share/lyutik"
    (legacy / "models").mkdir(parents=True)
    (legacy / "yandex-auth.json").write_text("{}")
    assert Settings(_env_file=None).models_dir == legacy / "models"
    assert token_path() == legacy / "yandex-auth.json"
    current = tmp_path / ".local/share/clawsona"
    (current / "models").mkdir(parents=True)
    (current / "yandex-auth.json").write_text("{}")
    assert Settings(_env_file=None).models_dir == current / "models"
    assert token_path() == current / "yandex-auth.json"
