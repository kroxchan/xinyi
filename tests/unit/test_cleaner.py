"""Tests for MessageCleaner."""
from __future__ import annotations

from src.data.cleaner import MessageCleaner


def test_cleaner_removes_system_messages(sample_messages):
    """System messages (撤回、语音、视频) are removed."""
    messages = [
        {"StrTalker": "wxid_xxx", "StrContent": "在干嘛呢", "CreateTime": 1704067200, "IsSender": 0, "type": 1},
        {"StrTalker": "wxid_xxx", "StrContent": "在想你啊", "CreateTime": 1704067260, "IsSender": 1, "type": 1},
        {"StrTalker": "wxid_xxx", "StrContent": "今天加班好累", "CreateTime": 1704106800, "IsSender": 0, "type": 1},
        {"StrTalker": "wxid_xxx", "StrContent": "辛苦了，要不要我来接你", "CreateTime": 1704107100, "IsSender": 1, "type": 1},
        {"StrTalker": "wxid_xxx", "StrContent": "你撤回了一条消息", "CreateTime": 1704067500, "IsSender": 0, "type": 1},
        {"StrTalker": "wxid_xxx", "StrContent": "[语音]", "CreateTime": 1704067560, "IsSender": 0, "type": 1},
    ]
    cleaner = MessageCleaner()
    cleaned = cleaner.clean_messages(messages)
    assert all(m["StrContent"] != "你撤回了一条消息" for m in cleaned)
    assert all("[语音]" not in m["StrContent"] for m in cleaned)
