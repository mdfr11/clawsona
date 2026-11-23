import pytest
from pydantic import ValidationError

from clawsona.chat import create_chat_client
from clawsona.config import Settings
from clawsona.openclaw_client import OpenClawClient


def test_settings_repr_excludes_credentials():
    credentials = {
        name: f"private-value-{index}"
        for index, name in enumerate(
            (
                "llm_api_key",
                "deepseek_api_key",
                "openclaw_gateway_token",
                "clawsona_tools_token",
                "yandex_music_token",
                "elevenlabs_api_key",
                "deepgram_api_key",
            )
        )
    }
    config = Settings(_env_file=None, **credentials)
    assert all(value not in repr(config) for value in credentials.values())


def test_local_config_requires_no_cloud_speech_keys(monkeypatch):
    for name in (
        "DEEPSEEK_API_KEY",
        "DEEPGRAM_API_KEY",
        "LLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    config = Settings(_env_file=None, llm_provider="ollama")
    assert config.stt_provider == "local"
    assert config.tts_provider == "piper"
    assert config.follow_up_without_name is True
    assert config.conversation_timeout_s == 120
    assert config.chat_url == "http://localhost:11434/v1"
    assert create_chat_client(config).model == "qwen2.5:3b"


def test_default_agent_is_openclaw():
    config = Settings(_env_file=None, openclaw_gateway_token="gateway-test")
    assert config.llm_provider == "openclaw"
    client = create_chat_client(config)
    assert isinstance(client, OpenClawClient)
    assert client.base_url == config.openclaw_url
    assert client.model == f"openclaw/{config.openclaw_agent}"


def test_only_selected_provider_needs_key():
    config = Settings(
        _env_file=None, llm_provider="deepseek", deepseek_api_key="", llm_api_key=""
    )
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        create_chat_client(config)
    config.deepseek_api_key = "test"
    create_chat_client(config)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sample_rate": 8000},
        {"llm_provider": "removed-agent"},
        {"wake_word": ""},
        {"max_utterance_s": 0},
        {"vad_threshold": 5},
        {"max_history_turns": 0},
        {"piper_voice": "../../other"},
    ],
)
def test_invalid_settings_are_rejected(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_paths_devices_and_url(tmp_path):
    config = Settings(
        _env_file=None,
        llm_provider="custom",
        models_dir=tmp_path,
        input_device="2",
        output_device="",
        llm_base_url="http://localhost:9000/v1/",
    )
    assert config.input_device == 2
    assert config.output_device is None
    assert config.chat_url == "http://localhost:9000/v1"
    assert config.piper_model_path == tmp_path / "piper/ru_RU-denis-medium.onnx"
    assert Settings(_env_file=None, log_file="").log_file is None


def test_custom_name_and_csv_aliases_can_be_set_in_environment(monkeypatch):
    monkeypatch.setenv("ASSISTANT_NAME", "  Жан   Люк  ")
    monkeypatch.setenv("ASSISTANT_ALIASES", "Jean Luc, Captain")
    monkeypatch.setenv("WAKE_WORD", "старое имя")
    config = Settings(_env_file=None)
    assert config.assistant_name == "Жан Люк"
    assert config.wake_word == config.assistant_name
    assert config.assistant_aliases == ["Jean Luc", "Captain"]


def test_old_env_name_is_supported_and_explicit_name_wins(tmp_path):
    path = tmp_path / ".env"
    path.write_text("WAKE_WORD=Лютик\n")
    assert Settings(_env_file=path).assistant_name == "Лютик"
    assert Settings(_env_file=path, assistant_name="Мира").assistant_name == "Мира"
    assert Settings(_env_file=None, wake_word="Атлас").assistant_name == "Атлас"


@pytest.mark.parametrize(
    "values",
    [
        {"assistant_name": "  "},
        {"assistant_name": "А\nБ"},
        {"assistant_name": "123"},
        {"assistant_aliases": [""]},
        {"assistant_aliases": "Mira,\nLyutik"},
    ],
)
def test_invalid_identity_is_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
