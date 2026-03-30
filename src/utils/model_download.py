"""Shared model download utility with hf-mirror fallback.

Automatically tries hf-mirror.com first (for China users), then falls back
to the official HuggingFace Hub if the mirror fails.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

HF_MIRROR = "https://hf-mirror.com"
HF_OFFICIAL = "https://huggingface.co"


def _hf_cache_dir() -> Path:
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def _st_cache_dir(model_name: str) -> Path:
    safe = model_name.replace("/", "--")
    return Path.home() / ".cache" / "torch" / "sentence_transformers" / safe


def _can_connect(host: str, port: int = 443, timeout: float = 3.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False


def _is_china_network() -> bool:
    hf_reachable = _can_connect("huggingface.co")
    mirror_reachable = _can_connect("hf-mirror.com")
    if not hf_reachable and mirror_reachable:
        return True
    return False


def _resolve_endpoint(model_name: str) -> str:
    if os.environ.get("HF_ENDPOINT"):
        return os.environ["HF_ENDPOINT"]
    if _is_china_network():
        logger.info("检测到国内网络环境，将优先使用镜像站 hf-mirror.com 下载模型")
        return HF_MIRROR
    return HF_OFFICIAL


def is_model_cached(model_name: str) -> bool:
    safe = model_name.replace("/", "--")
    hf_dir = _hf_cache_dir() / f"models--{safe}"
    if _has_required_artifacts(hf_dir):
        return True
    if _has_required_artifacts(_st_cache_dir(model_name)):
        return True
    return False


def _has_required_artifacts(root: Path) -> bool:
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


def _clear_incomplete_download(model_name: str):
    """Remove any partial-download artifacts before retrying."""
    safe = model_name.replace("/", "--")
    hf_dir = _hf_cache_dir() / f"models--{safe}"
    incomplete = hf_dir.with_name(hf_dir.name + ".incomplete")
    for partial in [hf_dir, incomplete]:
        if partial.exists():
            try:
                shutil.rmtree(partial)
                logger.info("已清理部分下载: %s", partial)
            except OSError:
                pass


def _snapshot_download(model_name: str, endpoint: str) -> str:
    from huggingface_hub import snapshot_download
    return snapshot_download(
        repo_id=model_name,
        endpoint=endpoint,
        resume_download=True,
    )


def download_model_once(model_name: str, extra_msg: str = "") -> bool:
    """Download a single model with mirror fallback.

    Returns True if succeeded, False if all sources failed.
    """
    if is_model_cached(model_name):
        return True

    resolved = _resolve_endpoint(model_name)
    endpoints = [resolved]
    if resolved != HF_OFFICIAL:
        endpoints.append(HF_OFFICIAL)

    last_error: Optional[Exception] = None
    for endpoint in endpoints:
        is_fallback = endpoint == HF_OFFICIAL
        prefix = "（镜像失效，切换到官方源）" if is_fallback else ""
        logger.info(f"{prefix}正在下载模型 %s %s …", model_name, extra_msg)

        saved_offline = os.environ.pop("HF_HUB_OFFLINE", None)
        saved_tf = os.environ.pop("TRANSFORMERS_OFFLINE", None)
        saved_endpoint = os.environ.get("HF_ENDPOINT")
        saved_base = os.environ.get("HUGGINGFACE_HUB_BASE_URL")
        os.environ["HF_ENDPOINT"] = endpoint
        os.environ["HUGGINGFACE_HUB_BASE_URL"] = endpoint

        try:
            _snapshot_download(model_name, endpoint)
            logger.info("模型 %s 下载完成（来源: %s）", model_name, endpoint)
            return True
        except Exception as e:
            last_error = e
            logger.warning(
                "从 %s 下载 %s 失败: %s", endpoint, model_name, e,
            )
        finally:
            os.environ.pop("HF_ENDPOINT", None)
            os.environ.pop("HUGGINGFACE_HUB_BASE_URL", None)
            if saved_endpoint is not None:
                os.environ["HF_ENDPOINT"] = saved_endpoint
            if saved_base is not None:
                os.environ["HUGGINGFACE_HUB_BASE_URL"] = saved_base
            if saved_offline is not None:
                os.environ["HF_HUB_OFFLINE"] = saved_offline
            elif "HF_HUB_OFFLINE" in os.environ:
                os.environ.pop("HF_HUB_OFFLINE", None)
            if saved_tf is not None:
                os.environ["TRANSFORMERS_OFFLINE"] = saved_tf
            elif "TRANSFORMERS_OFFLINE" in os.environ:
                os.environ.pop("TRANSFORMERS_OFFLINE", None)

    logger.error("模型 %s 所有来源均下载失败: %s", model_name, last_error)
    return False


# Models used by xinyi
XINYI_MODELS = [
    "BAAI/bge-m3",
    "Johnson8187/Chinese-Emotion-Small",
    "BAAI/bge-reranker-base",
]


def preload_all_models() -> dict[str, bool]:
    """Download all xinyi models. Returns model -> success map."""
    results = {}
    for model in XINYI_MODELS:
        extra = "(可选)" if model == "BAAI/bge-reranker-base" else ""
        results[model] = download_model_once(model, extra)
    return results


def resolve_local_model_path(model_name: str) -> str:
    """Return local path for a cached model, avoiding network calls."""
    from huggingface_hub import snapshot_download

    try:
        return snapshot_download(repo_id=model_name, local_files_only=True)
    except Exception:
        st_dir = _st_cache_dir(model_name)
        if _has_required_artifacts(st_dir):
            return str(st_dir)
        return model_name


# ── Watchdog download (background thread + subprocess liveness) ──────────────

_download_aborted = False


def abort_download():
    """Request abort of any in-progress watchdog download."""
    global _download_aborted
    _download_aborted = True


def download_model_watchdog(
    model_name: str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> bool:
    """Download a model in a background thread, reporting progress every 15s.

    If the internal download process dies unexpectedly (e.g. network drop,
    OOM), returns False so the caller can show a "download failed, retry"
    message to the user.
    """
    global _download_aborted
    _download_aborted = False

    if is_model_cached(model_name):
        on_progress(f"✅ {model_name} 已缓存，跳过") if on_progress else None
        return True

    result_box: list = [None]   # [True/False]
    exc_box: list = [None]       # [Exception]
    start_time = [time.time()]

    def _worker():
        try:
            result_box[0] = download_model_once(model_name)
        except Exception as e:
            exc_box[0] = e
            result_box[0] = False

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    while t.is_alive():
        t.join(timeout=15)
        if _download_aborted:
            logger.info("下载 %s 被用户中止", model_name)
            return False
        elapsed = time.time() - start_time[0]
        minutes = int(elapsed // 60)
        secs = int(elapsed % 60)
        msg = f"下载中 {model_name}… ({minutes}m{secs}s)"
        on_progress(msg) if on_progress else None
        logger.info(msg)

    # Thread finished — success or error
    if exc_box[0] is not None:
        logger.warning("下载 %s 异常: %s", model_name, exc_box[0])

    return bool(result_box[0])


def retry_download_model(model_name: str) -> bool:
    """Clear partial download then re-download. Use when user clicks retry."""
    _clear_incomplete_download(model_name)
    return download_model_watchdog(model_name)


def download_all_models_watchdog(
    on_progress: Optional[Callable[[str, int, int, bool, str], None]] = None,
) -> dict[str, bool]:
    """Download all XINYI models sequentially with progress reporting.

    Args:
        on_progress(model, idx, total, done, msg): called every ~15s and on done.
             done=True means the model just finished.

    Returns:
        model -> success dict.
    """
    global _download_aborted
    _download_aborted = False

    results = {}
    total = len(XINYI_MODELS)

    for idx, model in enumerate(XINYI_MODELS, 1):
        if _download_aborted:
            logger.info("下载被用户中止")
            results[model] = False
            on_progress(model, idx, total, False, "中止") if on_progress else None
            continue

        extra = "(可选)" if model == "BAAI/bge-reranker-base" else ""

        def report(msg: str):
            on_progress(model, idx, total, False, msg) if on_progress else None

        report(f"开始下载 {model} {extra}…")

        success = download_model_watchdog(model, on_progress=report)

        results[model] = success
        status_msg = f"✅ {model} 完成" if success else f"❌ {model} 失败 — 请点「重试」"
        on_progress(model, idx, total, True, status_msg) if on_progress else None

        if success:
            logger.info("模型 %s 下载成功", model)
        else:
            logger.warning("模型 %s 下载失败，建议检查网络后重试", model)

    return results
