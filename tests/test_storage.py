from pathlib import Path

from clawsona.config import Settings
from clawsona.openclaw_setup import child_env
from clawsona.yandex_auth import token_path


def test_configured_tools_profile_and_assistant_reach_gateway(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "CLAWSONA_TOOLS_TOKEN=fixture-secret\nCLAWSONA_TOOLS_PORT=18801\n"
        "OPENCLAW_PROFILE=training\nOPENCLAW_AGENT=training\nASSISTANT_NAME=Мира\n"
    )
    config = Settings(_env_file=env)
    assert config.clawsona_tools_token == "fixture-secret"
    assert config.clawsona_tools_port == 18801
    assert config.openclaw_profile == config.openclaw_agent == "training"
    assert config.assistant_name == "Мира"
    assert child_env(config)["CLAWSONA_TOOLS_TOKEN"] == "fixture-secret"


def test_models_and_music_auth_use_clawsona_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    root = tmp_path / ".local/share/clawsona"
    # Paths are stable both before and after the first download/login.
    for create in (False, True):
        if create:
            (root / "models").mkdir(parents=True)
            (root / "yandex-auth.json").write_text("{}")
        assert Settings(_env_file=None).models_dir == root / "models"
        assert token_path() == root / "yandex-auth.json"
