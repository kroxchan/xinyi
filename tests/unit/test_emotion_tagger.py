"""Tests for local emotion tagger fallback and label mapping."""
from __future__ import annotations


def test_local_emotion_tagger_falls_back_to_public_model(monkeypatch):
    from src.data.emotion_tagger import (
        DEFAULT_LOCAL_EMOTION_MODEL,
        LocalEmotionTagger,
    )

    attempts = []

    def _fake_download(model_name, extra_msg=""):
        attempts.append(model_name)
        return model_name == DEFAULT_LOCAL_EMOTION_MODEL

    monkeypatch.setattr("src.data.emotion_tagger.download_model_once", _fake_download)

    tagger = LocalEmotionTagger(model_name="jefferyluo/bert-chinese-emotion")
    tagger.download_model()

    assert attempts == [
        "jefferyluo/bert-chinese-emotion",
        DEFAULT_LOCAL_EMOTION_MODEL,
    ]
    assert tagger._resolved_model_name == DEFAULT_LOCAL_EMOTION_MODEL


def test_local_emotion_tagger_uses_any_cached_candidate(monkeypatch):
    from src.data.emotion_tagger import (
        DEFAULT_LOCAL_EMOTION_MODEL,
        LocalEmotionTagger,
    )

    monkeypatch.setattr(
        "src.data.emotion_tagger.is_model_cached",
        lambda model_name: model_name == DEFAULT_LOCAL_EMOTION_MODEL,
    )

    tagger = LocalEmotionTagger(model_name="jefferyluo/bert-chinese-emotion")

    assert tagger.is_model_cached() is True
    assert tagger._pick_available_model() == DEFAULT_LOCAL_EMOTION_MODEL


def test_local_emotion_tagger_maps_public_model_labels():
    from src.data.emotion_tagger import LocalEmotionTagger

    tagger = LocalEmotionTagger(model_name="Johnson8187/Chinese-Emotion-Small")
    tagger._resolved_model_name = "Johnson8187/Chinese-Emotion-Small"

    assert tagger._normalize_label(0, "LABEL_0") == "neutral"
    assert tagger._normalize_label(3, "LABEL_3") == "anger"
    assert tagger._normalize_label(6, "LABEL_6") == "excitement"
