"""连续性锚点 — 维护身份/矛盾/张力锚点。

管理 context/anchors.md，记录：
- identity: 身份锚点（我是谁，我的核心特质）
- contradiction: 矛盾锚点（言行不一致的地方）
- tension: 张力锚点（未解决的冲突或悬而未决的问题）

Example:
    anchors = AnchorTracker(Path("data/twin_workspace/context/anchors.md"))
    anchors.add("identity", "用户最近在思考职业转型", ttl_seconds=3600)
    anchors.add("tension", "关于是否搬去另一个城市还没决定", ttl_seconds=7200)
    active = anchors.get_active()
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logging_config import get_logger

logger = get_logger(__name__)

ANCHORS_TEMPLATE = """\
# 连续性锚点

> 自动生成，最后更新 {updated}

## 身份锚点

{identity_anchors}

## 矛盾锚点

{contradiction_anchors}

## 张力锚点

{tension_anchors}

---
"""

ANCHOR_ITEM_TEMPLATE = """\
- **{content}**
  - 添加于: {created}
  - 状态: {status}
  - 备注: {note}
"""


class AnchorTracker:
    """维护连续性锚点（身份/矛盾/张力）。

    特性：
    - TTL 支持（超时自动过期）
    - 人类可读 Markdown 格式
    - 支持手动添加/删除/更新
    - 自动清理过期锚点
    """

    ANCHOR_TYPES = ["identity", "contradiction", "tension"]

    ANCHOR_TYPE_LABELS = {
        "identity": "身份锚点",
        "contradiction": "矛盾锚点",
        "tension": "张力锚点",
    }

    def __init__(
        self,
        anchors_file: str | Path = "data/twin_workspace/context/anchors.md",
        default_ttl: int = 7200,
    ) -> None:
        self.anchors_file = Path(anchors_file)
        self.anchors_file.parent.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

        # 内存中的锚点状态
        # {type: {content: {created, expires_at, status, note}}}
        self._anchors: dict[str, dict[str, dict[str, Any]]] = {
            anchor_type: {} for anchor_type in self.ANCHOR_TYPES
        }

        # 加载已有锚点
        self._load()

    def _load(self) -> None:
        """从文件加载锚点状态。"""
        if not self.anchors_file.exists():
            return

        try:
            content = self.anchors_file.read_text(encoding="utf-8")
            current_type = None

            for line in content.split("\n"):
                line = line.strip()

                # 检测锚点类型标题
                if line == "## 身份锚点":
                    current_type = "identity"
                    continue
                elif line == "## 矛盾锚点":
                    current_type = "contradiction"
                    continue
                elif line == "## 张力锚点":
                    current_type = "tension"
                    continue
                elif line.startswith("## "):
                    current_type = None
                    continue

                # 解析锚点条目
                if current_type and line.startswith("- **"):
                    anchor_content = re.search(r"- \*\*(.+?)\*\*", line)
                    if anchor_content:
                        content_key = anchor_content.group(1)
                        self._anchors[current_type][content_key] = {
                            "created": datetime.now().isoformat(),
                            "expires_at": None,
                            "status": "active",
                            "note": "",
                        }

            logger.debug("Loaded anchors from file")

        except Exception as e:
            logger.warning("Failed to load anchors: %s", e)

    def _save(self) -> None:
        """保存锚点状态到文件。"""
        try:
            now = datetime.now()

            def format_section(anchor_type: str) -> str:
                anchors = self._anchors.get(anchor_type, {})
                if not anchors:
                    return "（暂无）"

                lines = []
                for content, info in anchors.items():
                    created = info.get("created", "未知")
                    status = info.get("status", "active")
                    note = info.get("note", "")

                    lines.append(ANCHOR_ITEM_TEMPLATE.format(
                        content=content,
                        created=created,
                        status=status,
                        note=note if note else "无",
                    ))

                return "\n".join(lines)

            content = ANCHORS_TEMPLATE.format(
                updated=now.strftime("%Y-%m-%d %H:%M"),
                identity_anchors=format_section("identity"),
                contradiction_anchors=format_section("contradiction"),
                tension_anchors=format_section("tension"),
            )

            self.anchors_file.write_text(content, encoding="utf-8")

        except Exception as e:
            logger.error("Failed to save anchors: %s", e)

    def add(
        self,
        anchor_type: str,
        content: str,
        ttl_seconds: int | None = None,
        note: str = "",
    ) -> bool:
        """添加锚点。

        Args:
            anchor_type: 锚点类型 (identity/contradiction/tension)
            content: 锚点内容
            ttl_seconds: 生存时间（秒），None 表示永不过期
            note: 备注信息

        Returns:
            是否添加成功
        """
        if anchor_type not in self.ANCHOR_TYPES:
            logger.warning("Invalid anchor type: %s", anchor_type)
            return False

        if not content or not content.strip():
            logger.warning("Empty anchor content")
            return False

        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl

        self._anchors[anchor_type][content.strip()] = {
            "created": datetime.now().isoformat(),
            "expires_at": time.time() + ttl if ttl > 0 else None,
            "status": "active",
            "note": note,
        }

        self._save()
        logger.info("Added %s anchor: %s", anchor_type, content[:50])
        return True

    def add_identity(self, content: str, note: str = "") -> bool:
        """快捷方法：添加身份锚点。"""
        return self.add("identity", content, note=note)

    def add_contradiction(self, content: str, note: str = "") -> bool:
        """快捷方法：添加矛盾锚点。"""
        return self.add("contradiction", content, note=note)

    def add_tension(self, content: str, note: str = "") -> bool:
        """快捷方法：添加张力锚点。"""
        return self.add("tension", content, note=note)

    def remove(self, anchor_type: str, content: str) -> bool:
        """移除锚点。"""
        if anchor_type not in self.ANCHOR_TYPES:
            return False

        if content in self._anchors[anchor_type]:
            del self._anchors[anchor_type][content]
            self._save()
            logger.info("Removed %s anchor: %s", anchor_type, content[:50])
            return True

        return False

    def get_active(
        self,
        anchor_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回未过期的活跃锚点。

        Args:
            anchor_type: 可选，筛选特定类型

        Returns:
            锚点列表，每项包含 type, content, created, expires_at, note
        """
        self.cleanup()

        results = []
        types_to_check = [anchor_type] if anchor_type else self.ANCHOR_TYPES

        for atype in types_to_check:
            if atype not in self.ANCHOR_TYPES:
                continue

            for content, info in self._anchors[atype].items():
                expires_at = info.get("expires_at")
                if expires_at and time.time() > expires_at:
                    continue

                results.append({
                    "type": atype,
                    "content": content,
                    "created": info.get("created"),
                    "expires_at": expires_at,
                    "note": info.get("note", ""),
                })

        return results

    def get_all(
        self,
        anchor_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回所有锚点（包括过期的）。"""
        results = []
        types_to_check = [anchor_type] if anchor_type else self.ANCHOR_TYPES

        for atype in types_to_check:
            if atype not in self.ANCHOR_TYPES:
                continue

            for content, info in self._anchors[atype].items():
                results.append({
                    "type": atype,
                    "content": content,
                    "created": info.get("created"),
                    "expires_at": info.get("expires_at"),
                    "note": info.get("note", ""),
                })

        return results

    def cleanup(self) -> int:
        """清理过期锚点。

        Returns:
            清理的锚点数量
        """
        now = time.time()
        cleaned = 0

        for anchor_type in self.ANCHOR_TYPES:
            to_remove = []

            for content, info in self._anchors[anchor_type].items():
                expires_at = info.get("expires_at")
                if expires_at and now > expires_at:
                    to_remove.append(content)

            for content in to_remove:
                del self._anchors[anchor_type][content]
                cleaned += 1

        if cleaned > 0:
            self._save()
            logger.info("Cleaned up %d expired anchors", cleaned)

        return cleaned

    def search(self, query: str) -> list[dict[str, Any]]:
        """在锚点中搜索。"""
        results = []
        query_lower = query.lower()

        for anchor in self.get_all():
            if query_lower in anchor["content"].lower():
                results.append(anchor)

        return results

    def resolve(self, anchor_type: str, content: str) -> bool:
        """标记锚点为已解决。"""
        if anchor_type not in self.ANCHOR_TYPES:
            return False

        if content in self._anchors[anchor_type]:
            self._anchors[anchor_type][content]["status"] = "resolved"
            self._save()
            logger.info("Resolved %s anchor: %s", anchor_type, content[:50])
            return True

        return False

    def format_for_context(self) -> str:
        """格式化锚点用于 prompt 上下文。"""
        active = self.get_active()

        if not active:
            return ""

        lines = ["## 当前锚点"]

        by_type = {}
        for anchor in active:
            by_type.setdefault(anchor["type"], []).append(anchor)

        for anchor_type in ["identity", "contradiction", "tension"]:
            anchors = by_type.get(anchor_type, [])
            if not anchors:
                continue

            label = self.ANCHOR_TYPE_LABELS.get(anchor_type, anchor_type)
            lines.append(f"\n### {label}")

            for anchor in anchors:
                lines.append(f"- {anchor['content']}")

        return "\n".join(lines)
