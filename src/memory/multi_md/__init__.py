"""Multi-Markdown Memory System — OpenClaw 风格记忆层。

与现有 ChromaDB + MemoryBank 并存，提供：
- 每日对话日志（append-only）
- 策展型长期记忆（curated memory）
- 话题追踪
- 连续性锚点
- BM25 关键词检索

目录结构：
    twin_workspace/
    ├── memory.md           # 策展记忆（持久知识）
    ├── context/
    │   ├── topics.md      # 话题追踪
    │   └── anchors.md     # 连续性锚点
    └── logs/
        └── YYYY-MM-DD.md  # 每日日志

所有模块都设计为可独立使用，通过 MultiMDManager 统一编排。
"""

from .daily_log import DailyLogManager
from .curated_memory import CuratedMemory
from .topic_tracker import TopicTracker
from .anchors import AnchorTracker
from .bm25_search import BM25Search
from .multi_md_manager import MultiMDManager

__all__ = [
    "DailyLogManager",
    "CuratedMemory",
    "TopicTracker",
    "AnchorTracker",
    "BM25Search",
    "MultiMDManager",
]
