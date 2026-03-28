from __future__ import annotations

import logging
import os
from pathlib import Path

from src.utils.model_download import download_model_once, is_model_cached

logger = logging.getLogger(__name__)


def _hf_cache_dir() -> Path:
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


class TextEmbedder:
    """将文本转为向量嵌入，支持 Apple Silicon (mps) / CUDA / CPU。"""

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: str = "mps",
        offline: bool = True,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._offline = offline
        self._model = None

        if offline:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    def is_model_cached(self) -> bool:
        return is_model_cached(self._model_name)

    def download_model(self) -> None:
        download_model_once(self._model_name)

    def warmup(self) -> None:
        """Pre-load the model so first chat doesn't wait."""
        self._ensure_model()

    def _ensure_model(self):
        if self._model is None:
            if not self.is_model_cached():
                self.download_model()
            logger.info("正在加载嵌入模型 %s …", self._model_name)
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name, device=self._device)
            self._model.encode(["warmup"], normalize_embeddings=True)
            logger.info("嵌入模型加载完成")

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_single(self, text: str) -> list[float]:
        return self.embed([text])[0]
