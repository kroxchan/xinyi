"""UI Tabs package — extracted from app.py"""
from __future__ import annotations

from .tab_setup import render_tab_setup
from .tab_chat import render_chat_tab, render_tab_chat
from .tab_eval import render_tab_eval
from .tab_cognitive import render_tab_cognitive
from .tab_analytics import render_tab_analytics
from .tab_beliefs import render_tab_beliefs
from .tab_memories import render_tab_memories
from .tab_system import render_tab_system

__all__ = [
    "render_tab_setup",
    "render_chat_tab",
    "render_tab_chat",
    "render_tab_eval",
    "render_tab_cognitive",
    "render_tab_analytics",
    "render_tab_beliefs",
    "render_tab_memories",
    "render_tab_system",
]
