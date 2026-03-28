"""每日日志管理器 — 追加型对话摘要。

管理 logs/YYYY-MM-DD.md 文件，每条会话结束时追加摘要。
日志格式人类可读，可直接编辑。

Example:
    log_mgr = DailyLogManager(Path("data/twin_workspace/logs"))
    log_mgr.append(
        session_id="abc123",
        summary={
            "mode": "partner",
            "topic": "关于工作压力的话题",
            "events": "分享了加班的烦恼",
            "emotion_trajectory": "从焦虑到释然",
            "messages": [
                "用户：我最近加班好累",
                "KK：怎么了？发生什么事了吗？",
                "用户：老板给的压力太大了",
            ],
            "new_facts": ["用户在IT行业工作", "最近项目压力大"],
            "relationship_changes": [],
            "open_issues": ["后续如何支持用户减压"],
        }
    )
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logging_config import get_logger

logger = get_logger(__name__)

LOG_HEADER_TEMPLATE = """\
# {date} 对话日志

> 自动生成，人类可编辑

## 会话摘要

"""

LOG_SESSION_TEMPLATE = """\
### 会话 {session_id} ({mode})
- **时间**: {timestamp}
- **话题**: {topic}
- **关键事件**: {events}
- **情绪轨迹**: {emotion_trajectory}

#### 对话摘录
{messages}

#### 提炼
- **新的事实**: {new_facts}
- **关系变化**: {relationship_changes}
- **未解决的问题**: {open_issues}

---
"""


class DailyLogManager:
    """管理 logs/YYYY-MM-DD.md 追加型日志文件。

    特性：
    - 每天一个文件，自动创建
    - 追加模式，不覆盖历史
    - 人类可读 Markdown 格式
    - 支持会话去重（同一 session_id 不会重复写入）
    """

    def __init__(
        self,
        logs_dir: str | Path = "data/twin_workspace/logs",
    ) -> None:
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _get_log_path(self, date: datetime | None = None) -> Path:
        """获取指定日期的日志文件路径。"""
        d = date or datetime.now()
        return self.logs_dir / f"{d.strftime('%Y-%m-%d')}.md"

    def _read_log(self, path: Path) -> str:
        """读取日志文件内容。"""
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _has_session(self, log_path: Path, session_id: str) -> bool:
        """检查日志中是否已存在该会话。"""
        if not log_path.exists():
            return False
        content = self._read_log(log_path)
        return f"### 会话 {session_id} (" in content

    def append(self, session_id: str, summary: dict[str, Any]) -> Path | None:
        """追加一条会话摘要到今天的日志文件。

        Args:
            session_id: 会话唯一标识
            summary: 摘要字典，包含以下字段：
                - mode: str — "partner" 或 "self"
                - topic: str — 本次话题
                - events: str — 关键事件
                - emotion_trajectory: str — 情绪变化
                - messages: list[str] — 对话摘录
                - new_facts: list[str] — 新的事实
                - relationship_changes: list[str] — 关系变化
                - open_issues: list[str] — 未解决的问题

        Returns:
            写入的日志文件路径，失败返回 None
        """
        log_path = self._get_log_path()

        # 会话去重
        if self._has_session(log_path, session_id):
            logger.debug("Session %s already exists in %s, skipping", session_id, log_path.name)
            return None

        # 构建会话内容
        now = datetime.now()
        session_content = LOG_SESSION_TEMPLATE.format(
            session_id=session_id,
            mode=summary.get("mode", "unknown"),
            timestamp=now.strftime("%H:%M:%S"),
            topic=self._format_list(summary.get("topic", "")),
            events=self._format_list(summary.get("events", "无")),
            emotion_trajectory=self._format_list(summary.get("emotion_trajectory", "平稳")),
            messages=self._format_messages(summary.get("messages", [])),
            new_facts=self._format_list_items(summary.get("new_facts", [])),
            relationship_changes=self._format_list_items(
                summary.get("relationship_changes", ["无"])
            ),
            open_issues=self._format_list_items(summary.get("open_issues", ["无"])),
        )

        try:
            existing_content = self._read_log(log_path)

            if existing_content:
                # 追加到文件末尾（最后一个 --- 之后）
                if existing_content.rstrip().endswith("---"):
                    new_content = existing_content.rstrip() + "\n" + session_content
                else:
                    new_content = existing_content + "\n" + session_content
            else:
                # 新建文件，先写 header
                new_content = LOG_HEADER_TEMPLATE.format(
                    date=now.strftime("%Y-%m-%d")
                ) + session_content

            log_path.write_text(new_content, encoding="utf-8")
            logger.info("Appended session %s to %s", session_id, log_path.name)
            return log_path

        except Exception as e:
            logger.error("Failed to append session %s: %s", session_id, e)
            return None

    def get_today_log(self) -> str:
        """获取今天的日志内容。"""
        return self._read_log(self._get_log_path())

    def get_log(self, date: datetime | None = None) -> str:
        """获取指定日期的日志内容。"""
        return self._read_log(self._get_log_path(date))

    def get_recent_logs(self, days: int = 3) -> list[dict[str, Any]]:
        """获取最近 N 天的日志摘要。

        Returns:
            列表，每项包含 date, path, sessions 字段
        """
        results = []
        today = datetime.now()

        for i in range(days):
            d = today.replace(hour=0, minute=0, second=0, microsecond=0)
            d = d.replace(day=max(1, d.day - i))
            log_path = self._get_log_path(d)

            if not log_path.exists():
                continue

            content = self._read_log(log_path)
            sessions = self._parse_sessions(content)

            results.append({
                "date": d.strftime("%Y-%m-%d"),
                "path": log_path,
                "sessions": sessions,
                "content": content,
            })

        return results

    def _parse_sessions(self, content: str) -> list[dict[str, Any]]:
        """解析日志内容中的所有会话。"""
        sessions = []
        pattern = re.compile(
            r"### 会话 (\S+) \(([^)]+)\)\n"
            r"- \*\*时间\*\*: ([^\n]+)\n"
            r"- \*\*话题\*\*: ([^\n]+)\n"
            r"- \*\*关键事件\*\*: ([^\n]+)\n"
            r"- \*\*情绪轨迹\*\*: ([^\n]+)\n"
        )

        for match in pattern.finditer(content):
            sessions.append({
                "session_id": match.group(1),
                "mode": match.group(2),
                "time": match.group(3),
                "topic": match.group(4),
                "events": match.group(5),
                "emotion_trajectory": match.group(6),
            })

        return sessions

    def list_log_files(self) -> list[Path]:
        """列出所有日志文件（按日期排序）。"""
        if not self.logs_dir.exists():
            return []
        files = sorted(self.logs_dir.glob("????-??-??.md"), reverse=True)
        return files

    @staticmethod
    def _format_list(value: str) -> str:
        """格式化单个字符串为列表项。"""
        if not value:
            return "无"
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        return value if value else "无"

    @staticmethod
    def _format_list_items(items: list) -> str:
        """格式化列表为 Markdown 无序列表。"""
        if not items:
            return "无"
        if isinstance(items, str):
            return items
        return "\n".join(f"  - {item}" for item in items if item)

    @staticmethod
    def _format_messages(messages: list[str]) -> str:
        """格式化对话消息列表。"""
        if not messages:
            return "无记录"
        lines = []
        for msg in messages[-6:]:  # 最多显示最近 6 条
            lines.append(f"> {msg}")
        return "\n".join(lines)
