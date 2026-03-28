"""Shared model download utility with hf-mirror fallback.

Automatically tries hf-mirror.com first (for China users), then falls back
to the official HuggingFace Hub if the mirror fails.

Usage:
    from src.utils.model_download import download_model_once
    download_model_once("BAAI/bge-m3")
    download_model_once("jefferyluo/bert-chinese-emotion")
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HF_MIRROR = "https://hf-mirror.com"
HF_OFFICIAL = "https://huggingface.co"

# Models used by xinyi
XINYI_MODELS = [
    "BAAI/bge-m3",
    "Johnson8187/Chinese-Emotion-Small",
    "BAAI/bge-reranker-base",
]


def _hf_cache_dir() -> Path:
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def _st_cache_dir(model_name: str) -> Path:
    safe = model_name.replace("/", "--")
    return Path.home() / ".cache" / "torch" / "sentence_transformers" / safe


def is_model_cached(model_name: str) -> bool:
    """Check if a HuggingFace model is already in the local cache."""
    safe = model_name.replace("/", "--")
    hf_dir = _hf_cache_dir() / f"models--{safe}"
    if _has_required_artifacts(hf_dir):
        return True
    if _has_required_artifacts(_st_cache_dir(model_name)):
        return True
    return False


def _can_connect(host: str, port: int = 443, timeout: float = 3.0) -> bool:
    """Quick connectivity check (no HTTP overhead)."""
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False


def _is_china_network() -> bool:
    """Heuristic: if HuggingFace is unreachable but mirror is, assume China network."""
    hf_reachable = _can_connect("huggingface.co")
    mirror_reachable = _can_connect("hf-mirror.com")
    if not hf_reachable and mirror_reachable:
        return True
    return False


def _resolve_endpoint(model_name: str) -> str:
    """Choose the best HF endpoint based on network conditions.

    Priority:
    1. User-set HF_ENDPOINT env var (explicit override)
    2. hf-mirror.com if in China network
    3. Official HuggingFace Hub
    """
    if os.environ.get("HF_ENDPOINT"):
        return os.environ["HF_ENDPOINT"]

    if _is_china_network():
        logger.info("检测到国内网络环境，将优先使用镜像站 hf-mirror.com 下载模型")
        return HF_MIRROR

    return HF_OFFICIAL


def download_model_once(
    model_name: str,
    extra_msg: str = "",
) -> bool:
    """Download a HuggingFace model with mirror fallback.

    Tries the resolved endpoint first. If it fails (timeout, HTTP error),
    automatically falls back to the official HuggingFace Hub.

    Args:
        model_name: HuggingFace model ID (e.g. "BAAI/bge-m3")
        extra_msg: Extra suffix for the log message (e.g. "(可选)" for optional models)

    Returns:
        True if download succeeded, False if all endpoints failed.
    """
    if is_model_cached(model_name):
        return True

    resolved = _resolve_endpoint(model_name)
    endpoints_to_try = [resolved]
    if resolved != HF_OFFICIAL:
        endpoints_to_try.append(HF_OFFICIAL)

    last_error: Optional[Exception] = None
    for endpoint in endpoints_to_try:
        is_fallback = endpoint == HF_OFFICIAL
        prefix = "（镜像失效，切换到官方源）" if is_fallback else ""
        logger.info(f"{prefix}正在下载模型 %s %s …", model_name, extra_msg)

        saved = os.environ.pop("HF_HUB_OFFLINE", None)
        saved_tf = os.environ.pop("TRANSFORMERS_OFFLINE", None)
        saved_endpoint = os.environ.get("HF_ENDPOINT")
        saved_base_url = os.environ.get("HUGGINGFACE_HUB_BASE_URL")
        os.environ["HF_ENDPOINT"] = endpoint
        os.environ["HUGGINGFACE_HUB_BASE_URL"] = endpoint

        try:
            local_path = _download_snapshot(model_name, endpoint)
            if _load_model(local_path):
                logger.info("模型 %s 下载完成（来源: %s）", model_name, endpoint)
                return True
        except Exception as e:
            last_error = e
            logger.warning(
                "从 %s 下载模型 %s 失败: %s，%s",
                endpoint,
                model_name,
                e,
                "将尝试其他来源" if endpoint != HF_OFFICIAL else "下载失败",
            )
        finally:
            os.environ.pop("HF_ENDPOINT", None)
            os.environ.pop("HUGGINGFACE_HUB_BASE_URL", None)
            if saved_endpoint is not None:
                os.environ["HF_ENDPOINT"] = saved_endpoint
            if saved_base_url is not None:
                os.environ["HUGGINGFACE_HUB_BASE_URL"] = saved_base_url
            if saved is not None:
                os.environ["HF_HUB_OFFLINE"] = saved
            elif "HF_HUB_OFFLINE" in os.environ:
                os.environ.pop("HF_HUB_OFFLINE", None)
            if saved_tf is not None:
                os.environ["TRANSFORMERS_OFFLINE"] = saved_tf
            elif "TRANSFORMERS_OFFLINE" in os.environ:
                os.environ.pop("TRANSFORMERS_OFFLINE", None)

    logger.error("模型 %s 所有来源均下载失败: %s", model_name, last_error)
    return False


def _load_model(model_name: str) -> bool:
    """Load the model into the cache by importing it."""
    from sentence_transformers import SentenceTransformer

    try:
        SentenceTransformer(model_name, device="cpu")
        return True
    except ImportError:
        pass

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    try:
        AutoTokenizer.from_pretrained(model_name)
        AutoModelForSequenceClassification.from_pretrained(model_name)
        return True
    except ImportError:
        pass

    return False


def _download_snapshot(model_name: str, endpoint: str) -> str:
    """Download repo snapshot through a specific endpoint and return local path."""
    from huggingface_hub import snapshot_download

    return snapshot_download(
        repo_id=model_name,
        endpoint=endpoint,
        resume_download=True,
    )


def resolve_local_model_path(model_name: str) -> str:
    """Return a strictly local path for a cached model.

    This avoids libraries silently reaching out to huggingface.co during
    warmup/load even when the model was already downloaded through a mirror.
    """
    from huggingface_hub import snapshot_download

    try:
        return snapshot_download(
            repo_id=model_name,
            local_files_only=True,
        )
    except Exception:
        st_dir = _st_cache_dir(model_name)
        if _has_required_artifacts(st_dir):
            return str(st_dir)
        return model_name


def _has_required_artifacts(root: Path) -> bool:
    """Detect whether a cache directory contains a usable model snapshot."""
    if not root.exists():
        return False
    required_names = {
        "modules.json",
        "config.json",
        "tokenizer_config.json",
        "model.safetensors",
        "pytorch_model.bin",
    }
    try:
        return any(path.name in required_names for path in root.rglob("*") if path.is_file())
    except OSError:
        return False


def preload_all_models(verbose: bool = True) -> dict[str, bool]:
    """Pre-download all xinyi models with mirror fallback.

    Call this once on first boot (e.g. from app startup or onboarding)
    to ensure all models are available before training starts.

    Returns:
        A dict mapping model_name -> success (bool).
    """
    results = {}
    for model in XINYI_MODELS:
        extra = "(可选)" if model == "BAAI/bge-reranker-base" else ""
        if verbose:
            logger.info("检查模型: %s %s …", model, extra)
        results[model] = download_model_once(model, extra)
    return results
