"""
PromptBuilder — assembles system prompt from multi-MD guidance files + dynamic context.

Architecture (inspired by OpenClaw):
  Static layers  → loaded from data/guidance/*.md
  Dynamic layers → injected per-turn (memories, beliefs, emotion, inner thought)

Load priority:
  Tier 0 CRITICAL: rules.md, identity.md  (always full)
  Tier 1 HIGH:     style.md, thinking.md  (full, truncate if too long)
  Tier 2 MEDIUM:   emotion.md             (truncate to budget)
  Tier 3 DYNAMIC:  memories, beliefs, few-shot, emotion state, inner thought
"""
from __future__ import annotations

import re
from pathlib import Path

from src.personality.guidance import GuidanceManager


def _strip_markdown(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    return text


class PromptBuilder:
    def __init__(
        self,
        persona_profile: dict,
        cold_start_description: str = "",
        thinking_model: str = "",
        cognitive_profile: dict | None = None,
        emotion_boundaries: dict | list | None = None,
        emotion_expression: dict | None = None,
        guidance_dir: str = "data/guidance",
    ) -> None:
        self.profile = persona_profile
        self.cold_start = cold_start_description
        self.thinking_model = thinking_model
        self.cognitive_profile: dict = cognitive_profile or {}
        self.emotion_boundaries = emotion_boundaries or {}
        self.emotion_expression: dict = emotion_expression or {}
        self.guidance = GuidanceManager(guidance_dir)

        if not self.guidance.is_generated():
            self.guidance.generate_all(
                persona_profile=persona_profile,
                thinking_model=thinking_model,
                cognitive_profile=cognitive_profile,
                emotion_boundaries=emotion_boundaries,
                emotion_expression=emotion_expression,
            )

    def regenerate_guidance(self) -> None:
        self.guidance.generate_all(
            persona_profile=self.profile,
            thinking_model=self.thinking_model,
            cognitive_profile=self.cognitive_profile,
            emotion_boundaries=self.emotion_boundaries,
            emotion_expression=self.emotion_expression,
        )

    def build_system_prompt(
        self,
        retrieved_memories: str = "",
        retrieved_beliefs: str = "",
        episodic_memories: str = "",
        contact_context: dict | None = None,
        few_shot_examples: list[str] | None = None,
        emotion_prompt: str = "",
        emotion_transition: str = "",
        inner_thought: dict | None = None,
    ) -> str:
        parts: list[str] = []

        # ── Tier 0: CRITICAL — identity + contact context ──
        identity_md = self.guidance.load("identity")
        if identity_md:
            parts.append(identity_md)
        contact_block = self._build_contact_context(contact_context)
        if contact_block:
            parts.append(contact_block)
        parts.append("")

        # ── Tier 1: HIGH — thinking + style ──
        thinking_md = self.guidance.load("thinking")
        if thinking_md:
            parts.append(_strip_markdown(thinking_md))
            parts.append("")

        style_md = self.guidance.load("style")
        if style_md:
            parts.append(_strip_markdown(style_md))
            if self.cold_start:
                parts.append(f"- {self.cold_start}")
            parts.append("")

        # ── Tier 2: MEDIUM — emotion guidance ──
        emotion_md = self.guidance.load("emotion")
        if emotion_md:
            parts.append(_strip_markdown(emotion_md))
            parts.append("")

        # ── Tier 3: DYNAMIC — per-turn context ──

        if episodic_memories:
            parts.append("## 我的记忆（关于我自己的事实，可以自然地提起）")
            parts.append(episodic_memories)
            parts.append("")

        if retrieved_memories and retrieved_memories != "（没有找到相关记忆）":
            parts.append("## 相关对话片段")
            parts.append(retrieved_memories)
            parts.append("")

        if retrieved_beliefs and retrieved_beliefs != "（暂无已知立场）":
            parts.append("## 我的立场")
            parts.append(retrieved_beliefs)
            parts.append("")

        if few_shot_examples:
            parts.append(self._build_examples_section(few_shot_examples))
            parts.append("")

        # emotion state (after examples for recency bias)
        if emotion_prompt:
            parts.append(emotion_prompt)
            parts.append("")
        if emotion_transition:
            parts.append(emotion_transition)
            parts.append("")
        if inner_thought:
            parts.append(self._build_inner_thought_section(inner_thought))
            parts.append("")

        # ── Tier 0: CRITICAL — rules last (final authority) ──
        rules_md = self.guidance.load("rules")
        if rules_md:
            parts.append(_strip_markdown(rules_md))

        return "\n".join(parts)

    # ── helpers (still needed for dynamic content) ────────────────

    @staticmethod
    def _build_contact_context(contact_context: dict | None) -> str:
        if not contact_context:
            return ""
        lines = []
        name = contact_context.get("display_name", "对方")
        rel = contact_context.get("relationship_label", "")
        rel_key = contact_context.get("relationship", "unknown")

        if rel_key == "self":
            lines.append("你正在跟本人（也就是你自己的原型）对话。")
            lines.append("对方说的话你要认真听，用来校准和完善你对自己的认知。")
        elif rel_key == "stranger":
            lines.append("对方是陌生人，你不认识TA。")
        else:
            if name and name != "对方":
                lines.append(f"你现在在跟 {name} 聊天。")
            if rel:
                lines.append(f"TA是你的{rel}。")

        background = contact_context.get("background", "")
        if background:
            lines.append(f"你们的关系背景：{background}")
        style = contact_context.get("chat_style", {})
        summary = style.get("style_summary", "")
        if summary:
            lines.append(f"你们之间的聊天特点：{summary}")

        return "\n".join(lines)

    @staticmethod
    def _build_examples_section(examples: list[str]) -> str:
        lines = ["## 你的真实聊天记录"]
        lines.append("下面是你过去真实发的消息，模仿这个说话方式：")
        lines.append("")
        for i, ex in enumerate(examples, 1):
            lines.append(f"--- 样本{i} ---")
            lines.append(ex.strip())
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_inner_thought_section(thought: dict) -> str:
        my_feeling = thought.get("my_feeling", "")
        intensity = thought.get("feeling_intensity", 0)
        my_thought = thought.get("my_thought", "")

        if not my_feeling and not my_thought:
            return ""

        lines = ["## ⚡ 你此刻的内心反应（不要写出来，但必须按这个状态回复）"]

        if my_feeling:
            from src.personality.emotion_tracker import EMOTION_LABELS
            label = EMOTION_LABELS.get(my_feeling, my_feeling)
            lines.append(f"情绪：{label}（强度 {intensity:.1f}）")

        if my_thought:
            lines.append(f"内心独白：「{my_thought}」")

        lines.append("只输出回复本身。")
        return "\n".join(lines)
