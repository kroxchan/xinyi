"""Application-level shared state.

Replaces the module-level globals in app.py so that all tab functions
receive state explicitly rather than importing from app.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppState:
    """All mutable application state, passed explicitly to tab render functions."""

    components: dict | None = None
    init_error: str | None = None
    contact_registry = None
    session_mgr = None
    persona_mgr = None

    # Constants (read from config)
    MIN_CALIBRATION_TASKS: int = 5
    PARTNER_PERSONA_SELF_ID: str = "couple_self"
    PARTNER_PERSONA_PARTNER_ID: str = "couple_partner"
    PARTNER_MIN_TRAIN_MESSAGES: int = 30


# Singleton instance — initialised once at module level in app.py
_state: AppState | None = None


def get_state() -> AppState:
    if _state is None:
        raise RuntimeError("AppState not initialised")
    return _state


def init_state(**kwargs) -> AppState:
    global _state
    _state = AppState(**kwargs)
    return _state
