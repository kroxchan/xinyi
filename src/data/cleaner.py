"""Comprehensive message cleaning pipeline.

Runs in order: decode → drop garbage → strip noise → strip wxid prefix →
drop system messages → redact PII → emit stats.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rich.console import Console

console = Console()

# ---------------------------------------------------------------------------
# PII redaction patterns
# ---------------------------------------------------------------------------
PHONE_RE = re.compile(r"1[3-9]\d[\s-]?\d{4}[\s-]?\d{4}")
ID_CARD_RE = re.compile(r"\b\d{17}[\dXx]\b")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# ---------------------------------------------------------------------------
# System / non-content keyword list
# ---------------------------------------------------------------------------
SYSTEM_KEYWORDS: list[str] = [
    "撤回了一条消息",
    "收到红包", "领取了你的红包", "领取了红包",
    "拍了拍",
    "邀请你加入了群聊", "邀请\"", "移出了群聊",
    "修改群名为", "群公告",
    "你已添加了", "我通过了你的朋友验证", "以上是打招呼的内容",
    "你通过扫描二维码",
    "发起了位置共享", "发起了语音通话", "发起了视频通话",
    "以下是新消息",
    "分享的名片",
    "加入了群聊", "退出了群聊",
    "开启了朋友验证", "已恢复了默认进群方式",
    "向你推荐了", "收到一条暗号消息",
    "此为系统自动报备", "系统自动报备",
]

SYSTEM_START_PATTERNS: list[str] = [
    "<msg", "<sysmsg", "<?xml",
]

# wxid:\n prefix injected by WeChat in group chat content
# Covers: wxid_xxx:\n, wxid_xxx:\r\n, digits@openim:\n, plain_id:\n
WXID_PREFIX_RE = re.compile(
    r"^(?:wxid_[a-z0-9]+|\d+@openim|[a-z][a-z0-9_]{5,}):\s*\n",
    re.IGNORECASE,
)

# Pure emoji like [旺柴] [捂脸] [微笑]
PURE_EMOJI_RE = re.compile(r"^(\[[\u4e00-\u9fff\w]+\]\s*)+$")

# Pure URL
PURE_URL_RE = re.compile(r"^https?://\S+$")

# Zstd magic bytes (binary garbage that leaked through as str repr)
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# Control characters (excluding \n \r \t) — indicates binary garbage decoded as str
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

KEEP_FIELDS = {"MsgSvrID", "IsSender", "StrTalker", "StrContent", "CreateTime"}


@dataclass
class CleanStats:
    """Tracks how many messages were dropped and why."""
    total_input: int = 0
    dropped_non_text_type: int = 0
    dropped_binary: int = 0
    dropped_empty: int = 0
    dropped_system: int = 0
    dropped_pure_emoji: int = 0
    dropped_pure_url: int = 0
    dropped_too_short: int = 0
    stripped_wxid_prefix: int = 0
    redacted_pii: int = 0
    total_output: int = 0

    def summary_lines(self) -> list[str]:
        lines = []
        dropped = self.total_input - self.total_output
        lines.append(f"输入 {self.total_input:,} → 输出 {self.total_output:,}（过滤 {dropped:,}）")
        if self.dropped_binary:
            lines.append(f"  · 二进制/乱码: -{self.dropped_binary:,}")
        if self.dropped_non_text_type:
            lines.append(f"  · 非文本类型: -{self.dropped_non_text_type:,}")
        if self.dropped_system:
            lines.append(f"  · 系统消息: -{self.dropped_system:,}")
        if self.dropped_pure_emoji:
            lines.append(f"  · 纯表情: -{self.dropped_pure_emoji:,}")
        if self.dropped_pure_url:
            lines.append(f"  · 纯链接: -{self.dropped_pure_url:,}")
        if self.dropped_empty:
            lines.append(f"  · 空/过短: -{self.dropped_empty:,}")
        if self.dropped_too_short:
            lines.append(f"  · 单字无意义: -{self.dropped_too_short:,}")
        if self.stripped_wxid_prefix:
            lines.append(f"  · 群聊wxid前缀已清除: {self.stripped_wxid_prefix:,}")
        if self.redacted_pii:
            lines.append(f"  · PII脱敏: {self.redacted_pii:,}")
        return lines


class MessageCleaner:

    def __init__(self, min_content_len: int = 1, strip_pure_emoji: bool = True) -> None:
        self.min_content_len = min_content_len
        self.strip_pure_emoji = strip_pure_emoji
        self.last_stats: CleanStats | None = None

    # ------------------------------------------------------------------
    # Stage 1: Decode bytes → str, drop undecodable
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_content(content) -> str | None:
        if isinstance(content, bytes):
            if content[:4] == ZSTD_MAGIC:
                return None
            try:
                return content.decode("utf-8", errors="ignore")
            except Exception:
                return None
        if isinstance(content, str):
            if content.startswith("b'") or content.startswith('b"'):
                return None
            return content
        return None

    # ------------------------------------------------------------------
    # Stage 2: Detect system messages
    # ------------------------------------------------------------------
    @staticmethod
    def _is_system_message(content: str) -> bool:
        for kw in SYSTEM_KEYWORDS:
            if kw in content:
                return True
        stripped = content.lstrip()
        for pat in SYSTEM_START_PATTERNS:
            if stripped.startswith(pat):
                return True
        return False

    # ------------------------------------------------------------------
    # Stage 3: Strip wxid:\n prefix from group chat messages
    # ------------------------------------------------------------------
    @staticmethod
    def _strip_wxid_prefix(content: str) -> tuple[str, bool]:
        m = WXID_PREFIX_RE.match(content)
        if m:
            return content[m.end():], True
        return content, False

    # ------------------------------------------------------------------
    # Stage 4: Redact PII
    # ------------------------------------------------------------------
    @staticmethod
    def _redact(text: str) -> tuple[str, bool]:
        changed = False
        for pattern in (PHONE_RE, EMAIL_RE, ID_CARD_RE):
            new_text = pattern.sub("[REDACTED]", text)
            if new_text != text:
                changed = True
                text = new_text
        return text, changed

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------
    def clean_messages(self, messages: list[dict]) -> list[dict]:
        stats = CleanStats(total_input=len(messages))
        cleaned: list[dict] = []

        for msg in messages:
            if msg.get("type", 0) != 1:
                stats.dropped_non_text_type += 1
                continue

            raw_content = msg.get("StrContent", "")
            content = self._decode_content(raw_content)
            if content is None:
                stats.dropped_binary += 1
                continue

            content = content.strip()
            if not content:
                stats.dropped_empty += 1
                continue

            if CONTROL_CHAR_RE.search(content):
                stats.dropped_binary += 1
                continue

            if self._is_system_message(content):
                stats.dropped_system += 1
                continue

            content, did_strip = self._strip_wxid_prefix(content)
            if did_strip:
                stats.stripped_wxid_prefix += 1
                content = content.strip()

            if self.strip_pure_emoji and PURE_EMOJI_RE.match(content):
                stats.dropped_pure_emoji += 1
                continue

            if PURE_URL_RE.match(content):
                stats.dropped_pure_url += 1
                continue

            if len(content) < self.min_content_len:
                stats.dropped_too_short += 1
                continue

            content, did_redact = self._redact(content)
            if did_redact:
                stats.redacted_pii += 1

            out = {k: v for k, v in msg.items() if k in KEEP_FIELDS}
            out["StrContent"] = content
            cleaned.append(out)

        stats.total_output = len(cleaned)
        self.last_stats = stats

        for line in stats.summary_lines():
            console.print(f"[green]{line}[/green]")

        return cleaned
