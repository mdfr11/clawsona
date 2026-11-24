import unicodedata
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(char).startswith("C") for char in value):
        raise ValueError("Имя не должно содержать управляющие символы")
    value = " ".join(value.split())
    if not 2 <= len(value) <= 40 or not any(char.isalpha() for char in value):
        raise ValueError("Имя должно содержать буквы и занимать от 2 до 40 символов")
    return value


def default_models_dir() -> Path:
    current = Path.home() / ".local/share/clawsona/models"
    legacy = Path.home() / ".local/share/lyutik/models"
    return legacy if not current.exists() and legacy.is_dir() else current


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    llm_provider: Literal["deepseek", "openclaw", "ollama", "custom"] = "openclaw"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str = Field("", repr=False)
    deepseek_api_key: str = Field("", repr=False)
    deepseek_thinking: bool = False
    openclaw_url: str = "http://127.0.0.1:18791/v1"
    openclaw_gateway_token: str = Field("", repr=False)
    openclaw_agent: str = Field("clawsona", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    openclaw_profile: str = Field("clawsona", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    clawsona_tools_token: str = Field(
        "",
        repr=False,
        validation_alias=AliasChoices("CLAWSONA_TOOLS_TOKEN", "LYUTIK_TOOLS_TOKEN"),
    )
    clawsona_tools_port: int = Field(
        18792,
        ge=1024,
        le=65535,
        validation_alias=AliasChoices("CLAWSONA_TOOLS_PORT", "LYUTIK_TOOLS_PORT"),
    )
    yandex_music_token: str = Field("", repr=False)
    music_enabled: bool = False
    music_volume: int = Field(50, ge=0, le=100)
    music_pause_during_speech: bool = True
    music_speech_mode: Literal["duck", "pause"] = "duck"
    music_duck_ratio: float = Field(0.2, ge=0, le=1)
    music_fade_duration_ms: int = Field(200, ge=0, le=2000)
    music_auto_next: bool = True
    llm_timeout_s: float = Field(120, gt=0)
    llm_max_tokens: int = Field(384, ge=32, le=4096)
    max_history_turns: int = Field(12, ge=1, le=100)

    stt_provider: Literal["local", "deepgram"] = "local"
    tts_provider: Literal["piper", "elevenlabs", "edge"] = "piper"
    elevenlabs_api_key: str = Field("", repr=False)
    elevenlabs_voice_id: str = Field("", pattern=r"^[A-Za-z0-9_-]*$")
    elevenlabs_model: str = Field(
        "eleven_v4_turbo", pattern=r"^eleven_v[34](?:_[a-z0-9_]+)?$"
    )
    elevenlabs_timeout_s: float = Field(45, gt=0, le=300)
    elevenlabs_fallback: bool = True
    deepgram_api_key: str = Field("", repr=False)
    tts_voice: str = "ru-RU-DmitryNeural"
    models_dir: Path = Field(default_factory=default_models_dir)
    whisper_model: str = "small"
    whisper_cpu_threads: int = Field(4, ge=1)
    whisper_beam_size: int = Field(5, ge=1, le=5)
    stt_hotwords: str = ""
    stt_language: Literal["auto", "ru", "en"] = "auto"
    stt_min_logprob: float = Field(-1.0, ge=-5, le=0)
    stt_max_no_speech_prob: float = Field(0.5, gt=0, lt=1)
    stt_max_compression_ratio: float = Field(2.4, gt=1, le=10)
    piper_voice: str = Field(
        "ru_RU-denis-medium",
        pattern=r"^[a-z]{2,3}_[A-Z]{2}-[A-Za-z0-9_]+-(?:x_low|low|medium|high)$",
    )
    piper_english_voice: str = Field(
        "en_US-ljspeech-medium",
        pattern=r"^en_[A-Z]{2}-[A-Za-z0-9_]+-(?:x_low|low|medium|high)$",
    )

    activation: Literal["name", "continuous"] = "name"
    assistant_name: str = Field(
        "Ассистент",
        validation_alias=AliasChoices("ASSISTANT_NAME", "WAKE_WORD", "wake_word"),
    )
    assistant_aliases: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Every speech component consumes the same PCM format.
    sample_rate: Literal[16000] = 16000
    input_device: int | str | None = None
    output_device: int | str | None = None
    vad_threshold: float = Field(0.6, gt=0, lt=1)
    vad_silence_duration_ms: int = Field(1800, ge=60, le=5000)
    vad_min_speech_ms: int = Field(180, ge=30, le=1000)
    vad_pre_roll_ms: int = Field(1000, ge=200, le=3000)
    conversation_timeout_s: float = Field(120, gt=0)
    follow_up_without_name: bool = True
    barge_in_enabled: bool = True
    barge_in_mode: Literal["name", "speech"] = "name"
    barge_in_min_speech_ms: int = Field(300, ge=100, le=1000)
    barge_in_check_interval_ms: int = Field(1200, ge=500, le=3000)
    max_utterance_s: float = Field(45, ge=1, le=300)
    audio_read_timeout_s: float = Field(3, gt=0)
    error_retry_delay_s: float = Field(2, gt=0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_file: Path | None = Path("logs/clawsona.log")
    log_transcripts: bool = False

    @field_validator("assistant_name")
    @classmethod
    def validate_name(cls, value):
        return normalize_name(value)

    @field_validator("assistant_aliases", mode="before")
    @classmethod
    def parse_aliases(cls, value):
        if isinstance(value, str):
            value = value.split(",") if value.strip() else []
        if not isinstance(value, (list, tuple)):
            raise ValueError("Варианты имени задаются списком или через запятую")
        return list(dict.fromkeys(normalize_name(item) for item in value))

    @property
    def wake_word(self) -> str:
        """Legacy Python accessor; new configurations use ASSISTANT_NAME."""
        return self.assistant_name

    @field_validator("log_file", mode="before")
    @classmethod
    def parse_log_file(cls, value):
        return Path(value).expanduser().resolve() if value else None

    @field_validator("models_dir", mode="after")
    @classmethod
    def expand_path(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("input_device", "output_device", mode="before")
    @classmethod
    def parse_device(cls, value):
        if value == "":
            return None
        if isinstance(value, str) and value.isdecimal():
            return int(value)
        return value

    @property
    def chat_url(self) -> str:
        if self.llm_provider == "openclaw":
            return self.openclaw_url.rstrip("/")
        if self.llm_base_url:
            return self.llm_base_url.rstrip("/")
        return {
            "deepseek": "https://api.deepseek.com",
            "openclaw": self.openclaw_url.rstrip("/"),
            "ollama": "http://localhost:11434/v1",
            "custom": "http://localhost:8080/v1",
        }[self.llm_provider]

    @property
    def chat_model(self) -> str:
        return (
            self.llm_model
            or {
                "deepseek": "deepseek-flash",
                "openclaw": f"openclaw/{self.openclaw_agent}",
                "ollama": "qwen2.5:3b",
                "custom": "local-model",
            }[self.llm_provider]
        )

    @property
    def chat_key(self) -> str:
        return self.llm_api_key or {
            "deepseek": self.deepseek_api_key,
            "openclaw": self.openclaw_gateway_token,
        }.get(self.llm_provider, "")

    @property
    def piper_model_path(self) -> Path:
        return self.models_dir / "piper" / f"{self.piper_voice}.onnx"

    @property
    def piper_english_model_path(self) -> Path:
        return self.models_dir / "piper" / f"{self.piper_english_voice}.onnx"

    @property
    def whisper_model_path(self) -> Path:
        return self.models_dir / "whisper" / self.whisper_model
