from __future__ import annotations

import logging
import os
from pathlib import Path

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
        safe_name = self._model_name.replace("/", "--")
        model_dir = _hf_cache_dir() / f"models--{safe_name}"
        if model_dir.exists() and any(model_dir.iterdir()):
            return True
        st_cache = Path.home() / ".cache" / "torch" / "sentence_transformers" / safe_name
        return st_cache.exists() and any(st_cache.iterdir())

    def download_model(self) -> None:
        prev_hf = os.environ.pop("HF_HUB_OFFLINE", None)
        prev_tf = os.environ.pop("TRANSFORMERS_OFFLINE", None)
        try:
            logger.info("正在下载嵌入模型 %s …", self._model_name)
            from sentence_transformers import SentenceTransformer
            SentenceTransformer(self._model_name, device="cpu")
            logger.info("嵌入模型下载完成")
        finally:
            if self._offline:
                if prev_hf is not None:
                    os.environ["HF_HUB_OFFLINE"] = prev_hf
                else:
                    os.environ["HF_HUB_OFFLINE"] = "1"
                if prev_tf is not None:
                    os.environ["TRANSFORMERS_OFFLINE"] = prev_tf
                else:
                    os.environ["TRANSFORMERS_OFFLINE"] = "1"

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
