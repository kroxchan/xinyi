"""话题追踪器 — 追踪活跃话题。

管理 context/topics.md，记录当前活跃话题及其频率。
从对话中提取话题关键词，更新追踪状态。

Example:
    tracker = TopicTracker(Path("data/twin_workspace/context/topics.md"))
    tracker.update("用户最近在讨论工作压力和职业发展")
    active = tracker.get_active_topics()
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.logging_config import get_logger

logger = get_logger(__name__)

TOPICS_TEMPLATE = """\
# 话题追踪

> 自动生成，最后更新 {updated}

## 活跃话题

{active_topics}

## 历史话题

{historical_topics}

---
"""

TOPIC_ITEM_TEMPLATE = "- **{topic}** — {count}次提及 | 最后活跃: {last_seen}"

# 话题提取正则（中文友好）
TOPIC_PATTERNS = [
    r"(工作|职场|加班|上班|辞职|面试|求职|工资|老板|领导|同事|项目|甲方)",
    r"(感情|恋爱|约会|吵架|分手|冷战|求婚|结婚|见家长|彩礼|同居)",
    r"(学习|考试|升学|留学|考研|读书|课程|培训|技能|成长)",
    r"(健康|运动|健身|减肥|饮食|睡眠|生病|医院|体检|心理咨询)",
    r"(旅游|旅行|度假|出国|签证|酒店|机票|景点|拍照|打卡)",
    r"(娱乐|游戏|追剧|综艺|电影|音乐|追星|短视频|直播|小说)",
    r"(购物|消费|理财|投资|股票|基金|省钱|省钱|省钱|钱包|预算)",
    r"(家庭|父母|亲戚|孩子|教育|养娃|婆媳|兄弟姐妹)",
    r"(社交|朋友|聚会|应酬|人脉|社恐|社牛|孤独|孤单)",
    r"(未来|规划|目标|梦想|迷茫|焦虑|压力|烦恼)",
]


class TopicTracker:
    """追踪活跃话题，维护频率和新鲜度。

    特性：
    - 基于关键词的话题提取
    - 频率统计
    - 新鲜度衰减
    - 人类可读 Markdown 格式
    """

    def __init__(
        self,
        topics_file: str | Path = "data/twin_workspace/context/topics.md",
        decay_days: int = 7,
    ) -> None:
        self.topics_file = Path(topics_file)
        self.topics_file.parent.mkdir(parents=True, exist_ok=True)
        self.decay_days = decay_days

        # 内存中的话题状态
        self._topics: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "last_seen": None, "category": "general"}
        )
        self._category_keywords = self._build_category_map()

        # 加载已有话题
        self._load()

    def _build_category_map(self) -> dict[str, list[str]]:
        """构建话题类别映射。"""
        return {
            "工作职场": ["工作", "职场", "加班", "上班", "辞职", "面试", "求职", "工资", "老板", "领导", "同事", "项目"],
            "感情关系": ["感情", "恋爱", "约会", "吵架", "分手", "冷战", "求婚", "结婚", "见家长"],
            "学习成长": ["学习", "考试", "升学", "留学", "考研", "读书", "课程"],
            "健康生活": ["健康", "运动", "健身", "减肥", "饮食", "睡眠", "生病"],
            "娱乐休闲": ["游戏", "追剧", "综艺", "电影", "音乐", "追星", "短视频"],
            "财务理财": ["购物", "消费", "理财", "投资", "股票", "基金", "省钱"],
            "家庭亲情": ["家庭", "父母", "孩子", "教育", "养娃", "婆媳"],
            "社交人际": ["朋友", "聚会", "社交", "人脉", "社恐", "孤独"],
            "未来规划": ["未来", "规划", "目标", "梦想", "迷茫", "焦虑", "压力"],
        }

    def _categorize(self, topic: str) -> str:
        """根据关键词判断话题类别。"""
        for category, keywords in self._category_keywords.items():
            if any(kw in topic for kw in keywords):
                return category
        return "general"

    def _load(self) -> None:
        """从文件加载话题状态。"""
        if not self.topics_file.exists():
            return

        try:
            content = self.topics_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            in_active = False
            for line in lines:
                line = line.strip()

                if line == "## 活跃话题":
                    in_active = True
                    continue
                elif line.startswith("## "):
                    in_active = False
                    continue

                if in_active and line.startswith("-"):
                    match = re.match(
                        r"- \*\*(.+?)\*\* — (\d+)次提及",
                        line
                    )
                    if match:
                        topic = match.group(1)
                        count = int(match.group(2))
                        self._topics[topic]["count"] = count
                        self._topics[topic]["category"] = self._categorize(topic)

            logger.debug("Loaded %d topics from file", len(self._topics))

        except Exception as e:
            logger.warning("Failed to load topics: %s", e)

    def _save(self) -> None:
        """保存话题状态到文件。"""
        try:
            now = datetime.now()
            active = self.get_active_topics(limit=20)
            historical = self.get_historical_topics(limit=20)

            active_lines = []
            for topic, info in active:
                active_lines.append(TOPIC_ITEM_TEMPLATE.format(
                    topic=topic,
                    count=info["count"],
                    last_seen=info["last_seen"].strftime("%Y-%m-%d") if info["last_seen"] else "未知",
                ))

            historical_lines = []
            for topic, info in historical:
                days_ago = (now - info["last_seen"]).days if info["last_seen"] else 999
                historical_lines.append(f"- ~~{topic}~~ ({days_ago}天前)")

            content = TOPICS_TEMPLATE.format(
                updated=now.strftime("%Y-%m-%d %H:%M"),
                active_topics="\n".join(active_lines) if active_lines else "（暂无活跃话题）",
                historical_topics="\n".join(historical_lines) if historical_lines else "（无历史话题）",
            )

            self.topics_file.write_text(content, encoding="utf-8")

        except Exception as e:
            logger.error("Failed to save topics: %s", e)

    def update(self, message: str) -> list[str]:
        """从消息中提取话题关键词，更新追踪。

        Args:
            message: 输入消息

        Returns:
            本次识别到的新话题列表
        """
        if not message or len(message) < 5:
            return []

        new_topics = []
        now = datetime.now()

        for pattern_str in TOPIC_PATTERNS:
            pattern = re.compile(pattern_str)
            matches = pattern.findall(message)

            for keyword in matches:
                topic = self._normalize_topic(keyword)

                if self._topics[topic]["count"] == 0:
                    new_topics.append(topic)

                self._topics[topic]["count"] += 1
                self._topics[topic]["last_seen"] = now
                self._topics[topic]["category"] = self._categorize(topic)

        if new_topics:
            self._save()

        return new_topics

    def update_batch(self, messages: list[str]) -> list[str]:
        """批量更新话题。

        Args:
            messages: 消息列表

        Returns:
            本次识别到的新话题列表
        """
        all_new = []
        for msg in messages:
            new = self.update(msg)
            all_new.extend(new)
        return list(set(all_new))

    def get_active_topics(self, top_k: int = 5) -> list[tuple[str, dict]]:
        """返回最活跃的话题。

        Returns:
            列表，每项为 (话题名, 信息字典)
        """
        self._apply_decay()

        now = datetime.now()
        cutoff = now - timedelta(days=self.decay_days)

        active = [
            (topic, info)
            for topic, info in self._topics.items()
            if info["count"] > 0 and (
                info["last_seen"] is None or info["last_seen"] >= cutoff
            )
        ]

        active.sort(key=lambda x: x[1]["count"], reverse=True)
        return active[:top_k]

    def get_historical_topics(self, limit: int = 20) -> list[tuple[str, dict]]:
        """返回历史（非活跃）话题。"""
        self._apply_decay()

        now = datetime.now()
        cutoff = now - timedelta(days=self.decay_days)

        historical = [
            (topic, info)
            for topic, info in self._topics.items()
            if info["count"] > 0 and info["last_seen"] < cutoff
        ]

        historical.sort(key=lambda x: x[1]["last_seen"], reverse=True)
        return historical[:limit]

    def get_topics_by_category(self, category: str) -> list[tuple[str, dict]]:
        """返回指定类别的话题。"""
        self._apply_decay()

        categorized = [
            (topic, info)
            for topic, info in self._topics.items()
            if info["category"] == category and info["count"] > 0
        ]

        categorized.sort(key=lambda x: x[1]["count"], reverse=True)
        return categorized

    def _apply_decay(self) -> None:
        """对新话题应用新鲜度衰减。"""
        now = datetime.now()

        for topic, info in list(self._topics.items()):
            if info["last_seen"] is None:
                continue

            days_inactive = (now - info["last_seen"]).days
            if days_inactive > self.decay_days:
                # 衰减计数，但不删除
                info["count"] = max(1, info["count"] - 1)

    @staticmethod
    def _normalize_topic(keyword: str) -> str:
        """规范化话题关键词。"""
        # 合并相似话题
        synonyms = {
            "上班": "工作",
            "加班": "工作",
            "辞职": "工作",
            "求职": "工作",
            "面试": "工作",
            "工资": "工作",
            "老板": "工作",
            "领导": "工作",
            "同事": "工作",
            "项目": "工作",
            "见家长": "感情",
            "求婚": "感情",
            "吵架": "感情",
            "冷战": "感情",
            "减肥": "健康",
            "健身": "健康",
        }
        return synonyms.get(keyword, keyword)
