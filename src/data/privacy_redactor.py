"""Privacy redaction engine with configurable rules and diff preview.

Supports built-in rules (phone, ID, email, wxid, bank card, transfer amounts)
and user-defined custom rules.  Provides both redacted output and a diff view
that highlights exactly what was replaced.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class RedactionRule:
    """A single redaction rule."""
    name: str
    pattern: re.Pattern
    replacement: str


@dataclass
class RedactionDiff:
    """One change made to a piece of text."""
    start: int
    end: int
    original: str
    replacement: str


# ── Built-in rules ──────────────────────────────────────────────────────────────

def _wxid(text: str) -> str:
    """Strip WeChat IDs (wxid_xxx, tencent_xxx, various openim IDs)."""
    return re.sub(
        r"\b(wxid_[a-z0-9]{5,32}|"
        r"gh_[a-z0-9]{5,32}|"
        r"\d{5,32}@openim|"
        r"[a-z][a-z0-9_]{5,30}@chatroom)\b",
        "[微信号]",
        text,
        flags=re.IGNORECASE,
    )


def _transfer(text: str) -> str:
    """Redact money transfer amounts."""
    return re.sub(
        r"(?:转账|红包|收款|付款)[^\n\d]{0,4}"
        r"(?:RMB|rmb|USD|\$|￥|€|£)?\s*"
        r"[\d,]+\.?\d*\s*"
        r"(?:元|块|美元|欧元|英镑)?",
        "[转账金额]",
        text,
    )


# ── PrivacyRedactor ────────────────────────────────────────────────────────────

class PrivacyRedactor:
    """Configurable PII redaction engine with diff preview.

    Example:
        redactor = PrivacyRedactor()
        redacted = redactor.redact("我的微信号是 wxid_abc123")
        diffs   = redactor.diff(original, redacted)
        print(diffs)  # [RedactionDiff(start=6, end=17, original='wxid_abc123', replacement='[微信号]')]
    """

    # Built-in rules (applied in order)
    # IMPORTANT: \b does NOT work next to Chinese characters (they are not part of
    # ASCII \w), so we use negative lookbehind/lookahead instead.
    BUILTIN_RULES: list[dict] = [
        {
            "name": "微信号",
            # {0,32} suffix: wxid_vivx=4, wxid_abc=3 均有效；排除纯 "wxid_"
            "pattern": r"(?<![a-zA-Z0-9_])(wxid_[a-z0-9_]{0,32}|gh_[a-z0-9_]{0,32}|\d{5,32}@openim|[a-z][a-z0-9_]{0,30}@chatroom)(?![a-zA-Z0-9_])",
            "replacement": "[微信号]",
            "flags": re.IGNORECASE,
        },
        {
            "name": "手机号",
            "pattern": r"(?<!\d)1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)",
            "replacement": "[手机号]",
            "flags": 0,
        },
        {
            "name": "身份证",
            "pattern": r"(?<!\d)\d{17}[\dXx](?![0-9])",
            "replacement": "[身份证号]",
            "flags": 0,
        },
        {
            "name": "邮箱",
            "pattern": r"(?<![a-zA-Z0-9_])[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}(?![a-zA-Z0-9_.%\-])",
            "replacement": "[邮箱]",
            "flags": 0,
        },
        {
            "name": "银行卡",
            # 13-19位连续数字（支持有/无分隔符）。16位标准卡：(\d{4}\D?){3}\d{4}，
            # 但需处理13-19位不等长的情况，用 {13,19} 连续数字更通用。
            "pattern": r"(?<!\d)\d{13,19}(?!\d)",
            "replacement": "[银行卡号]",
            "flags": 0,
        },
        {
            "name": "转账金额",
            "pattern": r"(?:转账|红包|收款|付款)[^\n\d]{0,4}(?:RMB|rmb|USD|\$|￥|€|£)?\s*[\d,]+\.?\d*\s*(?:元|块|美元|欧元|英镑)?",
            "replacement": "[转账金额]",
            "flags": 0,
        },
    ]

    def __init__(
        self,
        enabled_rules: list[str] | None = None,
        custom_rules: list[dict] | None = None,
    ) -> None:
        """Args:
            enabled_rules: list of rule names to activate (None = all built-in).
            custom_rules: extra rules in the same dict format as BUILTIN_RULES.
        """
        self._rules: list[RedactionRule] = []
        self._add_builtin_rules(enabled_rules)
        if custom_rules:
            self._add_custom_rules(custom_rules)

    def _add_builtin_rules(self, enabled: list[str] | None) -> None:
        for spec in self.BUILTIN_RULES:
            name = spec["name"]
            if enabled is not None and name not in enabled:
                continue
            flags = spec.get("flags", 0)
            self._rules.append(RedactionRule(
                name=name,
                pattern=re.compile(spec["pattern"], flags),
                replacement=spec["replacement"],
            ))

    def _add_custom_rules(self, rules: list[dict]) -> None:
        for spec in rules:
            flags = spec.get("flags", 0)
            self._rules.append(RedactionRule(
                name=spec.get("name", "custom"),
                pattern=re.compile(spec["pattern"], flags),
                replacement=spec.get("replacement", "[敏感信息]"),
            ))

    def add_rule(self, pattern: str, replacement: str, name: str = "custom",
                 flags: int = 0) -> None:
        """Add a new redaction rule at runtime."""
        self._rules.append(RedactionRule(
            name=name,
            pattern=re.compile(pattern, flags),
            replacement=replacement,
        ))

    def redact(self, text: str) -> str:
        """Apply all enabled rules and return the redacted text."""
        for rule in self._rules:
            text = rule.pattern.sub(rule.replacement, text)
        return text

    def diff(self, original: str, redacted: str) -> list[RedactionDiff]:
        """Return a list of changes between original and redacted text.

        Works by walking both strings simultaneously and collecting mismatches.
        """
        diffs: list[RedactionDiff] = []
        i = j = 0
        while i < len(original) or j < len(redacted):
            if i < len(original) and j < len(redacted) and original[i] == redacted[j]:
                i += 1
                j += 1
            else:
                # Collect the replacement run
                orig_run = []
                red_run = []
                orig_end = i
                red_end = j
                while orig_end < len(original) and (
                    orig_end >= len(redacted) or original[orig_end] != redacted[j]
                ):
                    orig_run.append(original[orig_end])
                    orig_end += 1
                while red_end < len(redacted) and (
                    red_end >= len(original) or redacted[red_end] != original[i]
                ):
                    red_run.append(redacted[red_end])
                    red_end += 1
                if orig_run or red_run:
                    diffs.append(RedactionDiff(
                        start=i,
                        end=orig_end,
                        original="".join(orig_run),
                        replacement="".join(red_run),
                    ))
                i = orig_end
                j = red_end
        return diffs

    def diff_html(self, original: str, redacted: str) -> str:
        """Return a human-readable HTML diff showing highlights."""
        diffs = self.diff(original, redacted)
        if not diffs:
            return f"<pre>{redacted}</pre>"
        # Build result by walking original and inserting highlights
        parts: list[str] = []
        pos = 0
        for d in diffs:
            if d.start > pos:
                parts.append(self._esc(original[pos:d.start]))
            parts.append(
                f'<span style="background:#fff3cd;padding:1px 2px;border-radius:2px" '
                f'title="替换为「{d.replacement}」">{self._esc(d.original)}</span>'
            )
            pos = d.end
        if pos < len(original):
            parts.append(self._esc(original[pos:]))
        return "<pre>" + "".join(parts) + "</pre>"

    @staticmethod
    def _esc(s: str) -> str:
        return (s
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>"))

    @property
    def enabled_rules(self) -> list[str]:
        return [r.name for r in self._rules]

    def __repr__(self) -> str:
        return f"PrivacyRedactor(rules={self.enabled_rules})"
