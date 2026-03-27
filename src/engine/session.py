"""Chat session persistence — create, save, load, list, delete."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DIR = "data/sessions"


class Session:
    __slots__ = ("id", "title", "mode", "contact_wxid", "created_at", "updated_at", "messages")

    def __init__(
        self,
        id: str | None = None,
        title: str = "新对话",
        mode: str = "owner",
        contact_wxid: str = "",
        created_at: float | None = None,
        updated_at: float | None = None,
        messages: list[dict] | None = None,
    ) -> None:
        self.id = id or uuid.uuid4().hex[:12]
        self.title = title
        self.mode = mode
        self.contact_wxid = contact_wxid
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or self.created_at
        self.messages = messages or []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "mode": self.mode,
            "contact_wxid": self.contact_wxid,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Session:
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            mode=d.get("mode", "owner"),
            contact_wxid=d.get("contact_wxid", ""),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
            messages=d.get("messages", []),
        )

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self.updated_at = time.time()

    def auto_title(self) -> None:
        """Set title from the first user message if still default."""
        if self.title != "新对话":
            return
        for m in self.messages:
            if m["role"] == "user":
                text = m["content"][:30]
                if len(m["content"]) > 30:
                    text += "…"
                self.title = text
                return


class SessionManager:
    """Manages sessions on disk as individual JSON files."""

    def __init__(self, directory: str = DEFAULT_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.dir / (session_id + ".json")

    def save(self, session: Session) -> None:
        with open(self._path(session.id), "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, session_id: str) -> Session | None:
        p = self._path(session_id)
        if not p.exists():
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return Session.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load session %s: %s", session_id, e)
            return None

    def list_sessions(self) -> list[dict]:
        """Return session summaries sorted by updated_at desc."""
        summaries = []
        for p in self.dir.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                summaries.append({
                    "id": d["id"],
                    "title": d.get("title", ""),
                    "mode": d.get("mode", "owner"),
                    "updated_at": d.get("updated_at", 0),
                    "message_count": len(d.get("messages", [])),
                })
            except Exception:
                continue
        summaries.sort(key=lambda s: s["updated_at"], reverse=True)
        return summaries

    def delete(self, session_id: str) -> bool:
        p = self._path(session_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def create(self, mode: str = "owner") -> Session:
        s = Session(mode=mode)
        self.save(s)
        return s
