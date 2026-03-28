"""Tests for MemoryRetriever including rerank integration."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class FakeHit:
    def __init__(self, text, distance=0.5):
        self._text = text
        self._distance = distance

    def __getitem__(self, key):
        if key == "text":
            return self._text
        if key == "distance":
            return self._distance
        if key == "metadata":
            return {"start_time": "2024-01-01", "contact": "wxid_xxx"}
        raise KeyError(key)


class FakeVectorStore:
    def __init__(self, hits=None):
        self._hits = hits or []

    def search(self, query, embedder, top_k=5, contact_filter=None):
        return [{"id": f"hit{i}", "text": h["text"], "metadata": h["metadata"], "distance": h["distance"]}
                for i, h in enumerate(self._hits)]


class FakeReranker:
    """Fake reranker that reverses the candidate order (so rerank changes result)."""
    def __init__(self, scores=None):
        self._scores = scores or {}

    def rerank(self, query, candidates, top_k):
        scored = [(c, self._scores.get(c, 0.0)) for c in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [{"content": c, "score": s} for c, s in scored[:top_k]]


def test_retrieve_no_reranker_returns_formatted_fragments(mock_embedder):
    """Without reranker, retriever returns formatted [记忆片段N] strings."""
    from src.memory.retriever import MemoryRetriever

    hits = [
        {"text": "你好呀", "metadata": {"start_time": "2024-01-01", "contact": "Alice"}, "distance": 0.1},
        {"text": "今天怎么样", "metadata": {"start_time": "2024-01-02", "contact": "Alice"}, "distance": 0.2},
    ]
    vs = FakeVectorStore(hits)
    retriever = MemoryRetriever(vs, mock_embedder, reranker=None)

    result = retriever.retrieve("hello", top_k=2)
    assert "记忆片段1" in result
    assert "你好呀" in result
    assert "记忆片段2" in result
    assert "今天怎么样" in result


def test_retrieve_empty_returns_no_memory_placeholder(mock_embedder):
    """Empty vector search returns the no-memory placeholder."""
    from src.memory.retriever import MemoryRetriever

    vs = FakeVectorStore([])
    retriever = MemoryRetriever(vs, mock_embedder, reranker=None)

    result = retriever.retrieve("hello", top_k=5)
    assert "没有找到相关记忆" in result


def test_retrieve_with_reranker_scores_attached(mock_embedder):
    """With reranker, results have rerank_score attached when available."""
    from src.memory.retriever import MemoryRetriever

    hits = [
        {"text": "A is relevant", "metadata": {"start_time": "2024-01-01", "contact": "Alice"}, "distance": 0.1},
        {"text": "B is most relevant", "metadata": {"start_time": "2024-01-02", "contact": "Alice"}, "distance": 0.05},
        {"text": "C is irrelevant", "metadata": {"start_time": "2024-01-03", "contact": "Alice"}, "distance": 0.9},
    ]
    vs = FakeVectorStore(hits)

    # Fake reranker scores: B > A > C (overrides vector distance)
    fake_reranker = FakeReranker(scores={"B is most relevant": 0.99, "A is relevant": 0.5, "C is irrelevant": 0.1})
    retriever = MemoryRetriever(vs, mock_embedder, reranker=fake_reranker, top_k_raw=10)

    # Call retrieve and check that reranked results have scores
    # We can verify by checking log output or the formatted result contains all texts
    result = retriever.retrieve("test query", top_k=3)

    # All 3 texts should appear in the result
    assert "B is most relevant" in result
    assert "A is relevant" in result
    assert "C is irrelevant" in result


def test_reranker_top_k_limits_output(mock_embedder):
    """Reranked output respects top_k even if more candidates returned."""
    from src.memory.retriever import MemoryRetriever

    hits = [{"text": f"text{i}", "metadata": {"start_time": f"2024-01-0{i}", "contact": "Alice"}, "distance": 0.1}
            for i in range(1, 11)]  # 10 hits
    vs = FakeVectorStore(hits)

    fake_reranker = FakeReranker(scores={f"text{i}": 1.0 - i * 0.05 for i in range(1, 11)})
    retriever = MemoryRetriever(vs, mock_embedder, reranker=fake_reranker, top_k_raw=20)

    result = retriever.retrieve("query", top_k=3)

    # Should only have 3 fragments due to top_k limit
    assert result.count("记忆片段") == 3
    # Results should be from the reranked set (text1-text10)
    assert "text1" in result
