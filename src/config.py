"""Pydantic-based typed configuration layer.

Replaces scattered yaml/dict config reads with a single,
type-safe, IDE-friendly config singleton.  Fully backward-compatible
with the existing `config["key"]` dict interface used throughout app.py.

Environment variables (${VAR:default}) are resolved before pydantic validation.
`.env` is auto-loaded via python-dotenv on first import.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Auto-load .env on first import
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed — rely on real environment


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _resolve_env_vars(obj):
    """Expand ${VAR:default} tokens recursively in a plain dict/list/str."""
    import re as _re

    def _sub(m):
        expr = m.group(1)
        if ":" in expr:
            var, default = expr.split(":", 1)
        else:
            var, default = expr, ""
        return os.environ.get(var, default)

    if isinstance(obj, str):
        return _re.sub(r"\$\{([^}]+)\}", _sub, obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def _default(*paths: str) -> Path:
    return _PROJECT_ROOT / "/".join(paths)


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class APIConfig(BaseModel):
    provider: Literal["openai"] = "openai"
    api_key: str = ""
    model: str = "gpt-4o"
    extraction_model: str = "gpt-4o"
    base_url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("headers", mode="before")
    @classmethod
    def _empty_headers(cls, v):
        if v is None:
            return {}
        return v


class EmbeddingConfig(BaseModel):
    model: str = "shibing624/text2vec-base-chinese"
    device: Literal["cpu", "cuda"] = "cpu"


class PathsConfig(BaseModel):
    raw_db_dir: Path = Path("data/raw")
    processed_dir: Path = Path("data/processed")
    chroma_dir: Path = Path("data/chroma_db")
    beliefs_file: Path = Path("data/beliefs.json")
    persona_file: Path = Path("data/persona_profile.yaml")
    emotion_file: Path = Path("data/emotion_profile.yaml")
    thinking_model_file: Path = Path("data/thinking_model.txt")
    task_results_file: Path = Path("data/task_results.json")
    cognitive_tasks_file: Path = Path("data/cognitive_tasks.json")

    @field_validator(
        "raw_db_dir", "processed_dir", "chroma_dir",
        "beliefs_file", "persona_file", "emotion_file",
        "thinking_model_file", "task_results_file", "cognitive_tasks_file",
        mode="before",
    )
    @classmethod
    def _coerce_path(cls, v):
        return Path(v) if v else Path(".")


class ChunkingConfig(BaseModel):
    max_turns: int = 15
    min_turns: int = 3
    time_gap_minutes: int = 30


class RetrievalConfig(BaseModel):
    top_k_vectors: int = 5
    top_k_beliefs: int = 3


class RerankConfig(BaseModel):
    enabled: bool = True
    provider: Literal["local", "cohere"] = "local"
    model: str = "BAAI/bge-reranker-base"
    cohere_api_key: str = ""
    device: Literal["cpu", "cuda"] = "cpu"
    top_k_raw: int = 20
    top_k_reranked: int = 5


class EmotionConfig(BaseModel):
    """Emotion tagging config (P2-6)."""
    enabled: bool = False
    provider: Literal["local", "llm"] = "local"
    model: str = "jefferyluo/bert-chinese-emotion"
    emotion_boost_weight: float = 1.5  # weight multiplier when emotion matches


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    dir: Path = Path("logs")
    rotation: str = "100 MB"
    retention: str = "30 days"


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    api: APIConfig = Field(default_factory=APIConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    emotion: EmotionConfig = Field(default_factory=EmotionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cold_start_description: str = ""

    # Environment toggles
    env: Literal["dev", "prod"] = Field(default="prod")

    @field_validator("env", mode="before")
    @classmethod
    def _resolve_env(cls, v):
        return os.environ.get("XINYI_ENV", v or "prod")

    # Dev mode auto-upgrades logging to DEBUG
    def effective_log_level(self) -> str:
        if self.env == "dev":
            return "DEBUG"
        return self.logging.level


# ---------------------------------------------------------------------------
# Singleton loader
# ---------------------------------------------------------------------------

_instance: AppConfig | None = None


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    """Load + validate config from YAML, resolving env vars first.

    Falls back gracefully: if the yaml key is missing, pydantic fills
    the default.  This means adding new fields never breaks old configs.
    """
    import yaml

    cfg_path = Path(config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"配置文件 {cfg_path} 不存在。"
            f" 请复制 config.default.yaml 为 config.yaml，或创建 config.yaml。"
        )

    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Expand ${VAR:default} tokens
    raw = _resolve_env_vars(raw)

    # Force env from env var (highest priority)
    raw["env"] = os.environ.get("XINYI_ENV", raw.get("env", "prod"))

    return AppConfig(**raw)


def get_config() -> AppConfig:
    """Return the cached singleton.  Lazy-loads on first call."""
    global _instance
    if _instance is None:
        _instance = load_config()
    return _instance


def reload_config(config_path: str | Path = "config.yaml") -> AppConfig:
    """Force-reload config from disk (useful after editing config.yaml)."""
    global _instance
    _instance = load_config(config_path)
    return _instance


# ---------------------------------------------------------------------------
# Backward-compatible dict accessor
# ---------------------------------------------------------------------------
#
# All code that currently reads config["api"]["key"] or config["embedding"]
# will keep working because AppConfig provides a __getitem__ interface via
# its .dict() output, and we expose a lightweight DictConfig wrapper below.
# ---------------------------------------------------------------------------

class DictConfig:
    """Thin wrapper that lets existing code use `cfg["api"]` syntax.

    Internally holds an AppConfig; changes are NOT persisted.
    For writes, use reload_config() after editing the yaml file.
    """

    def __init__(self, inner: AppConfig) -> None:
        self._inner = inner

    def __getitem__(self, key: str):
        # Map top-level keys to sub-models
        sub = getattr(self._inner, key, None)
        if sub is None:
            raise KeyError(f"config has no key '{key}'")
        if hasattr(sub, "model_dump"):
            return sub.model_dump()
        return sub

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    # Expose the typed accessor for new code
    @property
    def typed(self) -> AppConfig:
        return self._inner


def dict_config() -> DictConfig:
    """Backwards-compatible dict-style config accessor."""
    return DictConfig(get_config())
