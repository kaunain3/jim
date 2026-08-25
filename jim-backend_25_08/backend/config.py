"""App configuration. Override any of these with env vars, e.g.
JIM_LLM_BASE_URL=http://127.0.0.1:11434 (Ollama) before starting uvicorn.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_base_url: str = "http://127.0.0.1:8080"
    # Must match the exact model name your server expects. Ollama, for
    # example, 404s on anything that isn't a model you've actually pulled
    # (e.g. "llama3.1") — it won't accept a generic placeholder.
    llm_model: str = "local-model"
    library_dir: Path = Path("data/library")

    class Config:
        env_prefix = "JIM_"


settings = Settings()
settings.library_dir.mkdir(parents=True, exist_ok=True)
