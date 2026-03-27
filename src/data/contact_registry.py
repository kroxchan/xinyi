from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

RELATIONSHIP_TYPES = [
    "partner", "close_friend", "friend",
    "family", "colleague", "acquaintance",
    "group_family", "group_close_friend", "group_friend", "group_colleague", "group_chat",
    "service", "unknown",
]

RELATIONSHIP_LABELS = {
    "partner": "伴侣/对象",
    "close_friend": "闺蜜/好友", "friend": "朋友",
    "family": "家人", "colleague": "同事",
    "acquaintance": "认识的人",
    "group_family": "家人群", "group_close_friend": "好友群",
    "group_friend": "朋友群", "group_colleague": "同事群",
    "group_chat": "群聊（其他）",
    "service": "服务号", "unknown": "未知",
    "girlfriend": "伴侣/对象", "boyfriend": "伴侣/对象",
}

INTIMATE_KEYWORDS = frozenset({
    "宝宝", "亲亲", "老婆", "老公", "爱你", "想你",
    "么么", "抱抱", "亲爱的", "宝贝",
})


class ContactRegistry:
    def __init__(self, filepath: str = "data/contacts.json") -> None:
        self.filepath = Path(filepath)
        self.contacts: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.filepath.exists():
            try:
                self.contacts = json.loads(self.filepath.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error("Failed to load contacts: %s", e)

    def save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.filepath.write_text(
            json.dumps(self.contacts, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def build_from_messages(self, messages: list[dict], contacts_db: list[dict]) -> None:
        msg_counts: Counter = Counter()
        for m in messages:
            talker = m.get("StrTalker", "")
            if talker:
                msg_counts[talker] += 1

        name_map: dict[str, dict] = {}
        for c in contacts_db:
            wxid = c.get("UserName", "")
            if wxid:
                name_map[wxid] = {
                    "nickname": c.get("NickName", "") or "",
                    "remark": c.get("Remark", "") or "",
                }

        for wxid, count in msg_counts.most_common():
            if wxid in self.contacts and not self.contacts[wxid].get("auto_detected", True):
                self.contacts[wxid]["message_count"] = count
                continue
            info = name_map.get(wxid, {})
            self.contacts[wxid] = {
                "wxid": wxid,
                "nickname": info.get("nickname", ""),
                "remark": info.get("remark", ""),
                "relationship": self._detect_relationship(wxid, messages, count),
                "message_count": count,
                "auto_detected": True,
                "chat_style": {},
            }
        self.save()
        logger.info("Built contact registry: %d contacts", len(self.contacts))

    def _detect_relationship(self, wxid: str, messages: list[dict], count: int) -> str:
        if "@chatroom" in wxid:
            return "group_chat"
        if "@openim" in wxid:
            return "service"
        intimate_score = 0
        for m in messages:
            if m.get("StrTalker") == wxid and m.get("IsSender") == 1:
                text = m.get("StrContent", "")
                if isinstance(text, bytes):
                    try:
                        text = text.decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                if not isinstance(text, str):
                    continue
                for kw in INTIMATE_KEYWORDS:
                    if kw in text:
                        intimate_score += 1
            if intimate_score > 30:
                break
        if intimate_score > 20 and count > 1000:
            return "partner"
        if count > 500:
            return "close_friend"
        if count > 50:
            return "friend"
        return "acquaintance"

    def get_display_name(self, wxid: str) -> str:
        e = self.contacts.get(wxid, {})
        return e.get("remark") or e.get("nickname") or wxid

    def get_relationship(self, wxid: str) -> str:
        return self.contacts.get(wxid, {}).get("relationship", "unknown")

    def get_relationship_label(self, wxid: str) -> str:
        return RELATIONSHIP_LABELS.get(self.get_relationship(wxid), "未知")

    def set_relationship(self, wxid: str, relationship: str) -> None:
        if wxid in self.contacts:
            self.contacts[wxid]["relationship"] = relationship
            self.contacts[wxid]["auto_detected"] = False
            self.save()

    def set_chat_style(self, wxid: str, style: dict) -> None:
        if wxid in self.contacts:
            self.contacts[wxid]["chat_style"] = style
            self.save()

    def get_top_contacts(self, n: int = 20) -> list[dict]:
        items = sorted(self.contacts.values(), key=lambda c: c.get("message_count", 0), reverse=True)
        return items[:n]

    def get_contact(self, wxid: str) -> dict:
        return self.contacts.get(wxid, {})

    def get_contact_context(self, wxid: str) -> dict:
        e = self.contacts.get(wxid, {})
        return {
            "wxid": wxid,
            "display_name": self.get_display_name(wxid),
            "relationship": e.get("relationship", "unknown"),
            "relationship_label": self.get_relationship_label(wxid),
            "chat_style": e.get("chat_style", {}),
        }

    def get_dropdown_choices(self) -> list[tuple]:
        top = self.get_top_contacts(30)
        choices = []
        for c in top:
            wxid = c["wxid"]
            name = self.get_display_name(wxid)
            label = self.get_relationship_label(wxid)
            count = c.get("message_count", 0)
            choices.append(("{} [{}] ({:,}条)".format(name, label, count), wxid))
        return choices

    def count(self) -> int:
        return len(self.contacts)

    def iter_partner_candidates(self, limit: int = 12) -> list[dict]:
        """Private-chat contacts ranked for「可能是对象」— AI 规则 + 消息量。"""
        items = [
            c for c in self.contacts.values()
            if c.get("wxid") and "@chatroom" not in c["wxid"] and "@openim" not in c["wxid"]
        ]

        def _rank(c: dict) -> tuple[int, int]:
            rel = c.get("relationship", "")
            tier = 0
            if rel == "partner":
                tier = 3
            elif rel in ("close_friend", "girlfriend", "boyfriend"):
                tier = 2
            elif rel == "friend":
                tier = 1
            return (tier, c.get("message_count", 0))

        items.sort(key=_rank, reverse=True)
        return items[:limit]
