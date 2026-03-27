"""从聊天记录中训练情绪模型。

训练后生成 emotion_profile.yaml，包含：
- 每种情绪下的说话风格（消息长度、表情使用、常用词）
- 每种情绪的真实回复样本
- 情绪转换模式（生气后多久恢复，什么让你从开心变难过）
- 情绪触发条件（对方说什么会触发你什么情绪）
"""

from __future__ import annotations

import logging
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

EMOTION_KEYWORDS: dict[str, list[str]] = {
    "joy": [
        "哈哈", "哈哈哈", "666", "牛", "太好了", "开心", "好棒",
        "哈哈哈哈", "厉害", "耶", "好开心", "嘻嘻", "美滋滋",
    ],
    "excitement": [
        "冲", "太棒了", "等不及", "好期待", "兴奋", "燃", "冲冲冲",
        "激动", "终于", "好激动", "啊啊啊",
    ],
    "touched": [
        "感动", "好暖", "暖心", "泪目", "哭了", "太感动", "破防了",
        "戳心", "心里暖暖的",
    ],
    "gratitude": [
        "谢谢", "感谢", "多谢", "辛苦了", "太感谢", "谢谢你",
        "真的谢谢", "感恩", "thanks",
    ],
    "pride": [
        "骄傲", "自豪", "厉害了", "太牛了", "给你点赞", "真棒",
        "为你骄傲", "好厉害",
    ],
    "sadness": [
        "难过", "想哭", "心累", "心碎", "伤心", "哭了", "好难过",
        "崩溃", "绝望", "呜呜",
    ],
    "anger": [
        "烦", "无语", "服了", "够了", "你烦不烦", "离谱", "受不了",
        "搞什么", "神经", "有毛病", "烦死了", "气死", "滚",
    ],
    "anxiety": [
        "怎么办", "担心", "焦虑", "紧张", "急", "害怕", "不安",
        "慌了", "压力大", "怕",
    ],
    "disappointment": [
        "失望", "白期待了", "还以为", "本以为", "算了吧",
        "没意思", "不过如此", "唉",
    ],
    "wronged": [
        "委屈", "凭什么", "冤枉", "不公平", "为什么要这样",
        "我做错了什么", "被误解", "好委屈",
    ],
    "coquettish": [
        "宝宝", "人家", "嘤嘤嘤", "哼", "讨厌", "你说嘛",
        "不嘛", "求求了", "嘤", "呜呜呜", "哄哄我",
    ],
    "jealousy": [
        "吃醋", "嫉妒", "你和谁", "不许", "哼",
        "你是不是有别人了", "少跟她聊", "醋意",
    ],
    "heartache": [
        "心疼", "好心疼", "疼", "别太累", "照顾好自己",
        "看着都疼", "你辛苦了", "受苦了",
    ],
    "longing": [
        "想你", "好想你", "想见你", "什么时候回来", "快回来",
        "好久没见", "想死你了", "miss", "念你",
    ],
    "curiosity": [
        "为什么", "怎么回事", "然后呢", "什么意思", "真的吗",
        "讲讲", "细说", "好奇",
    ],
}

EMOJI_PATTERN = re.compile(r"\[[\u4e00-\u9fff\w]+\]")

# Control characters that indicate binary garbage (exclude \n \r \t)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Shared stopwords for top_words filtering
_STOPWORDS: set[str] = {
    "的", "了", "是", "在", "我", "你", "他", "她", "这", "那",
    "有", "不", "就", "也", "都", "把", "被", "给", "让", "对",
    "和", "与", "或", "而", "但", "却", "又", "再", "还", "很",
    "最", "会", "能", "要", "去", "来", "到", "说", "看", "着",
    "过", "吗", "吧", "呢", "啊", "哦", "嗯", "呀", "哈", "嘛",
    "么", "啦", "哪", "谁", "几", "多", "些", "这个", "那个",
    "什么", "怎么", "可以", "没有", "不了", "就是", "一个",
    "知道", "觉得", "然后", "但是", "因为", "所以", "还是",
    "已经", "应该", "可能", "或者", "如果", "虽然", "不过",
    "自己", "它", "们", "地", "得",
    "系统", "自动", "报备", "此为", "此为系统自动报备", "系统自动报备",
}


def _is_clean_text(text: str) -> bool:
    """Check if text is clean (no binary garbage, no control chars, no wxid prefix)."""
    if not isinstance(text, str) or not text.strip():
        return False
    if _CONTROL_CHAR_RE.search(text):
        return False
    if text.startswith("b'") or text.startswith('b"'):
        return False
    return True


def _detect_emotion(text: str) -> str:
    """Classify a single message's emotion. Returns the dominant emotion."""
    if not isinstance(text, str):
        return "neutral"

    scores: dict[str, float] = defaultdict(float)
    text_lower = text.lower()

    for emotion, keywords in EMOTION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                weight = len(kw) / 2.0
                scores[emotion] += weight

    if not scores:
        return "neutral"

    return max(scores, key=scores.get)


