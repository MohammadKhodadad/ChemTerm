"""Application configuration."""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHEMTERM_",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+psycopg://chemterm:chemterm_dev@127.0.0.1:5432/chemterm"
    )
    sql_echo: bool = False
    llm_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CHEMTERM_LLM_API_KEY", "OPENAI_API_KEY"),
    )
    llm_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CHEMTERM_LLM_MODEL", "OPENAI_MODEL"),
    )
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = Field(default=60, gt=0, le=600)
    embedding_model: str = "BAAI/bge-m3"
    embedding_model_version: str = "default"
    embedding_device: str | None = None
    concept_retrieval_top_k: int = Field(default=8, ge=1, le=50)


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""

    return Settings()
