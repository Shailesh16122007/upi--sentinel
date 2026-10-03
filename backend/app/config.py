"""Central configuration. Everything tunable lives here and is overridable via env vars."""
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class RiskThresholds(BaseModel):
    # Lower bound (inclusive) of each level on the 0-100 scale.
    medium: int = 30
    high: int = 60
    critical: int = 80


class DecisionPolicy(BaseModel):
    LOW: str = "ALLOW"
    MEDIUM: str = "VERIFY"
    HIGH: str = "WARN"
    CRITICAL: str = "BLOCK"
    # If true, a BLOCK can still be overridden by an explicit user confirmation
    # (the override is recorded as evidence). Banks may set this to false.
    allow_block_override: bool = True


class ScoreWeights(BaseModel):
    rule: float = 0.45
    model: float = 0.35
    network: float = 0.20


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_prefix="SENTINEL_", extra="ignore")

    app_name: str = "UPI Sentinel API"
    env: str = "dev"
    database_url: str = f"sqlite:///{BASE_DIR / 'sentinel.db'}"
    storage_dir: Path = BASE_DIR / "storage"

    # Comma-separated API keys accepted in the X-API-Key header.
    # Each partner (PSP app / bank) gets its own key. Demo key only for local use.
    api_keys: str = "demo-psp-key"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    max_upload_mb: int = 15
    max_audio_mb: int = 40
    max_files_per_case: int = 60

    # Speech-to-text (local). faster-whisper downloads the model on first use, then works offline.
    # Set SENTINEL_STT_ENGINE=none to disable; the app then shows "Audio transcription unavailable".
    stt_engine: str = "faster-whisper"
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    ocr_lang: str = "eng"
    # Minimum customer history rows before Isolation Forest is run.
    ml_min_history: int = 20

    # LLM (System 2 only). If unset, the investigator runs a deterministic rules engine
    # and labels its output engine="rules" — it never pretends to be an LLM.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"

    thresholds: RiskThresholds = RiskThresholds()
    policy: DecisionPolicy = DecisionPolicy()
    weights: ScoreWeights = ScoreWeights()

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}



@lru_cache
def get_settings() -> Settings:
    return Settings()
