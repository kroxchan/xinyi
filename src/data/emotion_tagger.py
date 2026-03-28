"""Emotion tagger for training-time chunk labeling.

Tag every conversation chunk with a dominant emotion label so that
retrieval can prioritize emotionally congruent memories
(e.g. when the user is angry, prefer chunks from angry conversations).

Two modes:
- local  : jefferyluo/bert-chinese-emotion  (CPU, ~50ms/chunk, no API cost)
- llm    : call the LLM with a simple classification prompt
"""
from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from src.logging_config import get_logger
from src.utils.model_download import download_model_once, is_model_cached, resolve_local_model_path

logger = get_logger(__name__)

EMOTION_LABELS = [
    "joy",          # 开心/愉快
    "excitement",   # 兴奋
    "touched",      # 感动
    "gratitude",    # 感谢
    "pride",        # 骄傲
    "sadness",      # 难过/悲伤
    "anger",        # 生气/愤怒
    "anxiety",       # 焦虑/担心
    "disappointment", # 失望
    "wronged",      # 委屈
    "coquettish",   # 撒娇
    "jealousy",     # 吃醋
    "heartache",    # 心疼
    "longing",      # 想念/思念
    "curiosity",    # 好奇
    "neutral",      # 中性/无明显情绪
]

EMOTION_DISPLAY = {
    "joy": "开心",
    "excitement": "兴奋",
    "touched": "感动",
    "gratitude": "感谢",
    "pride": "骄傲",
    "sadness": "难过",
    "anger": "生气",
    "anxiety": "焦虑",
    "disappointment": "失望",
    "wronged": "委屈",
    "coquettish": "撒娇",
    "jealousy": "吃醋",
    "heartache": "心疼",
    "longing": "想念",
    "curiosity": "好奇",
    "neutral": "中性",
}

DEFAULT_LOCAL_EMOTION_MODEL = "Johnson8187/Chinese-Emotion-Small"
LEGACY_LOCAL_EMOTION_MODEL = "jefferyluo/bert-chinese-emotion"
FALLBACK_LOCAL_EMOTION_MODELS = [
    DEFAULT_LOCAL_EMOTION_MODEL,
]

MODEL_LABEL_MAPPINGS: dict[str, dict[int | str, str]] = {
    "Johnson8187/Chinese-Emotion-Small": {
        0: "neutral",
        1: "anxiety",
        2: "joy",
        3: "anger",
        4: "sadness",
        5: "curiosity",
        6: "excitement",
        7: "disappointment",
        "label_0": "neutral",
        "label_1": "anxiety",
        "label_2": "joy",
        "label_3": "anger",
        "label_4": "sadness",
        "label_5": "curiosity",
        "label_6": "excitement",
        "label_7": "disappointment",
    },
    "Johnson8187/Chinese-Emotion": {
        0: "neutral",
        1: "anxiety",
        2: "joy",
        3: "anger",
        4: "sadness",
        5: "curiosity",
        6: "excitement",
        7: "disappointment",
        "label_0": "neutral",
        "label_1": "anxiety",
        "label_2": "joy",
        "label_3": "anger",
        "label_4": "sadness",
        "label_5": "curiosity",
        "label_6": "excitement",
        "label_7": "disappointment",
    },
}

class BaseEmotionTagger(ABC):
    """Abstract interface for emotion taggers."""

    @abstractmethod
    def tag(self, text: str) -> str:
        """Return the dominant emotion label for a single text."""
        ...

    @abstractmethod
    def tag_batch(self, texts: list[str]) -> list[str]:
        """Return a list of emotion labels (one per text)."""
        ...


