"""UI Tabs package ? extracted from app.py"""
from __future__ import annotations

from .tab_setup import render_setup_tab
from .tab_chat import render_chat_tab, render_tab_chat
from .tab_eval import render_eval_tab
from .tab_cognitive import render_cognitive_tab
from .tab_analytics import render_analytics_tab
from .tab_beliefs import render_beliefs_tab
from .tab_memories import render_memories_tab
from .tab_system import render_system_tab

__all__ = [
    "render_setup_tab",
    "render_chat_tab",
    "render_tab_chat",
    "render_eval_tab",
    "render_cognitive_tab",
    "render_analytics_tab",
    "render_beliefs_tab",
    "render_memories_tab",
    "render_system_tab",
]
