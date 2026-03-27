from __future__ import annotations

import logging
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

logger = logging.getLogger(__name__)


class TextEmbedder:
    """将文本转为向量嵌入，支持 Apple Silicon (mps) / CUDA / CPU。"""

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "mps") -> None:
        self._model_name = model_name
        self._device = device
        self._model = None

    def warmup(self) -> None:
        """Pre-load the model so first chat doesn't wait."""
        self._ensure_model()

    def _ensure_model(self):
        if self._model is None:
            logger.info("正在加载嵌入模型 %s (offline mode) …", self._model_name)
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
