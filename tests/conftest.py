"""Pytest fixtures for xinyi tests."""
from __future__ import annotations

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock

# ── sample data fixtures ──────────────────────────────────────

@pytest.fixture
def sample_messages():
    """Minimal list of raw WeChat messages."""
    return [
        {"msgId": "1", "msg": "在干嘛呢", "strCreateTime": "2024-01-01 10:00:00", "isSender": 0, "talker": "wxid_xxx"},
        {"msgId": "2", "msg": "在想你啊", "strCreateTime": "2024-01-01 10:01:00", "isSender": 1, "talker": "wxid_xxx"},
        {"msgId": "3", "msg": "今天加班好累", "strCreateTime": "2024-01-01 18:00:00", "isSender": 0, "talker": "wxid_xxx"},
        {"msgId": "4", "msg": "辛苦了，要不要我来接你", "strCreateTime": "2024-01-01 18:05:00", "isSender": 1, "talker": "wxid_xxx"},
    ]

@pytest.fixture
def sample_conversations():
    """Minimal list of structured conversation chunks."""
    return [
        {
            "id": "conv1",
            "text": "A: 在干嘛呢\nB: 在想你啊",
            "contact": "wxid_xxx",
            "start_time": "2024-01-01 10:00:00",
            "end_time": "2024-01-01 10:02:00",
            "turn_count": 2,
        },
        {
            "id": "conv2", 
            "text": "A: 今天加班好累\nB: 辛苦了，要不要我来接你",
            "contact": "wxid_xxx",
            "start_time": "2024-01-01 18:00:00",
            "end_time": "2024-01-01 18:06:00",
            "turn_count": 2,
        },
    ]

# ── mock components ────────────────────────────────────────────

@pytest.fixture
def mock_embedder():
    """Fake embedder that returns deterministic vectors."""
    class FakeEmbedder:
        def embed(self, texts):
            import numpy as np
            # deterministic fake embedding (dim=4)
            return (np.random.rand(len(texts), 4) * 0.01).tolist()
        def embed_single(self, text):
            return self.embed([text])[0]
        def is_model_cached(self):
            return True
    return FakeEmbedder()

@pytest.fixture
def mock_llm_response():
    """Factory for mock LLM chat completions responses."""
    def _make(content: str) -> MagicMock:
        mock = MagicMock()
        mock.choices = [MagicMock()]
        mock.choices[0].message.content = content
        return mock
    return _make

# ── test dirs ─────────────────────────────────────────────────

@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temp data directory structure."""
    d = tmp_path / "data"
    d.mkdir()
    (d / "raw").mkdir()
    (d / "processed").mkdir()
    (d / "chroma_db").mkdir()
    return d