class EmotionAnalyzer:
    """Trains an emotion profile from chat history."""

    def __init__(self) -> None:
        self.profile: dict = {}

    def train(self, messages: list[dict], twin_mode: str = "self") -> dict:
        """Analyze messages and build a comprehensive emotion profile."""
        target_sender = 0 if twin_mode == "partner" else 1
        my_msgs = [m for m in messages if m.get("IsSender") == target_sender]

        emotion_buckets: dict[str, list[dict]] = defaultdict(list)
        for m in my_msgs:
            text = m.get("StrContent", "")
            if isinstance(text, bytes):
                try:
                    text = text.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            if not _is_clean_text(text):
                continue
            emo = _detect_emotion(text)
            emotion_buckets[emo].append({
                "text": text,
                "time": m.get("CreateTime", 0),
                "talker": m.get("StrTalker", ""),
            })

        profile = {
            "total_analyzed": len(my_msgs),
            "emotion_distribution": {},
            "emotion_styles": {},
            "emotion_transitions": {},
            "emotion_triggers": {},
        }

        for emo, bucket in emotion_buckets.items():
            profile["emotion_distribution"][emo] = len(bucket)
            profile["emotion_styles"][emo] = self._analyze_style(bucket)

        profile["emotion_transitions"] = self._analyze_transitions(my_msgs)
        profile["emotion_triggers"] = self._analyze_triggers(messages, twin_mode)

        self.profile = profile
        return profile

    def _analyze_style(self, bucket: list[dict]) -> dict:
        """Build style profile for one emotion category."""
        texts = [b["text"] for b in bucket]
        lengths = [len(t) for t in texts]
        avg_len = sum(lengths) / len(lengths) if lengths else 0

        emoji_count = sum(len(EMOJI_PATTERN.findall(t)) for t in texts)
        emoji_rate = emoji_count / len(texts) if texts else 0

        word_counter: Counter = Counter()
        for t in texts:
            segs = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+|\[[\u4e00-\u9fff\w]+\]", t)
            for seg in segs:
                if len(seg) >= 2 and seg not in _STOPWORDS:
                    word_counter[seg] += 1

        top_words = [w for w, _ in word_counter.most_common(15)]

        random.seed(42)
        good_samples = [t for t in texts if 2 <= len(t) <= 50 and _is_clean_text(t)]
        samples = random.sample(good_samples, min(20, len(good_samples)))

        short_pct = sum(1 for ln in lengths if ln <= 6) / len(lengths) * 100 if lengths else 0

        return {
            "count": len(bucket),
            "avg_length": round(avg_len, 1),
            "short_message_pct": round(short_pct, 1),
            "emoji_rate": round(emoji_rate, 3),
            "top_words": top_words,
            "samples": samples,
        }

    def _analyze_transitions(self, my_msgs: list[dict]) -> dict:
        """Analyze how emotions transition over time."""
        sorted_msgs = sorted(my_msgs, key=lambda m: m.get("CreateTime", 0))

        transitions: Counter = Counter()
        prev_emo = "neutral"
        for m in sorted_msgs:
            text = m.get("StrContent", "")
            if isinstance(text, bytes):
                try:
                    text = text.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            if not _is_clean_text(text):
                continue
            emo = _detect_emotion(text)
            if emo != prev_emo:
                transitions[f"{prev_emo}->{emo}"] += 1
            prev_emo = emo

        top_transitions = transitions.most_common(15)
        return {t: c for t, c in top_transitions}

    def _analyze_triggers(self, all_messages: list[dict], twin_mode: str = "self") -> dict:
        """Analyze what the OTHER person says before the twin's emotional responses."""
        sorted_msgs = sorted(all_messages, key=lambda m: m.get("CreateTime", 0))
        twin_sender = 0 if twin_mode == "partner" else 1
        other_sender = 1 if twin_mode == "partner" else 0

        triggers: dict[str, list[str]] = defaultdict(list)

        for i in range(1, len(sorted_msgs)):
            curr = sorted_msgs[i]
            prev = sorted_msgs[i - 1]

            if curr.get("IsSender") != twin_sender or prev.get("IsSender") != other_sender:
                continue

            my_text = curr.get("StrContent", "")
            other_text = prev.get("StrContent", "")
            if isinstance(my_text, bytes):
                try:
                    my_text = my_text.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            if isinstance(other_text, bytes):
                try:
                    other_text = other_text.decode("utf-8", errors="ignore")
                except Exception:
                    continue
            if not _is_clean_text(my_text) or not _is_clean_text(other_text):
                continue

            emo = _detect_emotion(my_text)
            if emo != "neutral" and 2 <= len(other_text) <= 60:
                triggers[emo].append(other_text)

        result = {}
        for emo, texts in triggers.items():
            random.seed(emo.__hash__() % 2**31)
            samples = random.sample(texts, min(10, len(texts)))
            result[emo] = samples
        return result

    def save(self, filepath: str = "data/emotion_profile.yaml") -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.profile, f, allow_unicode=True, default_flow_style=False)
        logger.info("Emotion profile saved to %s", filepath)

    @staticmethod
    def load(filepath: str = "data/emotion_profile.yaml") -> dict:
        path = Path(filepath)
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
