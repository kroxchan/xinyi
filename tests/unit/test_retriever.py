"""Tests for MemoryRetriever."""
from __future__ import annotations

import pytest


class _FakeHit:
    def __init__(self, text, distance=0.5, metadata=None):
        self._text = text
        self._distance = distance
        self._metadata = metadata or {"start_time": "2024-01-01", "contact": "wxid_xxx"}

    def __getitem__(self, key):
        if key == "text":
            return self._text
        if key == "distance":
            return self._distance
        if key == "metadata":
            return self._metadata
        raise KeyError(key)


class _FakeVectorStore:
    def __init__(self, hits=None):
        self._hits = hits or []

    def search(self, query, embedder, top_k=5, contact_filter=None):
        return [{"id": f"hit{i}", "text": h._text, "metadata": h._metadata, "distance": h._distance}
                for i, h in enumerate(self._hits[:top_k])]


def test_retrieve_returns_formatted_fragments(mock_embedder):
    """With hits, retriever returns correctly formatted [记忆片段N] strings."""
    from src.memory.retriever import MemoryRetriever

    vs = _FakeVectorStore([
        _FakeHit("你好呀", metadata={"start_time": "2024-01-01", "contact": "Alice"}),
        _FakeHit("今天怎么样", metadata={"start_time": "2024-01-02", "contact": "Alice"}),
    ])
    retriever = MemoryRetriever(vs, mock_embedder)

    result = retriever.retrieve("hello", top_k=2)

    assert "记忆片段1" in result
    assert "你好呀" in result
    assert "记忆片段2" in result
    assert "今天怎么样" in result
    assert "Alice" in result


def test_retrieve_empty_returns_no_memory_placeholder(mock_embedder):
    """Empty vector search returns the no-memory placeholder."""
    from src.memory.retriever import MemoryRetriever

    vs = _FakeVectorStore([])
    retriever = MemoryRetriever(vs, mock_embedder)

    result = retriever.retrieve("hello", top_k=5)

    assert "没有找到相关记忆" in result


def test_retrieve_falls_back_without_filter_when_no_results(mock_embedder):
    """When contact-filtered search returns nothing, retriever retries without filter."""
    class _PartialFakeStore:
        def __init__(self):
            self.call_count = 0

        def search(self, query, embedder, top_k=5, contact_filter=None):
            self.call_count += 1
            if self.call_count == 1:
                # First call (with filter) returns empty
                assert contact_filter == "wxid_filtered"
                return []
            # Second call (no filter) returns hits
            return [{"id": "hit1", "text": "fallback text",
                     "metadata": {"start_time": "2024-01-01", "contact": "Anyone"},
                     "distance": 0.1}]

    from src.memory.retriever import MemoryRetriever
    vs = _PartialFakeStore()
    retriever = MemoryRetriever(vs, mock_embedder)

    result = retriever.retrieve("query", top_k=5, contact_wxid="wxid_filtered")

    assert "fallback text" in result
    assert vs.call_count == 2


def test_retrieve_respects_top_k(mock_embedder):
    """Result fragment count respects the top_k parameter."""
    from src.memory.retriever import MemoryRetriever

    vs = _FakeVectorStore([
        _FakeHit(f"text{i}", metadata={"start_time": f"2024-01-0{i}", "contact": "A"})
        for i in range(1, 9)
    ])
    retriever = MemoryRetriever(vs, mock_embedder)

    result = retriever.retrieve("query", top_k=3)

    assert result.count("记忆片段") == 3
    assert "text1" in result
    assert "text3" in result
    assert "text7" not in result


def test_retrieve_includes_date_and_contact_in_fragment_header(mock_embedder):
    """Each fragment header contains the correct date and contact."""
    from src.memory.retriever import MemoryRetriever

    vs = _FakeVectorStore([
        _FakeHit(
            "我想你了",
            metadata={"start_time": "2024-03-14 20:00:00", "contact": "女朋友"},
        ),
    ])
    retriever = MemoryRetriever(vs, mock_embedder)

    result = retriever.retrieve("love", top_k=1)

    assert "记忆片段1" in result
    assert "2024-03-14" in result
    assert "女朋友" in result
    assert "我想你了" in result
