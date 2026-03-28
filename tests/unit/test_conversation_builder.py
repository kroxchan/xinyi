"""Tests for ConversationBuilder time-based chunking."""
from __future__ import annotations

from src.data.conversation_builder import ConversationBuilder


def test_builder_chunks_by_time_gap(sample_messages):
    """Conversations with > time_gap_minutes gap create separate chunks."""
    builder = ConversationBuilder(time_gap_minutes=5, max_turns=20, min_turns=1)
    
    # Messages 30 minutes apart should be separate chunks
    messages = [
        {"StrTalker": "wxid_xxx", "StrContent": "你好", "CreateTime": 1704067200, "IsSender": 0},
        {"StrTalker": "wxid_xxx", "StrContent": "你好呀", "CreateTime": 1704067260, "IsSender": 1},
        {"StrTalker": "wxid_xxx", "StrContent": "明天见", "CreateTime": 1704069300, "IsSender": 0},  # 35 min gap
        {"StrTalker": "wxid_xxx", "StrContent": "明天见！", "CreateTime": 1704069360, "IsSender": 1},
    ]
    chunks = builder.build_conversations(messages, skip_chatrooms=True)
    # Should produce 2 chunks: [1,2] and [3,4]
    assert len(chunks) == 2


def test_builder_respects_max_turns(sample_messages):
    """Conversations exceeding max_turns are split."""
    builder = ConversationBuilder(time_gap_minutes=999, max_turns=2, min_turns=1)
    
    messages = [
        {"StrTalker": "wxid_xxx", "StrContent": f"msg{i}", "CreateTime": 1704067200 + i * 60, "IsSender": i % 2}
        for i in range(1, 8)
    ]
    chunks = builder.build_conversations(messages, skip_chatrooms=True)
    # Should be split into chunks of 2 turns each
    for chunk in chunks:
        assert len(chunk.get("turns", [])) <= 2
