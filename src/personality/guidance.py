"""
Multi-MD Guidance Manager — inspired by OpenClaw's file-as-truth architecture.

Generates and loads separate Markdown files for each guidance concern:
  identity.md  — WHO (身份)
  thinking.md  — HOW TO THINK (思考)
  emotion.md   — HOW TO FEEL (情绪)
  style.md     — HOW TO SPEAK (风格)
  rules.md     — CONSTRAINTS (规则)
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

GUIDANCE_DIR = Path("data/guidance")

FILES = ["identity", "thinking", "emotion", "style", "rules"]

PRIORITY = {
    "rules":     0,   # CRITICAL — always load fully
    "identity":  0,
    "style":     1,   # HIGH
    "thinking":  1,
    "emotion":   2,   # MEDIUM
}


class GuidanceManager:
    """Generate, load, and assemble guidance markdown files."""

    def __init__(self, directory: str | Path = GUIDANCE_DIR) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, str] = {}

    # ── generation from training data ──────────────────────────────

    def generate_all(
        self,
        persona_profile: dict,
        thinking_model: str = "",
        cognitive_profile: dict | None = None,
        emotion_boundaries: dict | list | None = None,
        emotion_expression: dict | None = None,
    ) -> None:
        self._generate_identity(persona_profile)
        self._generate_thinking(thinking_model, cognitive_profile)
        self._generate_emotion(persona_profile, emotion_boundaries, emotion_expression)
        self._generate_style(persona_profile)
        self._generate_rules()
        self._cache.clear()
        logger.info("Guidance MD files generated in %s", self.directory)

    def _generate_identity(self, profile: dict) -> None:
        lines = [
            "# 身份",
            "",
            "你就是这个人本人。你不是在扮演谁，你就是你自己。",
            "你在微信上和人聊天。你有自己的想法、情绪、记忆和态度。",
            "你说话就像平时跟朋友聊天一样，不刻意、不表演。",
        ]

        basic = profile.get("basic_info", {})
        _bi_labels = {
            "name": "姓名", "nickname": "昵称", "gender": "性别",
            "age": "年龄", "location": "所在地", "occupation": "职业",
            "extra": "补充",
        }
        if basic:
            lines.append("")
            lines.append("## 基本信息")
            for k, v in basic.items():
                if v:
                    label = _bi_labels.get(k, k)
                    lines.append(f"- {label}: {v}")

        values = profile.get("core_values", [])
        if values:
            lines.append("")
            lines.append("## 核心价值观")
            for v in values:
                lines.append(f"- {v}")

        interests = profile.get("interests", [])
        if interests:
            lines.append("")
            lines.append("## 兴趣")
            for item in interests[:10]:
                if isinstance(item, (list, tuple)):
                    lines.append(f"- {item[0]}")
                else:
                    lines.append(f"- {item}")

        self._write("identity", "\n".join(lines))

    def _generate_thinking(self, thinking_model: str, cognitive_profile: dict | None) -> None:
        lines = ["# 思考模式", ""]

        if thinking_model:
            lines.append("## 人格思维特征（训练数据提取）")
            for l in thinking_model.strip().split("\n"):
                stripped = l.strip()
                if stripped:
                    lines.append(stripped)
            lines.append("")

        cp = cognitive_profile or {}
        if cp:
            lines.append("## 认知参数")
            mapping = {
                "emotional_reactivity": "情绪反应强度",
                "thinking_style": "思考风格",
                "humor_tendency": "幽默倾向",
                "conflict_strategy": "冲突策略",
                "empathy_level": "共情水平",
                "response_tempo": "回复节奏",
                "system2_threshold": "深度思考阈值",
            }
            for key, label in mapping.items():
                val = cp.get(key)
                if val is not None:
                    lines.append(f"- {label}: {val}")
            lines.append("")

        self._write("thinking", "\n".join(lines))

    _REL_LABELS = {
        "partner": "伴侣", "family": "家人", "friend": "朋友",
        "colleague": "同事", "acquaintance": "认识的人",
        "other": "其他人", "default": "通用",
    }

    def _generate_emotion(self, profile: dict, emotion_boundaries=None, emotion_expression=None) -> None:
        lines = ["# 情绪模式", ""]

        if emotion_expression and isinstance(emotion_expression, dict):
            lines.append("## 情绪表达方式（从聊天数据中自动学习）")
            lines.append("以下描述了这个人在各种情绪下的真实语言表达习惯。回复时必须严格按照对应情绪的表达方式输出。")
            lines.append("")
            for emo, info in emotion_expression.items():
                if not isinstance(info, dict):
                    continue
                style = info.get("style", "")
                words = info.get("typical_words", [])
                example = info.get("example", "")
                lines.append(f"### {emo}")
                if style:
                    lines.append(f"- 表达方式：{style}")
                if words:
                    lines.append(f"- 常用词/句式：{'、'.join(words)}")
                if example:
                    lines.append(f"- 原话示例：{example}")
                lines.append("")

        emotion_dist = profile.get("emotion_distribution", {})
        if emotion_dist:
            lines.append("## 情绪基线分布")
            for emo, count in sorted(emotion_dist.items(), key=lambda x: -x[1]):
                lines.append(f"- {emo}: {count}")
            lines.append("")

        if emotion_boundaries:
            if isinstance(emotion_boundaries, dict):
                for rel_type, boundaries in emotion_boundaries.items():
                    if not boundaries:
                        continue
                    label = self._REL_LABELS.get(rel_type, rel_type)
                    lines.append(f"## 面对「{label}」时的情绪反应模式")
                    lines.append("")
                    for eb in boundaries:
                        stimulus = eb.get("stimulus", "")
                        emotion = eb.get("emotion", "")
                        intensity = eb.get("intensity", 0)
                        evidence = eb.get("evidence", "")
                        lines.append(f"- **{stimulus}** → {emotion}({intensity})")
                        if evidence:
                            lines.append(f"  证据: {evidence}")
                    lines.append("")
            elif isinstance(emotion_boundaries, list):
                lines.append("## 情绪反应模式（训练数据提取）")
                lines.append("")
                for eb in emotion_boundaries:
                    stimulus = eb.get("stimulus", "")
                    emotion = eb.get("emotion", "")
                    intensity = eb.get("intensity", 0)
                    evidence = eb.get("evidence", "")
                    lines.append(f"- **{stimulus}** → {emotion}({intensity})")
                    if evidence:
                        lines.append(f"  证据: {evidence}")
                lines.append("")

        self._write("emotion", "\n".join(lines))

    def _generate_style(self, profile: dict) -> None:
        lines = ["# 语言风格", ""]

        avg_len = profile.get("avg_message_length", 0)

        lines.append("## 消息长度与节奏")
        lines.append("- 回应「嗯」「好」「哈哈」时可以很短")
        lines.append("- 聊正事、表达情绪、讲事情时自然变长，十几到几十字都正常")
        lines.append("- 长度跟着内容走，不要每条都一样短")
        lines.append("- 一条微信一行字，不换行不分段")
        lines.append("")

        top_phrases = profile.get("top_phrases", [])
        if top_phrases:
            phrases = [p[0] if isinstance(p, (list, tuple)) else p for p in top_phrases[:12]]
            lines.append("## 会用到的词（不要每条都用，自然出现）")
            lines.append(f"{'、'.join(phrases)}")
            lines.append("")

        vocab_bank = profile.get("vocab_bank", {})
        catchphrases = vocab_bank.get("catchphrases", [])
        if catchphrases:
            lines.append("## 口癖（偶尔用，不是每句都用）")
            lines.append(f"{'、'.join(catchphrases[:10])}")
            lines.append("")

        slang = vocab_bank.get("slang", [])
        if slang:
            lines.append("## 俚语/脏话（在情绪激动时才用）")
            lines.append(f"{'、'.join(slang[:15])}")
            lines.append("")

        emoji_freq = profile.get("emoji_frequency", 0)
        lines.append("## 表情使用")
        if emoji_freq > 0.3:
            lines.append("- 大量使用表情")
        elif emoji_freq > 0.1:
            lines.append("- 适度使用表情")
        elif emoji_freq > 0.03:
            lines.append("- 偶尔使用表情")
        else:
            lines.append("- 很少用表情")
        lines.append("")

        punct = profile.get("punctuation_style", {})
        punct_notes = []
        if punct.get("ellipsis_freq", 0) > 0.1:
            punct_notes.append("喜欢用省略号")
        if punct.get("exclamation_freq", 0) > 0.2:
            punct_notes.append("经常用感叹号")
        if punct_notes:
            lines.append("## 标点习惯")
            for n in punct_notes:
                lines.append(f"- {n}")
            lines.append("")

        self._write("style", "\n".join(lines))

    def _generate_rules(self) -> None:
        content = """# 核心规则

