"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 100% Free BigQuery Sandbox (1 TiB/month, no billing card)
    gcp_project_id: str = Field(default="", description="GCP Sandbox Project ID")
    bigquery_dataset: str = Field(
        default="bigquery-public-data.thelook_ecommerce",
        description="Target BigQuery public dataset (project.dataset)",
    )
    max_bytes_per_query: int = Field(
        default=1_073_741_824,  # 1 GB safety cap
        ge=1_048_576,
        description="Maximum bytes allowed per query during dry-run check",
    )

    # 100% Free Local Ollama LLM
    ollama_base_url: str = Field(default="http://localhost:11434")
    llm_model: str = Field(default="qwen2.5-coder:7b")
    llm_timeout_seconds: int = Field(default=60, ge=5)

    # Local Persistence
    chroma_persist_dir: Path = Field(default=Path("storage/chroma_db"))
    sqlite_db_path: Path = Field(default=Path("storage/querylens.db"))

    # Agent & Cache Controls
    max_repair_retries: int = Field(default=3, ge=0, le=5)
    cache_ttl_seconds: int = Field(default=3600, ge=0)
    log_level: str = Field(default="INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()