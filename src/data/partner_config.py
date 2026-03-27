"""Persist which WeChat contact is the confirmed partner (情侣对象)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/partner_config.json")


def load_partner_wxid() -> str:
    if not DEFAULT_PATH.exists():
        return ""
    try:
        data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        return (data.get("partner_wxid") or "").strip()
    except Exception as e:
        logger.warning("Failed to load partner config: %s", e)
        return ""


def save_partner_wxid(wxid: str) -> None:
    DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if DEFAULT_PATH.exists():
        try:
            data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["partner_wxid"] = (wxid or "").strip()
    DEFAULT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_twin_mode() -> str:
    if not DEFAULT_PATH.exists():
        return "self"
    try:
        data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        mode = (data.get("twin_mode") or "").strip()
        return mode if mode in ("self", "partner") else "self"
    except Exception as e:
        logger.warning("Failed to load twin_mode: %s", e)
        return "self"


def save_twin_mode(mode: str) -> None:
    DEFAULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if DEFAULT_PATH.exists():
        try:
            data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["twin_mode"] = mode if mode in ("self", "partner") else "self"
    DEFAULT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
