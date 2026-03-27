"""认知探测任务库。

任务设计原则（来自原始架构讨论）：
- 有约束：必须放弃某些东西，暴露真实优先级
- 有歧义：没有标准答案，处理方式本身就是数据
- 有压力：触发真实反应，而不是精心表演的回答

任务不是问卷，而是制造认知压力的情境，
让模型从用户行为中反推逻辑，而不是相信自述。
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)

TASK_DIMENSIONS = {
    "value_tradeoff": "价值取舍",
    "moral_dilemma": "道德困境",
    "priority_sort": "优先级排序",
    "conflict_resolution": "冲突处理",
    "resource_allocation": "资源分配",
    "identity_boundary": "身份边界",
    "emotional_response": "情绪反应",
    "trust_calibration": "信任校准",
}

DEFAULT_TASKS_FILE = "data/cognitive_tasks.json"


def _load_tasks_from_file(filepath: str = DEFAULT_TASKS_FILE) -> list[dict]:
    path = Path(filepath)
    if not path.exists():
        logger.warning("任务文件不存在: %s", filepath)
        return []
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("任务文件解析失败: %s", e)
        return []

DYNAMIC_TASK_PROMPT = """你是一个认知心理学家。根据以下关于一个人的现有信念和最近发现的矛盾/盲点，
设计一个针对性的认知探测任务。

任务设计要求：
1. 有约束：必须做选择，不能两全
2. 有歧义：没有标准答案
3. 针对性：能验证或澄清下面的矛盾/盲点

现有信念：
{beliefs}

发现的矛盾/盲点：
{contradiction}

请设计一个具体的情境任务（不是问卷题），让这个人在回答中自然暴露TA对这个矛盾的真实处理方式。

输出格式（JSON）：
{{"prompt": "任务情境描述", "probes": ["探测维度1", "探测维度2"], "target_contradiction": "针对的矛盾"}}"""


class TaskLibrary:
    """认知探测任务管理。"""

    def __init__(
        self,
        storage_path: str = "data/task_results.json",
        tasks_file: str = DEFAULT_TASKS_FILE,
    ) -> None:
        self.storage_path = Path(storage_path)
        self.tasks_file = tasks_file
        self.tasks = _load_tasks_from_file(tasks_file)
        self.completed: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text("utf-8"))
                raw = data.get("completed", {})
                self.completed = raw if isinstance(raw, dict) else {}
            except (json.JSONDecodeError, KeyError):
                pass

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"completed": self.completed}
        self.storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")

    def get_next_task(self, exclude_ids: set[str] | None = None) -> dict | None:
        """Get next uncompleted task, prioritizing diverse dimensions."""
        done_ids = set(self.completed.keys())
        if exclude_ids:
            done_ids |= exclude_ids

        remaining = [t for t in self.tasks if t["id"] not in done_ids]
        if not remaining:
            return None

        done_dims = {self.completed[tid].get("dimension") for tid in self.completed}
        uncovered = [t for t in remaining if t["dimension"] not in done_dims]
        pool = uncovered if uncovered else remaining

        return random.choice(pool)

    def record_response(self, task_id: str, user_response: str, task_prompt: str = "") -> dict:
        """Record a user's response to a task."""
        result = {
            "task_id": task_id,
            "response": user_response,
            "prompt": task_prompt,
            "dimension": next((t["dimension"] for t in self.tasks if t["id"] == task_id), ""),
            "probes": next((t["probes"] for t in self.tasks if t["id"] == task_id), []),
        }
        self.completed[task_id] = result
        self.save()
        return result

    def reload_tasks(self) -> int:
        """Reload tasks from the external JSON file."""
        self.tasks = _load_tasks_from_file(self.tasks_file)
        return len(self.tasks)

    def add_dynamic_task(self, task: dict) -> None:
        """Add a dynamically generated task and persist to disk."""
        if "id" not in task:
            task["id"] = f"dyn_{len(self.tasks):03d}"
        self.tasks.append(task)
        self._save_tasks()

    def _save_tasks(self) -> None:
        path = Path(self.tasks_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.tasks, ensure_ascii=False, indent=2), "utf-8")

    def get_completed_count(self) -> int:
        return len(self.completed)

    def get_total_count(self) -> int:
        return len(self.tasks)

    def get_all_responses(self) -> list[dict]:
        return list(self.completed.values())

    @staticmethod
    def generate_dynamic_task(
        api_client,
        model: str,
        beliefs: list[dict],
        contradiction: str,
    ) -> dict | None:
        """Use LLM to generate a targeted task for a specific contradiction."""
        belief_text = "\n".join(
            f"- {b.get('topic', '')}: {b.get('stance', '')} (置信度: {b.get('confidence', '?')})"
            for b in beliefs[:10]
        )
        prompt = DYNAMIC_TASK_PROMPT.format(beliefs=belief_text, contradiction=contradiction)

        try:
            resp = api_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是认知心理学家，擅长设计能暴露真实思维模式的情境任务。输出严格JSON格式。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )
            text = resp.choices[0].message.content or ""
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            task = json.loads(text)
            task["id"] = f"dyn_{random.randint(100, 999)}"
            task["dimension"] = "dynamic"
            return task
        except Exception as e:
            logger.warning("Failed to generate dynamic task: %s", e)
            return None
