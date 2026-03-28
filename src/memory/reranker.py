"""Reranker for two-stage retrieval: coarse vector search → fine cross-encoder rerank."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from src.logging_config import get_logger

logger = get_logger(__name__)


def _hf_cache_dir() -> Path:
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


class BaseReranker(ABC):
    """Abstract reranker interface."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[str],
        top_k: int,
    ) -> list[dict]:
        """Score candidates against query and return top-k reranked results.

        Args:
            query: User query string.
            candidates: List of candidate text strings.
            top_k: Number of results to return.

        Returns:
            List of dicts with keys: "content" (str), "score" (float, higher = better).
        """
        ...


class BGEReranker(BaseReranker):
    """Local BAAI/bge-reranker-base, CPU-friendly (~50-100ms for 20 candidates)."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        device: str = "cpu",
        offline: bool = True,
        max_batch_size: int = 32,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._offline = offline
        self._max_batch_size = max_batch_size
        self._model = None

        if offline:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    # ── model lifecycle ─────────────────────────────────────────────────────────

    def is_model_cached(self) -> bool:
        safe_name = self._model_name.replace("/", "--")
        hf_dir = _hf_cache_dir() / f"models--{safe_name}"
        if hf_dir.exists() and any(hf_dir.iterdir()):
            return True
        st_dir = Path.home() / ".cache" / "torch" / "sentence_transformers" / safe_name
        return st_dir.exists() and any(st_dir.iterdir())

    def download_model(self) -> None:
        prev_hf = os.environ.pop("HF_HUB_OFFLINE", None)
        prev_tf = os.environ.pop("TRANSFORMERS_OFFLINE", None)
        try:
            logger.info("正在下载 rerank 模型 %s …", self._model_name)
            from sentence_transformers import CrossEncoder

            CrossEncoder(self._model_name, device="cpu")
            logger.info("rerank 模型下载完成")
        finally:
            if self._offline:
                if prev_hf is not None:
                    os.environ["HF_HUB_OFFLINE"] = prev_hf
                else:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                if prev_tf is not None:
                    os.environ["TRANSFORMERS_OFFLINE"] = prev_tf
                else:
                    os.environ.pop("TRANSFORMERS_OFFLINE", None)

    def warmup(self) -> None:
        self._ensure_model()

    def _ensure_model(self) -> None:
        if self._model is None:
            if not self.is_model_cached():
                self.download_model()
            logger.info("正在加载 rerank 模型 %s …", self._model_name)
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self._model_name, device=self._device)
            # warmup
            self._model.predict([("warmup", "warmup")])
            logger.info("rerank 模型加载完成")

    # ── rerank ────────────────────────────────────────────────────────────────

    def rerank(
        self,
        query: str,
        candidates: list[str],
        top_k: int,
    ) -> list[dict]:
        if not candidates:
            return []

        import time
        t0 = time.perf_counter()
        self._ensure_model()
        load_ms = (time.perf_counter() - t0) * 1000

        pairs = [(query, c) for c in candidates]
        t1 = time.perf_counter()
        scores = self._model.predict(pairs, show_progress_bar=False)
        rerank_ms = (time.perf_counter() - t1) * 1000

        if not hasattr(scores, "tolist"):
            scores = scores.tolist()

        scored = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        logger.info("rerank: 模型加载 %.0fms / 重排耗时 %.1fms (%d candidates → top-%d)",
                    load_ms, rerank_ms, len(candidates), top_k)
        return [
            {"content": text, "score": float(score)}
            for text, score in scored[:top_k]
        ]


class CohereReranker(BaseReranker):
    """Cohere Rerank API, no local model required."""

    def __init__(
        self,
        api_key: str,
        model: str = "rerank-multilingual-v3.0",
        top_k: int = 5,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._top_k = top_k

    def rerank(
        self,
        query: str,
        candidates: list[str],
        top_k: int,
    ) -> list[dict]:
        if not candidates:
            return []

        try:
            import cohere

            client = cohere.Client(self._api_key)
            resp = client.rerank(
                query=query,
                documents=candidates,
                model=self._model,
                top_n=top_k,
                return_documents=False,
            )
            results = []
            for r in resp.results:
                results.append({"content": candidates[r.index], "score": float(r.relevance_score)})
            return results
        except Exception as e:
            logger.warning("Cohere rerank failed, falling back to empty: %s", e)
            return []


# ── factory ────────────────────────────────────────────────────────────────────


def build_reranker(config: dict) -> BaseReranker | None:
    """Build a reranker from config dict.

    Config shape (config.yaml):
        rerank:
            enabled: true
            provider: "local"          # "local" | "cohere"
            model: "BAAI/bge-reranker-base"
            cohere_api_key: "${COHERE_API_KEY:}"
            device: "cpu"
            top_k_raw: 20
            top_k_reranked: 5
    """
    rerank_cfg = config.get("rerank", {})
    if not rerank_cfg.get("enabled", False):
        return None

    provider = rerank_cfg.get("provider", "local")

    if provider == "cohere":
        raw_key = rerank_cfg.get("cohere_api_key", "")
        import os as _os

        api_key = os.path.expandvars(raw_key)
        if not api_key:
            logger.warning("Cohere API key not set, skipping rerank")
            return None
        return CohereReranker(api_key=api_key, model=rerank_cfg.get("model", "rerank-multilingual-v3.0"))

    # local BAAI reranker
    return BGEReranker(
        model_name=rerank_cfg.get("model", "BAAI/bge-reranker-base"),
        device=rerank_cfg.get("device", "cpu"),
    )
