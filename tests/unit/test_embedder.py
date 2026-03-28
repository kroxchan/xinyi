"""Tests for TextEmbedder and BGEReranker model cache checks."""
from __future__ import annotations

import pytest


def test_embedder_is_model_cached_returns_bool():
    """is_model_cached should return True or False without errors."""
    from src.memory.embedder import TextEmbedder

    emb = TextEmbedder(offline=True)
    result = emb.is_model_cached()
    assert isinstance(result, bool)


def test_bge_reranker_is_model_cached_returns_bool():
    """BGEReranker.is_model_cached should return True or False without errors."""
    from src.memory.reranker import BGEReranker

    rr = BGEReranker(offline=True)
    result = rr.is_model_cached()
    assert isinstance(result, bool)


def test_reranker_factory_returns_none_when_disabled():
    """build_reranker with enabled=false returns None."""
    from src.memory.reranker import build_reranker

    config = {"rerank": {"enabled": False}}
    result = build_reranker(config)
    assert result is None
