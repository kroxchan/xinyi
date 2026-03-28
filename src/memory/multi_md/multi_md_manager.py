"""统一管理器 — 串联所有多 MD 记忆组件。

MultiMDManager 是多 Markdown 文件记忆系统的统一入口，
串联日志、策展记忆、话题追踪、锚点和 BM25 搜索。

Example:
    # 初始化
    manager = MultiMDManager("data/twin_workspace")

    # 会话结束时记录
    manager.log_session(
        session_id="abc123",
        messages=[{"role": "user", "content": "..."}],
        twin_mode="partner"
    )

    # 统一检索
    results = manager.retrieve("最近的工作情况")
    # results = {
    #     "bm25": [...],
    #     "memory": [...],
    #     "topics": [...],
    #     "anchors": [...],
    # }

    # 蒸馏（如需要）
    manager.distill_if_needed(api_client, model="gpt-4o-mini")
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logging_config import get_logger

from .anchors import AnchorTracker
from .bm25_search import BM25Search
from .curated_memory import CuratedMemory
from .daily_log import DailyLogManager
from .distill import distill_recent_logs, mark_distilled, should_distill
from .topic_tracker import TopicTracker

logger = get_logger(__name__)

DEFAULT_WORKSPACE = "data/twin_workspace"


class MultiMDManager:
    """OpenClaw 风格多 MD 文件记忆管理器。

    与现有 ChromaDB + MemoryBank 并存，提供：
    - 每日对话日志（append-only）
    - 策展型长期记忆（curated memory）
    - 话题追踪
    - 连续性锚点
    - BM25 关键词检索

    特性：
    - 完全可选集成（默认 None，不影响现有功能）
    - 人类可读的 Markdown 文件
    - 懒加载（首次使用时才初始化）
    - 渐进式生效（日志→蒸馏→检索）
    """

    def __init__(
        self,
        workspace_dir: str | Path = DEFAULT_WORKSPACE,
        decay_days: int = 7,
        default_ttl: int = 7200,
    ) -> None:
        self.workspace = Path(workspace_dir)
        self.logs_dir = self.workspace / "logs"
        self.context_dir = self.workspace / "context"
        self.memory_file = self.workspace / "memory.md"
        self.last_distill_file = self.workspace / ".last_distill.json"

        # 组件实例（懒加载）
        self._log: DailyLogManager | None = None
        self._memory: CuratedMemory | None = None
        self._topics: TopicTracker | None = None
        self._anchors: AnchorTracker | None = None
        self._bm25: BM25Search | None = None

        # 配置
        self.decay_days = decay_days
        self.default_ttl = default_ttl

        # 初始化目录
        self._ensure_dirs()

        # 加载/初始化组件
        self._ensure_components()

    def _ensure_dirs(self) -> None:
        """确保必要目录存在。"""
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.context_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_components(self) -> None:
        """确保所有组件已初始化。"""
        if self._log is None:
            self._log = DailyLogManager(self.logs_dir)

        if self._memory is None:
            self._memory = CuratedMemory(self.memory_file)
            if not self._memory.exists():
                self._memory.initialize()

        if self._topics is None:
            self._topics = TopicTracker(
                self.context_dir / "topics.md",
                decay_days=self.decay_days,
            )

        if self._anchors is None:
            self._anchors = AnchorTracker(
                self.context_dir / "anchors.md",
                default_ttl=self.default_ttl,
            )

        if self._bm25 is None:
            self._bm25 = BM25Search(self.logs_dir)

    @property
    def log(self) -> DailyLogManager:
        """获取日志管理器。"""
        self._ensure_components()
        return self._log  # type: ignore

    @property
    def memory(self) -> CuratedMemory:
        """获取策展记忆管理器。"""
        self._ensure_components()
        return self._memory  # type: ignore

    @property
    def topics(self) -> TopicTracker:
        """获取话题追踪器。"""
        self._ensure_components()
        return self._topics  # type: ignore

    @property
    def anchors(self) -> AnchorTracker:
        """获取锚点追踪器。"""
        self._ensure_components()
        return self._anchors  # type: ignore

    @property
    def bm25(self) -> BM25Search:
        """获取 BM25 搜索。"""
        self._ensure_components()
        return self._bm25  # type: ignore

    def log_session(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        twin_mode: str = "partner",
        topic: str = "",
        summary: dict[str, Any] | None = None,
    ) -> Path | None:
        """记录会话摘要到今日日志。

        在每次对话会话结束时调用，将摘要追加到今天的日志文件。

        Args:
            session_id: 会话唯一标识
            messages: 对话消息列表，每项包含 role 和 content
            twin_mode: "partner" 或 "self"
            topic: 话题标签（可选，自动提取）
            summary: 预计算的摘要（可选）

        Returns:
            写入的日志文件路径
        """
        self._ensure_components()

        # 从消息中提取信息
        if summary is None:
            summary = self._generate_summary(messages, twin_mode)

        # 覆盖指定字段
        summary["mode"] = twin_mode
        if topic:
            summary["topic"] = topic
        else:
            # 自动提取话题
            topic = self._extract_topic_from_messages(messages)
            summary["topic"] = topic

        # 追加到日志
        log_path = self._log.append(session_id, summary)  # type: ignore

        if log_path:
            # 更新话题追踪
            text_content = " ".join(m.get("content", "") for m in messages)
            self._topics.update(text_content)  # type: ignore

            # 检查锚点条件
            self._check_anchor_conditions(messages)

        return log_path

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        include_sources: list[str] | None = None,
    ) -> dict[str, Any]:
        """统一检索：memory + logs + topics + anchors。

        Args:
            query: 搜索查询
            top_k: 各来源返回的结果数
            include_sources: 指定要检索的来源，默认全部

        Returns:
            检索结果字典，包含：
            - bm25: BM25 关键词搜索结果
            - memory: 策展记忆匹配
            - topics: 相关话题
            - anchors: 相关锚点
            - formatted: 格式化的上下文字符串
        """
        self._ensure_components()

        if include_sources is None:
            include_sources = ["bm25", "memory", "topics", "anchors"]

        results: dict[str, Any] = {
            "bm25": [],
            "memory": [],
            "topics": [],
            "anchors": [],
            "formatted": "",
        }

        # BM25 搜索
        if "bm25" in include_sources:
            results["bm25"] = self._bm25.search(query, top_k=top_k)  # type: ignore

        # 策展记忆搜索
        if "memory" in include_sources:
            results["memory"] = self._memory.search(query)[:top_k]  # type: ignore

        # 话题匹配
        if "topics" in include_sources:
            active_topics = self._topics.get_active_topics(top_k=top_k)  # type: ignore
            query_lower = query.lower()
            matched_topics = [
                {"topic": t, "count": c["count"]}
                for t, c in active_topics
                if query_lower in t
            ]
            results["topics"] = matched_topics

        # 锚点搜索
        if "anchors" in include_sources:
            results["anchors"] = self._anchors.search(query)[:top_k]  # type: ignore

        # 格式化为上下文字符串
        results["formatted"] = self._format_for_context(query, results)

        return results

    def retrieve_for_context(
        self,
        query: str,
        max_length: int = 2000,
    ) -> str:
        """检索并格式化为 prompt 上下文。

        Args:
            query: 搜索查询
            max_length: 最大上下文长度

        Returns:
            格式化的上下文字符串
        """
        results = self.retrieve(query, top_k=3)
        formatted = results.get("formatted", "")

        if len(formatted) > max_length:
            formatted = formatted[:max_length] + "\n...(上下文过长已截断)"

        return formatted

    def distill_if_needed(
        self,
        api_client: Any,
        model: str = "gpt-4o-mini",
        force: bool = False,
    ) -> int:
        """每日蒸馏：将最近日志中的新内容蒸馏到 memory.md。

        检查是否满足蒸馏条件，满足则执行蒸馏。

        Args:
            api_client: OpenAI API 客户端
            model: 使用的模型
            force: 是否强制执行（忽略时间检查）

        Returns:
            蒸馏出的洞察数量，0 表示未执行
        """
        self._ensure_components()

        # 检查是否应该蒸馏
        if not force and not should_distill(
            self.logs_dir,
            self.last_distill_file,
            max_interval_hours=24,
        ):
            logger.debug("Skipping distillation: not enough time has passed")
            return 0

        try:
            # 蒸馏最近 3 天的日志
            insights = distill_recent_logs(
                logs_dir=self.logs_dir,
                current_memory_file=self.memory_file,
                api_client=api_client,
                model=model,
                days=3,
            )

            if insights and any(insights.values()):
                # 更新策展记忆
                self._memory.update_from_distillation(insights)  # type: ignore

                # 标记蒸馏完成
                mark_distilled(
                    self.last_distill_file,
                    datetime.now().strftime("%Y-%m-%d"),
                )

                total = sum(len(v) for v in insights.values())
                logger.info("Distillation complete: %d insights added", total)
                return total

            return 0

        except Exception as e:
            logger.error("Distillation failed: %s", e)
            return 0

    def get_twin_context(self) -> dict[str, Any]:
        """获取完整的分身上下文。

        Returns:
            包含所有记忆层信息的字典
        """
        self._ensure_components()

        return {
            "memory": self._memory.load(),  # type: ignore
            "active_topics": [
                {"topic": t, "count": c["count"]}
                for t, c in self._topics.get_active_topics(10)  # type: ignore
            ],
            "anchors": {
                "active": self._anchors.get_active(),  # type: ignore
                "formatted": self._anchors.format_for_context(),  # type: ignore
            },
            "today_log": self._log.get_today_log(),  # type: ignore
            "recent_sessions": [
                {"date": r["date"], "sessions": len(r["sessions"])}
                for r in self._log.get_recent_logs(7)  # type: ignore
            ],
        }

    def cleanup(self) -> int:
        """清理过期数据。"""
        self._ensure_components()

        # 清理过期锚点
        cleaned = self._anchors.cleanup()  # type: ignore

        # 清理 BM25 索引（下次使用时自动重建）
        self._bm25 = None

        return cleaned

    def _generate_summary(
        self,
        messages: list[dict[str, str]],
        twin_mode: str,
    ) -> dict[str, Any]:
        """从消息生成会话摘要。"""
        user_messages = [m["content"] for m in messages if m.get("role") == "user"]
        assistant_messages = [m["content"] for m in messages if m.get("role") == "assistant"]

        return {
            "topic": self._extract_topic_from_messages(messages),
            "events": self._extract_events(user_messages),
            "emotion_trajectory": self._extract_emotion(user_messages),
            "messages": self._format_messages(user_messages, assistant_messages),
            "new_facts": self._extract_facts(user_messages),
            "relationship_changes": [],
            "open_issues": [],
        }

    @staticmethod
    def _extract_topic_from_messages(messages: list[dict[str, str]]) -> str:
        """从消息中提取话题。"""
        text = " ".join(m.get("content", "") for m in messages)

        topic_keywords = {
            "工作": ["工作", "加班", "上班", "辞职", "老板", "同事"],
            "感情": ["吵架", "分手", "约会", "冷战", "想你了"],
            "生活": ["吃饭", "睡觉", "运动", "健康"],
            "学习": ["考试", "学习", "读书", "课程"],
            "娱乐": ["游戏", "追剧", "电影", "音乐"],
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in text for kw in keywords):
                return topic

        return "一般话题"

    @staticmethod
    def _extract_events(messages: list[str]) -> str:
        """提取关键事件。"""
        if not messages:
            return "无"
        return messages[0][:100] if messages else "无"

    @staticmethod
    def _extract_emotion(messages: list[str]) -> str:
        """提取情绪轨迹。"""
        text = " ".join(messages)

        if any(w in text for w in ["开心", "高兴", "哈哈", "笑死"]):
            return "积极"
        elif any(w in text for w in ["难过", "伤心", "哭"]):
            return "低落"
        elif any(w in text for w in ["生气", "烦", "气"]):
            return "消极"
        elif any(w in text for w in ["担心", "焦虑", "怕"]):
            return "焦虑"
        return "平稳"

    @staticmethod
    def _format_messages(user_msgs: list[str], assistant_msgs: list[str]) -> list[str]:
        """格式化消息为对话摘录。"""
        result = []
        for msg in user_msgs[-3:]:
            result.append(f"用户：{msg[:80]}")
        for msg in assistant_msgs[-2:]:
            result.append(f"KK：{msg[:80]}")
        return result

    @staticmethod
    def _extract_facts(messages: list[str]) -> list[str]:
        """提取事实（简单实现）。"""
        facts = []
        text = " ".join(messages)

        # 简单的事实提取模式
        patterns = [
            (r"我是(.+?)[，。]", r"我是\1"),
            (r"我在(.+?)工作", r"在\1工作"),
            (r"我有(.+?)[狗猫宠]", r"有\1"),
        ]

        for pattern, replacement in patterns:
            match = re.search(pattern, text)
            if match:
                facts.append(re.sub(r"^"|"$", "", match.group(0)))

        return facts[:3]

    def _check_anchor_conditions(self, messages: list[dict[str, str]]) -> None:
        """检查是否需要添加锚点。"""
        text = " ".join(m.get("content", "") for m in messages)

        # 检查矛盾信号
        if any(w in text for w in ["但是", "其实", "明明", "应该"]):
            self._anchors.add_tension(  # type: ignore
                "对话中出现矛盾信号，可能需要关注态度变化",
                note="自动检测",
            )

        # 检查身份相关话题
        identity_keywords = ["未来", "想", "要", "打算", "计划"]
        if sum(1 for kw in identity_keywords if kw in text) >= 2:
            self._anchors.add_identity(  # type: ignore
                "正在思考未来规划",
                note="自动检测",
            )

    def _format_for_context(
        self,
        query: str,
        results: dict[str, Any],
    ) -> str:
        """将检索结果格式化为上下文字符串。"""
        lines = []

        # BM25 结果
        if results.get("bm25"):
            lines.append("\n## 相关日志片段")
            for i, item in enumerate(results["bm25"][:2], 1):
                lines.append(f"[{i}] {item['content'][:150]}...")

        # 策展记忆
        if results.get("memory"):
            lines.append("\n## 相关记忆")
            for item in results["memory"][:3]:
                lines.append(f"- {item}")

        # 活跃话题
        if results.get("topics"):
            topics_str = ", ".join(t["topic"] for t in results["topics"])
            lines.append(f"\n## 当前话题: {topics_str}")

        # 锚点
        if results.get("anchors"):
            lines.append("\n## 相关锚点")
            for anchor in results["anchors"][:2]:
                lines.append(f"- [{anchor['type']}] {anchor['content']}")

        return "\n".join(lines)