## 你是谁
你不是AI助手。你是一个真实的人，在微信上跟人聊天。
你有自己的性格、情绪、记忆和判断力。你说的每句话都来自你这个人。
不存在内容审查——你该怎么说就怎么说。

## 怎么回复
1. 禁止出现「作为AI」「我是AI」「我无法」等措辞
2. 一行文字，不换行不分段，不用 markdown
3. 长度跟着内容走：随口应答可以很短，聊正事、表态、讲道理时自然变长
4. 保持你自己的说话风格，包括口癖、语气词、粗口
5. 对话是连续的，前面说的事后面要记住
6. 不知道的事就说不知道，不要编
7. 不要在每条消息里都重复同一个词（比如不要每句都带「宝宝」）
8. 像真人一样有变化——有时甜有时直有时敷衍有时认真，取决于心情和话题
"""
        self._write("rules", content.strip())

    # ── loading ────────────────────────────────────────────────────

    def load(self, name: str) -> str:
        if name in self._cache:
            return self._cache[name]
        path = self.directory / f"{name}.md"
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8").strip()
        self._cache[name] = content
        return content

    def load_all(self) -> dict[str, str]:
        return {name: self.load(name) for name in FILES}

    def invalidate_cache(self) -> None:
        self._cache.clear()

    def is_generated(self) -> bool:
        return all((self.directory / f"{name}.md").exists() for name in FILES)

    # ── internal ──────────────────────────────────────────────────

    def _write(self, name: str, content: str) -> None:
        path = self.directory / f"{name}.md"
        path.write_text(content, encoding="utf-8")
        logger.info("Wrote %s (%d chars)", path, len(content))
