from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PhysioPlus Assistant"
    app_version: str = "0.1.0"
    environment: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    enable_debug_endpoints: bool = True

    embedding_model_name: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    knowledge_dir: Path = BASE_DIR / "knowledge"
    index_dir: Path = BASE_DIR / "index"

    chunk_max_words: int = Field(default=60, ge=20, le=120)
    chunk_overlap_sentences: int = Field(default=1, ge=0, le=3)
    top_k: int = Field(default=5, ge=1, le=20)
    evidence_threshold: float = Field(default=0.35, ge=0.0, le=1.0)

    groq_api_key: str = ""
    groq_api_keys: str = ""
    groq_model: str = "qwen/qwen3.8-27b"
    groq_reasoning_effort: str = "none"
    llm_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    llm_connect_timeout_seconds: float = Field(default=3.0, ge=0.5, le=30.0)
    force_ipv4: bool = True
    llm_rate_limit_max_wait_seconds: float = Field(default=3.0, ge=0.0, le=60.0)
    llm_min_interval_seconds: float = Field(default=0.0, ge=0.0, le=120.0)

    physio_api_base_url: str = "http://localhost:3000/api/v1"
    physio_api_timeout_seconds: float = Field(default=8.0, ge=1.0, le=60.0)
    data_tools_enabled: bool = True
    actions_enabled: bool = True
    patient_actions_enabled: bool = True
    assistant_signing_secret: str = ""
    proposal_ttl_seconds: int = Field(default=300, ge=60, le=1800)
    default_appointment_minutes: int = Field(default=60, ge=15, le=240)
    tool_max_items: int = Field(default=15, ge=1, le=100)
    timezone: str = "America/Sao_Paulo"

    prompt_version: str = "v3"
    verify_answers: bool = False
    query_analysis_enabled: bool = True
    generation_max_tokens: int = Field(default=700, ge=100, le=2000)
    history_max_turns: int = Field(default=6, ge=0, le=20)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def groq_key_list(self) -> list[str]:
        keys: list[str] = []

        for raw in [self.groq_api_keys, self.groq_api_key]:
            for key in raw.split(","):
                key = key.strip()
                if key and key not in keys:
                    keys.append(key)

        return keys

    @property
    def manifest_path(self) -> Path:
        return self.knowledge_dir / "manifest.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()