class LocalEmotionTagger(BaseEmotionTagger):
    """Local Chinese emotion classifier with fallback candidates."""

    def __init__(
        self,
        model_name: str = "jefferyluo/bert-chinese-emotion",
        device: str = "cpu",
        offline: bool = True,
        max_batch_size: int = 32,
    ) -> None:
        self._model_name = model_name
        self._candidate_models = self._build_candidate_models(model_name)
        self._resolved_model_name = model_name
        self._device = device
        self._offline = offline
        self._max_batch_size = max_batch_size
        self._model = None

        if offline:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    # ── model lifecycle ─────────────────────────────────────────────────────

    @staticmethod
    def _build_candidate_models(model_name: str) -> list[str]:
        ordered: list[str] = []
        for candidate in [model_name, *FALLBACK_LOCAL_EMOTION_MODELS]:
            if candidate and candidate not in ordered:
                ordered.append(candidate)
        return ordered

    def is_model_cached(self) -> bool:
        return any(is_model_cached(model_name) for model_name in self._candidate_models)

    def download_model(self) -> None:
        last_failure = None
        for model_name in self._candidate_models:
            logger.info("检查情感分类模型候选: %s", model_name)
            if download_model_once(model_name):
                self._resolved_model_name = model_name
                return
            last_failure = model_name
        raise RuntimeError("情感模型下载失败，所有候选均不可用: {}".format(last_failure))

    def warmup(self) -> None:
        self._ensure_model()

    def _ensure_model(self) -> None:
        if self._model is None:
            if not self.is_model_cached():
                self.download_model()
            self._resolved_model_name = self._pick_available_model()
            logger.info("正在加载情感分类模型 %s …", self._resolved_model_name)
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            model_path = resolve_local_model_path(self._resolved_model_name)
            tok = AutoTokenizer.from_pretrained(model_path)
            model = AutoModelForSequenceClassification.from_pretrained(model_path)
            self._model = (model, tok)
            # warmup
            self._predict_one("测试文本")
            logger.info("情感分类模型加载完成")

    def _pick_available_model(self) -> str:
        for model_name in self._candidate_models:
            if is_model_cached(model_name):
                return model_name
        return self._candidate_models[0]

    def _normalize_label(self, pred_id: int, raw_label: str) -> str:
        mapping = MODEL_LABEL_MAPPINGS.get(self._resolved_model_name, {})
        if pred_id in mapping:
            return mapping[pred_id]
        lowered = str(raw_label).strip().lower()
        if lowered in mapping:
            return mapping[lowered]
        if lowered in EMOTION_LABELS:
            return lowered
        return "neutral"

    # ── predict ─────────────────────────────────────────────────────────────

    def _predict_one(self, text: str) -> str:
        model, tok = self._model
        inputs = tok(text, return_tensors="pt", truncation=True, max_length=128)
        import torch
        with torch.no_grad():
            logits = model(**inputs).logits
        pred_id = int(logits.argmax(dim=-1).item())
        labels = model.config.id2label
        return self._normalize_label(pred_id, labels.get(pred_id, "neutral"))

    def tag(self, text: str) -> str:
        if not text or not text.strip():
            return "neutral"
        self._ensure_model()
        return self._predict_one(text[:512])

    def tag_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        self._ensure_model()
        model, tok = self._model
        import torch

        results: list[str] = []
        for i in range(0, len(texts), self._max_batch_size):
            batch = [t[:512] for t in texts[i : i + self._max_batch_size]]
            try:
                inputs = tok(
                    batch,
                    return_tensors="pt",
                    truncation=True,
                    max_length=128,
                    padding=True,
                )
                with torch.no_grad():
                    logits = model(**inputs).logits
                preds = logits.argmax(dim=-1).tolist()
                labels = model.config.id2label
                for p in preds:
                    results.append(self._normalize_label(p, labels.get(p, "neutral")))
            except Exception as e:
                logger.warning("batch tag failed for chunk %d: %s", i, e)
                results.extend(["neutral"] * len(batch))
        return results


class LLMTagger(BaseEmotionTagger):
    """Use the main LLM for emotion classification via a simple prompt."""

    def __init__(
        self,
        api_client: Any,
        model: str = "gpt-4o",
        batch_size: int = 10,
    ) -> None:
        self._client = api_client
        self._model = model
        self._batch_size = batch_size

    def tag(self, text: str) -> str:
        labels = self.tag_batch([text])
        return labels[0] if labels else "neutral"

    def tag_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        prompt = (
            "以下每条消息的格式是「序号. 内容」。"
            "请判断每条消息的主导情绪，只返回情绪标签（每行一个）。\n"
            "可选标签：\n" + "\n".join(f"- {k}: {v}" for k, v in EMOTION_DISPLAY.items()) + "\n\n"
            + "\n".join(f"{i+1}. {t[:200]}" for i, t in enumerate(texts))
            + "\n\n直接输出标签列表，每行一个，不要其他解释。"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            raw = (resp.choices[0].message.content or "").strip()
            lines = [l.strip().lower() for l in raw.splitlines() if l.strip()]
            # Map display names back to labels
            label_map = {v: k for k, v in EMOTION_DISPLAY.items()}
            results = []
            for line in lines:
                line_lower = line.lower()
                if line_lower in EMOTION_LABELS:
                    results.append(line_lower)
                elif line_lower in label_map:
                    results.append(label_map[line_lower])
                else:
                    results.append("neutral")
            if len(results) < len(texts):
                results.extend(["neutral"] * (len(texts) - len(results)))
            return results[: len(texts)]
        except Exception as e:
            logger.warning("LLM emotion tagging failed: %s", e)
            return ["neutral"] * len(texts)


# ── factory ──────────────────────────────────────────────────────────────────


def build_tagger(
    config: dict,
    api_client: Any = None,
) -> BaseEmotionTagger | None:
    """Build an emotion tagger from config dict.

    Config shape (config.yaml):
        emotion:
            enabled: true
            provider: "local" | "llm"
            model: "Johnson8187/Chinese-Emotion-Small"
            emotion_boost_weight: 1.5
    """
    emotion_cfg = config.get("emotion", {})
    if not emotion_cfg.get("enabled", False):
        return None

    provider = emotion_cfg.get("provider", "local")

    if provider == "llm":
        if api_client is None:
            logger.warning("LLM emotion tagger requires api_client, skipping")
            return None
        return LLMTagger(
            api_client=api_client,
            model=emotion_cfg.get("model", "gpt-4o"),
        )

    # local BERT tagger
    return LocalEmotionTagger(
        model_name=emotion_cfg.get("model", DEFAULT_LOCAL_EMOTION_MODEL),
        device=emotion_cfg.get("device", "cpu"),
    )
