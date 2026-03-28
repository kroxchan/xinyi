"""策展记忆管理器 — 从日志蒸馏的持久知识。

管理 memory.md 文件，存储从每日日志中提炼的长期记忆。
格式参考 OpenClaw，包含：关于我、重要经历、关系动态等板块。

Example:
    memory = CuratedMemory(Path("data/twin_workspace/memory.md"))
    memory.update([
        "用户在互联网行业工作，经常加班",
        "最近在考虑换工作",
    ])
    content = memory.load()
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logging_config import get_logger

logger = get_logger(__name__)

MEMORY_TEMPLATE = """\
# 长期记忆

> 由心译 (xinyi) 自动维护，最后更新 {updated}

## 关于我

{about_me}

## 重要经历

{experiences}

## 关系动态

{relationship}

## 沟通偏好

{preferences}

## 未解决的问题

{open_issues}

---
*记忆文件，人类可直接编辑。删除或修改内容不会影响系统运行。*
"""


class CuratedMemory:
    """管理 memory.md — 从日志蒸馏的持久知识。

    特性：
    - 结构化 Markdown 格式
    - 支持增量更新
    - 人类可读可编辑
    - 自动去重（基于内容相似度）
    """

    DEFAULT_SECTIONS = [
        "about_me",
        "experiences",
        "relationship",
        "preferences",
        "open_issues",
    ]

    def __init__(
        self,
        memory_file: str | Path = "data/twin_workspace/memory.md",
    ) -> None:
        self.memory_file = Path(memory_file)
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> str:
        """加载 memory.md 内容。"""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def exists(self) -> bool:
        """检查记忆文件是否存在且有内容。"""
        if not self.memory_file.exists():
            return False
        content = self.load()
        return bool(content.strip())

    def get_sections(self) -> dict[str, str]:
        """解析记忆文件的各个板块。

        Returns:
            字典，key 为板块名（about_me, experiences 等），
            value 为板块内容（不含标题）
        """
        content = self.load()
        if not content:
            return {s: "" for s in self.DEFAULT_SECTIONS}

        sections: dict[str, str] = {s: "" for s in self.DEFAULT_SECTIONS}

        for section in self.DEFAULT_SECTIONS:
            pattern = rf"## {section.replace('_', ' ').title()}\s*\n(.*?)(?=^## |\Z)"
            match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
            if match:
                sections[section] = match.group(1).strip()

        return sections

    def update(
        self,
        new_insights: list[str],
        section: str = "about_me",
    ) -> bool:
        """追加新洞察到 memory.md 的指定板块。

        Args:
            new_insights: 新洞察列表，每项一行
            section: 目标板块名

        Returns:
            是否更新成功
        """
        if not new_insights:
            return True

        if section not in self.DEFAULT_SECTIONS:
            logger.warning("Unknown section: %s, defaulting to about_me", section)
            section = "about_me"

        try:
            content = self.load()
            sections = self.get_sections()

            # 去重：检查新洞察是否已存在
            existing_items = self._extract_bullet_points(sections.get(section, ""))
            filtered_insights = [
                insight for insight in new_insights
                if not self._is_similar(insight, existing_items)
            ]

            if not filtered_insights:
                logger.debug("All insights already exist, skipping update")
                return True

            # 追加新洞察（带时间戳）
            timestamp = datetime.now().strftime("%Y-%m-%d")
            new_items = "\n".join(
                f"- {insight.strip()} ({timestamp})"
                for insight in filtered_insights
            )

            if sections[section]:
                sections[section] += "\n" + new_items
            else:
                sections[section] = new_items

            # 重新构建文件
            new_content = MEMORY_TEMPLATE.format(
                updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
                about_me=sections.get("about_me", ""),
                experiences=sections.get("experiences", ""),
                relationship=sections.get("relationship", ""),
                preferences=sections.get("preferences", ""),
                open_issues=sections.get("open_issues", ""),
            )

            self.memory_file.write_text(new_content, encoding="utf-8")
            logger.info(
                "Updated memory.md: added %d insights to %s",
                len(filtered_insights), section
            )
            return True

        except Exception as e:
            logger.error("Failed to update memory: %s", e)
            return False

    def update_from_distillation(
        self,
        distillation_result: dict[str, list[str]],
    ) -> bool:
        """从蒸馏结果批量更新各板块。

        Args:
            distillation_result: 字典，key 为板块名，value 为该板块的新洞察列表
                Example: {
                    "about_me": ["用户最近在学习烹饪"],
                    "preferences": ["偏好安静的约会环境"],
                }

        Returns:
            是否完全成功
        """
        success = True
        for section, insights in distillation_result.items():
            if insights:
                if not self.update(insights, section=section):
                    success = False
        return success

    def search(self, query: str) -> list[str]:
        """在记忆中搜索包含关键词的内容。

        Args:
            query: 搜索关键词

        Returns:
            匹配的条目列表
        """
        content = self.load()
        if not content:
            return []

        results = []
        for line in content.split("\n"):
            if query.lower() in line.lower() and line.strip().startswith("-"):
                results.append(line.strip())
        return results

    def initialize(self) -> None:
        """初始化空的记忆文件。"""
        if not self.exists():
            content = MEMORY_TEMPLATE.format(
                updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
                about_me="（暂无记忆）",
                experiences="（暂无记录）",
                relationship="（暂无记录）",
                preferences="（暂无记录）",
                open_issues="（暂无待处理事项）",
            )
            self.memory_file.write_text(content, encoding="utf-8")
            logger.info("Initialized memory.md")

    @staticmethod
    def _extract_bullet_points(text: str) -> list[str]:
        """提取文本中的所有列表项。"""
        items = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("-"):
                # 去掉时间戳
                cleaned = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", line[1:].strip())
                items.append(cleaned)
        return items

    @staticmethod
    def _is_similar(new_item: str, existing_items: list[str], threshold: float = 0.7) -> bool:
        """简单文本相似度判断（基于关键词重叠）。"""
        if not existing_items:
            return False

        new_words = set(CuratedMemory._tokenize(new_item))
        if not new_words:
            return False

        for existing in existing_items:
            existing_words = set(CuratedMemory._tokenize(existing))
            if not existing_words:
                continue

            overlap = len(new_words & existing_words)
            union = len(new_words | existing_words)
            if union > 0 and overlap / union >= threshold:
                return True

        return False

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单分词（按空格和标点）。"""
        text = re.sub(r"[^\w\s]", "", text.lower())
        return [w for w in text.split() if len(w) >= 2]
