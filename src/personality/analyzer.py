from __future__ import annotations

import re
from collections import Counter

import jieba


EMOJI_PATTERN = re.compile(
    "[\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f6ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\u2600-\u26ff"
    "\u2700-\u27bf"
    "\ufe00-\ufe0f"
    "\u200d]+",
    flags=re.UNICODE,
)

WECHAT_EMOJI_PATTERN = re.compile(r"\[[\u4e00-\u9fff]+\]")


class PersonalityAnalyzer:
    def __init__(self) -> None:
        pass

    def analyze(self, messages: list[dict], twin_mode: str = "self") -> dict:
        target_sender = 0 if twin_mode == "partner" else 1
        sent_messages = [m for m in messages if m.get("IsSender") == target_sender]
        texts = [m.get("StrContent", "") for m in sent_messages if m.get("StrContent")]

        if not texts:
            return self._empty_result()

        total = len(texts)
        all_text = "".join(texts)

        avg_length = sum(len(t) for t in texts) / total

        emoji_count = sum(len(EMOJI_PATTERN.findall(t)) + len(WECHAT_EMOJI_PATTERN.findall(t)) for t in texts)
        emoji_frequency = emoji_count / total

        punctuation_style = self._analyze_punctuation(texts, total)
        top_phrases = self._extract_top_phrases(texts, top_k=20)
        all_words = [w for w in jieba.cut(all_text) if w.strip()]
        vocabulary_richness = len(set(all_words)) / len(all_words) if all_words else 0.0

        avg_response_time = self._calc_avg_response_time(messages)
        length_dist = self._calc_length_distribution(texts)
        topic_keywords = self._extract_topic_keywords(texts, top_k=30)
        vocab_bank = self._extract_vocab_bank(texts)

        return {
            "avg_message_length": round(avg_length, 2),
            "emoji_frequency": round(emoji_frequency, 4),
            "punctuation_style": punctuation_style,
            "top_phrases": [list(t) for t in top_phrases],
            "vocabulary_richness": round(vocabulary_richness, 4),
            "avg_response_time_seconds": avg_response_time,
            "message_length_distribution": length_dist,
            "topic_keywords": [list(t) for t in topic_keywords],
            "total_messages_analyzed": total,
            "vocab_bank": vocab_bank,
        }

    def _analyze_punctuation(self, texts: list[str], total: int) -> dict[str, float]:
        exclamation = sum(t.count("！") + t.count("!") for t in texts)
        ellipsis = sum(t.count("…") + t.count("...") for t in texts)
        question = sum(t.count("？") + t.count("?") for t in texts)
        return {
            "exclamation_freq": round(exclamation / total, 4),
            "ellipsis_freq": round(ellipsis / total, 4),
            "question_freq": round(question / total, 4),
        }

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
        "系统", "自动", "报备", "此为",
    }

    def _extract_top_phrases(
        self, texts: list[str], top_k: int = 20
    ) -> list[tuple[str, int]]:
        counter: Counter[str] = Counter()
        for text in texts:
            words = jieba.cut(text)
            for w in words:
                w = w.strip()
                if len(w) >= 2 and w not in self._STOPWORDS:
                    counter[w] += 1
        return counter.most_common(top_k)

    def _calc_avg_response_time(self, messages: list[dict]) -> float | None:
        response_times: list[float] = []
        sorted_msgs = sorted(messages, key=lambda m: m.get("CreateTime", 0))

        for i in range(1, len(sorted_msgs)):
            prev = sorted_msgs[i - 1]
            curr = sorted_msgs[i]
            if prev.get("IsSender") == 0 and curr.get("IsSender") == 1:
                prev_time = prev.get("CreateTime", 0)
                curr_time = curr.get("CreateTime", 0)
                if prev_time and curr_time:
                    delta = curr_time - prev_time
                    if 0 < delta < 86400:
                        response_times.append(delta)

        if not response_times:
            return None
        return round(sum(response_times) / len(response_times), 2)

    def _calc_length_distribution(self, texts: list[str]) -> dict[str, float]:
        total = len(texts)
        short = sum(1 for t in texts if len(t) < 10)
        medium = sum(1 for t in texts if 10 <= len(t) <= 50)
        long_ = sum(1 for t in texts if len(t) > 50)
        return {
            "short": round(short / total * 100, 2),
            "medium": round(medium / total * 100, 2),
            "long": round(long_ / total * 100, 2),
        }

    def _extract_topic_keywords(self, texts: list[str], top_k: int = 30) -> list[tuple[str, int]]:
        counter: Counter[str] = Counter()
        for text in texts:
            words = jieba.cut(text)
            for w in words:
                w = w.strip()
                if len(w) >= 2 and w not in self._STOPWORDS:
                    counter[w] += 1
        return counter.most_common(top_k)

    _SLANG_SEEDS = {
        "卧槽", "我操", "操", "靠", "我靠", "妈的", "他妈", "草", "我草",
        "牛逼", "nb", "NB", "傻逼", "sb", "SB", "尼玛", "你妈",
        "tmd", "TMD", "日", "去你的", "滚", "屌", "艹", "我艹",
        "fuck", "shit", "damn", "wtf", "卧草", "woc", "wc",
        "废物", "智障", "弱智", "脑残", "白痴", "变态", "神经病",
        "6", "666", "牛", "绝了", "裂开", "无语", "离谱", "破防",
        "emo", "社死", "摆烂", "寄", "芭比Q", "麻了", "蚌埠住",
        "hhhh", "哈哈哈", "笑死", "xswl", "绷不住", "乐了",
    }

    _CATCHPHRASE_PATTERNS = [
        re.compile(r"^.{1,4}吧$"),
        re.compile(r"^.{1,4}啊$"),
        re.compile(r"^.{1,6}了$"),
    ]

    def _extract_vocab_bank(self, texts: list[str]) -> dict:
        slang_counter: Counter[str] = Counter()
        catchphrase_counter: Counter[str] = Counter()

        for t in texts:
            t_lower = t.lower().strip()
            for seed in self._SLANG_SEEDS:
                if seed.lower() in t_lower:
                    slang_counter[seed] += 1

            if len(t.strip()) <= 8:
                catchphrase_counter[t.strip()] += 1

        slang = [w for w, c in slang_counter.most_common(30) if c >= 3]

        short_hits = [(w, c) for w, c in catchphrase_counter.most_common(200) if c >= 5 and len(w) >= 2]
        catchphrases = [w for w, _ in short_hits[:30]]

        sample_with_slang: list[str] = []
        if slang:
            slang_set = set(s.lower() for s in slang[:10])
            for t in texts:
                if any(s in t.lower() for s in slang_set):
                    clean = t.strip()
                    if 2 < len(clean) < 60:
                        sample_with_slang.append(clean)
                        if len(sample_with_slang) >= 30:
                            break

        return {
            "slang": slang,
            "catchphrases": catchphrases,
            "slang_samples": sample_with_slang,
        }

    def analyze_per_contact(self, messages: list[dict], contact_wxid: str) -> dict:
        """Analyze communication style specifically for one contact."""
        contact_msgs = [m for m in messages if m.get("StrTalker") == contact_wxid]
        if not contact_msgs:
            return {}
        result = self.analyze(contact_msgs)
        style_hints = []
        avg_len = result.get("avg_message_length", 0)
        if avg_len < 8:
            style_hints.append("消息很短")
        elif avg_len > 30:
            style_hints.append("消息较长")
        emoji_freq = result.get("emoji_frequency", 0)
        if emoji_freq > 0.2:
            style_hints.append("大量使用表情")
        elif emoji_freq > 0.05:
            style_hints.append("适度使用表情")
        top = result.get("top_phrases", [])
        intimate_words = {"宝宝", "亲亲", "么么", "抱抱", "宝贝", "爱你", "想你"}
        found = [p[0] for p in top if isinstance(p, (list, tuple)) and p[0] in intimate_words]
        if found:
            style_hints.append("语气亲密（常用：" + "、".join(found[:3]) + "）")
        result["style_summary"] = "、".join(style_hints) if style_hints else "普通聊天风格"
        return result

    def _empty_result(self) -> dict:
        return {
            "avg_message_length": 0,
            "emoji_frequency": 0,
            "punctuation_style": {"exclamation_freq": 0, "ellipsis_freq": 0, "question_freq": 0},
            "top_phrases": [],
            "vocabulary_richness": 0,
            "avg_response_time_seconds": None,
            "message_length_distribution": {"short": 0, "medium": 0, "long": 0},
            "topic_keywords": [],
            "total_messages_analyzed": 0,
            "vocab_bank": {"slang": [], "catchphrases": [], "slang_samples": []},
        }
