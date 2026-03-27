"""实时情绪追踪器。

根据对话上下文判断当前情绪状态，并从训练好的 emotion_profile 中
返回当前情绪下应有的说话风格和样本。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from src.personality.emotion_analyzer import _detect_emotion, EMOTION_KEYWORDS

logger = logging.getLogger(__name__)

EMOTION_LABELS = {
    "joy": "开心",
    "excitement": "兴奋",
    "touched": "感动",
    "gratitude": "感谢",
    "pride": "骄傲",
    "sadness": "难过",
    "anger": "生气",
    "anxiety": "焦虑",
    "disappointment": "失望",
    "wronged": "委屈",
    "coquettish": "撒娇",
    "jealousy": "吃醋",
    "heartache": "心疼",
    "longing": "思念",
    "curiosity": "好奇",
    "neutral": "平静",
}


class EmotionTracker:
    """Tracks emotional state during a conversation and provides
    emotion-aware context for prompt building."""

    def __init__(
        self,
        emotion_profile: dict,
        api_client=None,
        model: str | None = None,
    ) -> None:
        self.profile = emotion_profile
        self.api_client = api_client
        self.model = model
        self.current_emotion = "neutral"
        self.emotion_history: list[str] = []
        self.confidence = 0.0

    def update_from_history(self, chat_history: list[dict]) -> str:
        """Analyze recent chat history to determine current emotional state."""
        if not chat_history:
            self.current_emotion = "neutral"
            self.confidence = 0.0
            return self.current_emotion

        recent = chat_history[-8:]

        if self.api_client:
            try:
                formatted = self._format_messages_for_llm(recent)
                result = self._detect_emotion_llm(formatted)
                self.current_emotion = result["emotion"]
                self.confidence = result["confidence"]
                self.emotion_history.append(self.current_emotion)
                logger.debug(
                    "LLM emotion: %s (%.2f) - %s",
                    result["emotion"],
                    result["confidence"],
                    result.get("reason", ""),
                )
                return self.current_emotion
            except Exception:
                logger.warning(
                    "LLM emotion detection failed, falling back to keywords",
                    exc_info=True,
                )

        return self._update_from_history_keywords(recent)

    def _update_from_history_keywords(self, recent: list[dict]) -> str:
        """Keyword-based fallback for emotion detection."""
        scores: dict[str, float] = defaultdict(float)
        decay = 1.0
        for msg in reversed(recent):
            text = msg.get("content", "")
            role = msg.get("role", "")

            emo = _detect_emotion(text)
            if emo != "neutral":
                weight = decay * (1.5 if role == "user" else 1.0)
                scores[emo] += weight
            decay *= 0.7

        if not scores:
            self.current_emotion = "neutral"
            self.confidence = 0.0
            return "neutral"

        best_emo = max(scores, key=scores.get)
        total = sum(scores.values())
        self.confidence = scores[best_emo] / total if total > 0 else 0.0
        self.current_emotion = best_emo
        self.emotion_history.append(best_emo)

        return best_emo

    @staticmethod
    def _format_messages_for_llm(messages: list[dict]) -> str:
        """Convert message dicts into a readable conversation string."""
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            speaker = "对方" if role == "user" else "我"
            lines.append(f"{speaker}: {content}")
        return "\n".join(lines)

    _EMOTION_DETECT_PROMPT = (
        '你是一个中文情绪分析专家。请根据下面的对话上下文，判断「我」当前的情绪状态。\n'
        '\n'
        '可选情绪: joy, excitement, touched, gratitude, pride, sadness, anger, anxiety, disappointment, wronged, coquettish, jealousy, heartache, longing, curiosity, neutral\n'
        '\n'
        '重要提示：\n'
        '- 中文情绪表达往往很含蓄和间接。\n'
        '- 「嗯」单独出现可能代表冷淡；「哦」在对方长消息后可能代表敷衍/不满。\n'
        '- 「随便你」「你开心就好」往往是生气或冷淡，不是真的随意。\n'
        '- 要综合上下文判断，不要只看单条消息。\n'
        '\n'
        '请只输出一个JSON对象，不要输出其他内容：\n'
        '{"emotion": "xxx", "confidence": 0.0-1.0, "reason": "简短说明"}\n'
        '\n'
        '对话内容：\n'
    )

    def _detect_emotion_llm(self, conversation: str) -> dict:
        """Use LLM to classify the emotional state from conversation context.

        Returns dict with keys: emotion, confidence, reason.
        """
        prompt = self._EMOTION_DETECT_PROMPT + conversation

        response = self.api_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=150,
        )

        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)

        valid_emotions = {
            "joy", "excitement", "touched", "gratitude", "pride",
            "sadness", "anger", "anxiety", "disappointment", "wronged",
            "coquettish", "jealousy", "heartache", "longing",
            "curiosity", "neutral",
        }
        if result.get("emotion") not in valid_emotions:
            result["emotion"] = "neutral"
        result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.5))))

        return result

    _NEGATIVE_EMOTIONS = {
        "sadness", "anger", "anxiety", "disappointment", "wronged", "jealousy",
    }
    _POSITIVE_EMOTIONS = {"joy", "excitement", "touched", "gratitude", "pride"}

    _CONTAGION_WEIGHTS = {"none": 0.0, "slight": 0.15, "moderate": 0.35, "strong": 0.6}

    def set_reactive_emotion(
        self,
        emotion: str,
        confidence: float = 0.8,
        their_emotion: str | None = None,
        contagion: str = "slight",
    ) -> None:
        """Set emotion based on inner-thinking appraisal result.

        Applies three cognitive science principles:
        1. Markov momentum — previous emotion biases current state.
           Negative emotions have higher inertia (decay 0.4 vs 0.2).
        2. Emotional contagion — other person's emotion shifts ours,
           weighted by relationship closeness (contagion level).
        3. Intensity tracking — blended confidence reflects conviction.
        """
        if emotion not in {
            "joy", "excitement", "touched", "gratitude", "pride",
            "sadness", "anger", "anxiety", "disappointment", "wronged",
            "coquettish", "jealousy", "heartache", "longing",
            "curiosity", "neutral",
        }:
            return

        prev = self.current_emotion

        # --- Markov momentum: negative emotions resist change ---
        if prev != emotion and prev in self._NEGATIVE_EMOTIONS:
            inertia = 0.40
            if confidence < inertia:
                emotion = prev
                logger.debug("Markov inertia kept negative emotion %s", prev)
        elif prev != emotion and prev in self._POSITIVE_EMOTIONS:
            inertia = 0.20
            if confidence < inertia:
                emotion = prev

        # --- Emotional contagion: their emotion shifts ours ---
        if their_emotion and their_emotion in {
            "joy", "excitement", "touched", "gratitude", "pride",
            "sadness", "anger", "anxiety", "disappointment", "wronged",
            "coquettish", "jealousy", "heartache", "longing",
            "curiosity",
        }:
            cw = self._CONTAGION_WEIGHTS.get(contagion, 0.15)
            if cw > 0 and their_emotion != emotion:
                if their_emotion in self._POSITIVE_EMOTIONS:
                    cw *= 1.5
                elif their_emotion in self._NEGATIVE_EMOTIONS:
                    cw *= 0.8
                if cw >= 0.3 and confidence < 0.5:
                    emotion = their_emotion
                    confidence = cw
                    logger.debug("Contagion override: now %s (weight %.2f)", emotion, cw)

        self.current_emotion = emotion
        self.confidence = max(0.0, min(1.0, confidence))
        self.emotion_history.append(emotion)
        if prev != emotion:
            logger.debug("Reactive emotion: %s -> %s (confidence %.2f)", prev, emotion, confidence)

    def detect_other_emotion(self, message: str) -> str:
        """Detect what emotion the OTHER person is expressing."""
        return _detect_emotion(message)

    def get_emotion_prompt(self) -> str:
        """Generate emotion-aware prompt section based on current state."""
        emo = self.current_emotion
        if not self.profile:
            return ""

        styles = self.profile.get("emotion_styles", {})

        if emo == "neutral":
            neutral_style = styles.get("neutral", {})
            lines = ["## 当前情绪状态：日常/平静"]
            lines.append("- 你现在心情平静，但你是活人，不是机器。说话自然带语气词（嗯、哦、啊、哈），不要太正式")
            top_words = neutral_style.get("top_words", [])
            if top_words:
                lines.append(f"- 你日常最常用的词：{'、'.join(top_words[:8])}")
            samples = neutral_style.get("samples", [])
            if samples:
                lines.append("")
                lines.append("你平时说话的真实样本（模仿这个语气）：")
                for s in samples[:5]:
                    lines.append(f"  「{s}」")
            return "\n".join(lines)

        style = styles.get(emo, {})
        if not style:
            return ""

        label = EMOTION_LABELS.get(emo, emo)
        lines = [f"## 当前情绪状态：{label}"]

        avg_len = style.get("avg_length", 0)
        short_pct = style.get("short_message_pct", 0)
        emoji_rate = style.get("emoji_rate", 0)

        if short_pct > 70:
            lines.append(f"- 这种情绪下你消息极短（平均{avg_len:.0f}字），不要写长句")
        elif avg_len > 0:
            lines.append(f"- 这种情绪下你消息平均{avg_len:.0f}字")

        if emoji_rate > 0.1:
            lines.append("- 这种情绪下你会用表情")
        elif emoji_rate < 0.02:
            lines.append("- 这种情绪下你很少用表情")

        top_words = style.get("top_words", [])
        if top_words:
            lines.append(f"- 这种情绪下你常说：{'、'.join(top_words[:8])}")

        samples = style.get("samples", [])
        if samples:
            lines.append("")
            lines.append(f"你在{label}时真实的回复（直接模仿）：")
            for s in samples[:8]:
                lines.append(f"  「{s}」")

        lines.append("")
        lines.append(f"按上面{label}时的真实样本说话，模仿那个语气和用词")

        return "\n".join(lines)

    def get_emotion_transition_hint(self) -> str:
        """If emotion recently changed, provide transition guidance."""
        if len(self.emotion_history) < 2:
            return ""

        prev = self.emotion_history[-2]
        curr = self.emotion_history[-1]
        if prev == curr:
            return ""

        prev_label = EMOTION_LABELS.get(prev, prev)
        curr_label = EMOTION_LABELS.get(curr, curr)

        transition_hints = {
            ("anger", "coquettish"): "你刚从生气转为撒娇，过渡要自然，不要突然翻脸",
            ("anger", "neutral"): "你刚消气，语气回归正常但不要太热情",
            ("sadness", "joy"): "你心情好转了，但不要一下跳太开心",
            ("longing", "joy"): "你从思念转为开心，可能对方回来了或联系了",
            ("coquettish", "anger"): "你刚从撒娇变生气，说明触碰到底线了，语气要明显变冷",
            ("disappointment", "longing"): "你从失望转为思念，是在慢慢软化",
            ("neutral", "anger"): "你突然生气了，一定是对方说了让你不爽的话",
            ("wronged", "anger"): "你从委屈变成了生气，情绪在升级",
            ("jealousy", "coquettish"): "你从吃醋变撒娇，在用可爱方式表达不安",
        }

        hint = transition_hints.get((prev, curr))
        if not hint:
            hint = f"你的情绪从{prev_label}转为{curr_label}，过渡要自然"

        return f"[情绪变化：{prev_label} → {curr_label}] {hint}"
