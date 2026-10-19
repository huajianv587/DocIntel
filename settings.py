from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DocIntel Support Workbench"
    environment: str = "development"
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: str | None = None
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://localhost:8000"

    database_url: str = "postgresql+psycopg://docintel:docintel@localhost:5432/docintel"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "docintel_chunks"
    # A vector-only hit must clear this bar before it can become answer evidence.
    # Lexical hits are still fused normally, which keeps exact identifiers and
    # commands reliable while preventing unrelated low-score embeddings from
    # defeating abstention.
    retrieval_min_vector_score: float = Field(default=0.42, ge=0.0, le=1.0)

    s3_endpoint_url: str | None = None
    s3_region: str = "ap-southeast-1"
    s3_bucket: str = "docintel"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    jwt_secret: str = "local-development-secret-change-this-32-bytes-minimum"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    bootstrap_admin_email: str = "admin@docintel.io"
    bootstrap_admin_password: str = "change-me-now"

    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"
    deepseek_timeout_seconds: float = 45.0

    github_token: str | None = None
    github_repositories: str = "fastapi/fastapi,django/django,kubernetes/website"
    github_sync_interval_minutes: int = 360
    github_max_documents: int = 200
    github_max_issues: int = 100
    github_max_comments: int = 100

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    sandbox_enabled: bool = True
    sandbox_execution_mode: str = "docker"
    sandbox_queue: str = "sandbox"
    sandbox_task_timeout_seconds: int = 30
    sandbox_image: str = "python:3.12-slim"
    sandbox_timeout_seconds: int = 15
    sandbox_memory_mb: int = 256
    sandbox_output_chars: int = 12000

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def github_repository_list(self) -> list[str]:
        return [item.strip() for item in self.github_repositories.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

