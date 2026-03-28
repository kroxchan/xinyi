"""蒸馏逻辑 — 从日志到策展记忆。

将每日日志中的新内容蒸馏到策展记忆（memory.md）。
使用 LLM 提取「持久事实」，避免一次性情绪反应被固化。

Example:
    insights = distill_daily_log_to_memory(
        log_date="2026-03-28",
        current_memory="data/twin_workspace/memory.md",
        api_client=client,
        model="gpt-4o-mini"
    )
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.logging_config import get_logger

logger = get_logger(__name__)

DISTILL_PROMPT = """\
你是一位记忆策展人。你的任务是从对话日志中提炼出**持久事实**，添加到长期记忆中。

## 原则

1. **只提取客观事实**：具体事件、偏好、计划、关系状态
2. **过滤情绪噪音**：不要记录一次性的情绪反应（如「今天心情不好」）
3. **识别模式**：从重复出现的话题中提炼共性
4. **区分确定性与推测**：
   - 确定：用户明确说过的
   - 可能：暗示或推测的

## 当前记忆（参考，避免重复）

{current_memory}

## 待分析日志

{log_content}

## 你的任务

分析日志，输出 JSON 格式的洞察，按板块分类：

{{
    "about_me": [
        "洞察1（关于用户本人的事实）",
        "洞察2"
    ],
    "experiences": [
        "重要经历1",
        "重要经历2"
    ],
    "relationship": [
        "关系动态1",
        "关系动态2"
    ],
    "preferences": [
        "偏好1",
        "偏好2"
    ],
    "open_issues": [
        "悬而未决的问题1",
        "悬而未决的问题2"
    ]
}}

规则：
- 每个板块最多 5 条洞察
- 只输出 JSON，不要其他文字
- 如果某板块没有新洞察，输出空数组 []
- 内容要具体，不要泛泛而谈（如「用户工作繁忙」而非「用户很忙」）
"""


def distill_daily_log_to_memory(
    log_date: str,
    logs_dir: str | Path,
    current_memory_file: str | Path,
    api_client: Any,
    model: str = "gpt-4o-mini",
) -> dict[str, list[str]]:
    """用 LLM 从单日日志中提炼新洞察。

    Args:
        log_date: 日志日期（YYYY-MM-DD）
        logs_dir: 日志目录
        current_memory_file: 当前记忆文件路径
        api_client: OpenAI API 客户端
        model: 使用的模型

    Returns:
        提炼出的洞察字典
    """
    logs_dir = Path(logs_dir)
    current_memory_file = Path(current_memory_file)

    # 读取日志内容
    log_file = logs_dir / f"{log_date}.md"
    if not log_file.exists():
        logger.warning("Log file not found: %s", log_file)
        return {}

    log_content = log_file.read_text(encoding="utf-8")

    # 读取当前记忆
    current_memory = ""
    if current_memory_file.exists():
        current_memory = current_memory_file.read_text(encoding="utf-8")
        # 截取关键部分
        if len(current_memory) > 2000:
            current_memory = current_memory[:2000] + "\n..."

    # 构建 prompt
    prompt = DISTILL_PROMPT.format(
        current_memory=current_memory or "（暂无记忆）",
        log_content=log_content[:4000],
    )

    try:
        resp = api_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个记忆策展专家。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        raw = (resp.choices[0].message.content or "").strip()

        # 解析 JSON
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

        result = json.loads(raw)

        # 验证结构
        expected_keys = ["about_me", "experiences", "relationship", "preferences", "open_issues"]
        for key in expected_keys:
            if key not in result:
                result[key] = []
            elif not isinstance(result[key], list):
                result[key] = []

        logger.info("Distilled %d insights from %s",
                     sum(len(v) for v in result.values()), log_date)

        return result

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse distillation JSON: %s", e)
        return {}
    except Exception as e:
        logger.error("Distillation failed: %s", e)
        return {}


def distill_recent_logs(
    logs_dir: str | Path,
    current_memory_file: str | Path,
    api_client: Any,
    model: str = "gpt-4o-mini",
    days: int = 3,
) -> dict[str, list[str]]:
    """蒸馏最近 N 天的日志。

    Args:
        logs_dir: 日志目录
        current_memory_file: 当前记忆文件
        api_client: API 客户端
        model: 模型名
        days: 天数

    Returns:
        合并后的洞察字典
    """
    logs_dir = Path(logs_dir)
    current_memory_file = Path(current_memory_file)

    today = datetime.now()
    all_insights: dict[str, list[str]] = {
        "about_me": [],
        "experiences": [],
        "relationship": [],
        "preferences": [],
        "open_issues": [],
    }

    for i in range(days):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")

        insights = distill_daily_log_to_memory(
            log_date=date_str,
            logs_dir=logs_dir,
            current_memory_file=current_memory_file,
            api_client=api_client,
            model=model,
        )

        for key, values in insights.items():
            if key in all_insights and values:
                all_insights[key].extend(values)

    # 去重
    for key in all_insights:
        all_insights[key] = _dedupe_insights(all_insights[key])

    logger.info("Total distilled: %d insights from %d days",
                sum(len(v) for v in all_insights.values()), days)

    return all_insights


def _dedupe_insights(insights: list[str]) -> list[str]:
    """去除重复的洞察。"""
    seen = set()
    unique = []

    for insight in insights:
        # 标准化用于比较
        normalized = re.sub(r"\s+", "", insight.lower())
        normalized = re.sub(r"[的de是]", "", normalized)[:30]

        if normalized not in seen and len(normalized) >= 4:
            seen.add(normalized)
            unique.append(insight)

    return unique


def should_distill(
    logs_dir: str | Path,
    last_distill_file: str | Path,
    max_interval_hours: int = 24,
) -> bool:
    """检查是否应该执行蒸馏。

    Args:
        logs_dir: 日志目录
        last_distill_file: 上次蒸馏时间记录文件
        max_interval_hours: 最大间隔小时数

    Returns:
        是否应该执行蒸馏
    """
    logs_dir = Path(logs_dir)
    last_distill_file = Path(last_distill_file)

    # 检查是否有新的日志文件
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    today_log = logs_dir / f"{today_str}.md"

    if not today_log.exists():
        return False

    # 检查上次蒸馏时间
    if not last_distill_file.exists():
        return True

    try:
        data = json.loads(last_distill_file.read_text(encoding="utf-8"))
        last_distill = datetime.fromisoformat(data.get("last_distill", "2000-01-01"))
        hours_since = (today - last_distill).total_seconds() / 3600
        return hours_since >= max_interval_hours
    except Exception:
        return True


def mark_distilled(
    last_distill_file: str | Path,
    log_date: str,
) -> None:
    """标记蒸馏完成。"""
    last_distill_file = Path(last_distill_file)
    last_distill_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "last_distill": datetime.now().isoformat(),
        "last_distill_log": log_date,
    }

    last_distill_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
