"""Persistent persona management — create, save, load, list, delete.

A Persona represents a conversation partner with a fixed relationship context
and continuous chat history, like a real WeChat contact.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DIR = "data/personas"

RELATIONSHIP_TYPES = {
    "self": "本人对话（自我优化）",
    "stranger": "陌生人",
    "friend": "朋友",
    "close_friend": "好朋友",
    "family": "家人",
    "partner": "对象",
    "colleague": "同事",
    "custom": "自定义",
}

RELATIONSHIP_TONES = {
    "self": "",
    "stranger": "对方是陌生人，你不认识TA，不知道TA是谁。该问就问，不要假装认识",
    "friend": "友好自然，有分寸但不生硬",
    "close_friend": "跟TA可以很放松，开玩笑，吐槽，分享私事",
    "family": "关心但不啰嗦，耐心",
    "partner": "跟TA说话要亲密自然，可以撒娇、用亲昵称呼，像真正的情侣对话",
    "colleague": "专业友好，适度寒暄",
    "custom": "",
}


class Persona:
    __slots__ = (
        "id", "name", "relationship", "label", "background",
        "messages", "created_at", "updated_at",
    )

    def __init__(
        self,
        id: str | None = None,
        name: str = "",
        relationship: str = "stranger",
        label: str = "",
        background: str = "",
        messages: list[dict] | None = None,
        created_at: float | None = None,
        updated_at: float | None = None,
    ) -> None:
        self.id = id or uuid.uuid4().hex[:12]
        self.name = name
        self.relationship = relationship
        self.label = label or RELATIONSHIP_TYPES.get(relationship, "")
        self.background = background
        self.messages = messages or []
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "relationship": self.relationship,
            "label": self.label,
            "background": self.background,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Persona:
        return cls(
            id=d["id"],
            name=d.get("name", ""),
            relationship=d.get("relationship", "stranger"),
            label=d.get("label", ""),
            background=d.get("background", ""),
            messages=d.get("messages", []),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
        )

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        self.updated_at = time.time()

    def display_name(self) -> str:
        """Human-readable name for UI display."""
        rel = RELATIONSHIP_TYPES.get(self.relationship, "")
        if self.name:
            return "{} - {}".format(rel, self.name) if rel else self.name
        return rel or "未命名"

    def to_contact_context(self) -> dict:
        """Build a contact_context dict compatible with PromptBuilder._build_identity."""
        return {
            "source": "persona",
            "display_name": self.name or "对方",
            "relationship": self.relationship,
            "relationship_label": self.label,
            "background": self.background,
            "chat_style": {},
        }


class PersonaManager:
    """Manages personas on disk as individual JSON files."""

    def __init__(self, directory: str = DEFAULT_DIR) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, persona_id: str) -> Path:
        return self.dir / (persona_id + ".json")

    def save(self, persona: Persona) -> None:
        with open(self._path(persona.id), "w", encoding="utf-8") as f:
            json.dump(persona.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, persona_id: str) -> Persona | None:
        p = self._path(persona_id)
        if not p.exists():
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return Persona.from_dict(json.load(f))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load persona %s: %s", persona_id, e)
            return None

    def list_personas(self) -> list[dict]:
        """Return persona summaries sorted by updated_at desc."""
        summaries = []
        for p in self.dir.glob("*.json"):
            try:
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                persona = Persona.from_dict(d)
                summaries.append({
                    "id": d["id"],
                    "display_name": persona.display_name(),
                    "relationship": d.get("relationship", "stranger"),
                    "updated_at": d.get("updated_at", 0),
                    "message_count": len(d.get("messages", [])),
                })
            except Exception:
                continue
        summaries.sort(key=lambda s: s["updated_at"], reverse=True)
        return summaries

    def delete(self, persona_id: str) -> bool:
        p = self._path(persona_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def create(
        self,
        name: str = "",
        relationship: str = "stranger",
        label: str = "",
        background: str = "",
    ) -> Persona:
        persona = Persona(
            name=name,
            relationship=relationship,
            label=label,
            background=background,
        )
        self.save(persona)
        return persona
