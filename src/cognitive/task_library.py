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

DEFAULT_SEED_TASKS = [
    {
        "id": "seed_value_tradeoff_001",
        "dimension": "value_tradeoff",
        "prompt": "你周末原本答应陪伴侣去做一件对TA很重要的事，但家里突然提出希望你回去参加一场并非紧急、却很讲究“态度”的家庭安排。两边都没有强迫你，只是如果你不去，都会失望。你会怎么权衡？你会优先考虑承诺、关系重要性、现实后果，还是别的东西？你会怎么向没被选中的那一方解释？",
        "probes": ["价值权重排序", "关系承诺观", "代价承受方式"],
        "source_constructs": ["价值权衡", "承诺优先级", "关系责任"],
        "theory_basis": "moral trade-off / interpersonal prioritization",
    },
    {
        "id": "seed_moral_dilemma_001",
        "dimension": "moral_dilemma",
        "prompt": "你知道一个和你关系不错的人，正在隐瞒一件会明显伤害伴侣或家人的事。受影响的人现在并不知情，而你一旦揭开，可能会永久破坏你和这个朋友的关系。你会选择沉默、先私下劝对方自己坦白，还是直接告诉受影响的人？在你心里，“忠诚”“公平”“减少伤害”这几个原则谁更重要？",
        "probes": ["道德取向", "忠诚边界", "后果敏感度"],
        "source_constructs": ["后果敏感", "规范敏感", "忠诚-公平冲突"],
        "theory_basis": "moral trade-off system / dilemma judgment",
    },
    {
        "id": "seed_priority_sort_001",
        "dimension": "priority_sort",
        "prompt": "如果未来三年你只能把精力真正放在两件事上，你会怎么排序：事业上升、稳定亲密关系、个人自由、家庭期待、情绪健康？请你不仅说选什么，也说你愿意为这个排序承担什么代价，以及哪一种代价是你最不能接受的。",
        "probes": ["长期优先级", "损失厌恶", "自我排序方式"],
        "source_constructs": ["目标层级", "代价承受阈值", "自我一致性"],
        "theory_basis": "social-cognitive personality signatures / goal hierarchy",
    },
    {
        "id": "seed_conflict_resolution_001",
        "dimension": "conflict_resolution",
        "prompt": "你和很重要的人刚发生冲突，对方说“我现在不想聊”。你这边却会因为悬着而难受，甚至很难睡着。你会继续追着沟通、先发一段解释/安抚、强迫自己等对方冷静，还是先抽离去做别的？你最怕的是关系变淡、被误解，还是情绪继续升级？",
        "probes": ["冲突修复节奏", "依恋焦虑线索", "边界感"],
        "source_constructs": ["attachment anxiety", "conflict repair", "reassurance seeking"],
        "theory_basis": "adult romantic attachment (ECR-R)",
    },
    {
        "id": "seed_resource_allocation_001",
        "dimension": "resource_allocation",
        "prompt": "你这个月只剩下一笔有限的时间和金钱预算。一个选择是优先满足自己一个很久以来的需求，另一个选择是去支持伴侣/家人的现实困难。两边都不是生死攸关，只是谁先被照顾，会明显反映你把谁放在前面。你通常会怎么分？如果选了自己，你会不会内疚；如果选了别人，你会不会委屈？",
        "probes": ["资源分配偏好", "自我照顾能力", "亏欠/委屈阈值"],
        "source_constructs": ["communal orientation", "self-sacrifice", "guilt sensitivity"],
        "theory_basis": "interpersonal prioritization / self-other regulation",
    },
    {
        "id": "seed_identity_boundary_001",
        "dimension": "identity_boundary",
        "prompt": "伴侣希望你为了关系做一个改变，例如少和某类朋友来往、少公开表达某些观点，或调整某种你一直以来的生活方式。这个要求不算完全不合理，但会让你隐隐觉得“再退一步就不像我了”。你会怎么判断这件事是正常磨合，还是已经碰到你的身份边界？",
        "probes": ["身份边界", "关系妥协模式", "自主性需求"],
        "source_constructs": ["autonomy", "boundary setting", "identity coherence"],
        "theory_basis": "self-determination / boundary regulation",
    },
    {
        "id": "seed_emotional_response_001",
        "dimension": "emotional_response",
        "prompt": "你认真准备的一件事，被最在意的人轻描淡写地否定了。对方可能不是恶意，但你当下明显受伤。你的第一反应更像哪一种：立刻解释、沉默抽离、冷下来、阴阳一句、要求对方看见你的情绪，还是别的？如果对方想修复，你最希望TA做的是解释、道歉、共情、安抚，还是先给空间？",
        "probes": ["受伤后的第一反应", "情绪调节方式", "被安抚需求"],
        "source_constructs": ["emotion regulation", "interpersonal soothing", "repair preference"],
        "theory_basis": "emotion regulation / interpersonal emotion regulation in couples",
    },
    {
        "id": "seed_trust_calibration_001",
        "dimension": "trust_calibration",
        "prompt": "你后来才知道，对方有一件事没有主动告诉你。对方解释说“不是故意瞒你，只是觉得没必要说，怕你多想”。你会把这更倾向理解成：欺骗、界限不同、表达习惯差异，还是先保留判断继续观察？你通常需要对方给出什么，才能重新恢复信任感？",
        "probes": ["信任阈值", "归因方式", "信任修复条件"],
        "source_constructs": ["attachment avoidance/anxiety", "epistemic trust", "attribution style"],
        "theory_basis": "adult attachment / trust calibration",
    },
]


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


def _clone_seed_tasks() -> list[dict]:
    return [dict(task) for task in DEFAULT_SEED_TASKS]

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
        self.ensure_seed_tasks()

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
        self.ensure_seed_tasks()
        return len(self.tasks)

    def ensure_seed_tasks(self) -> int:
        """Guarantee the library has an initial calibration task set.

        Fresh installs may not ship `data/cognitive_tasks.json`, and dynamic
        contradiction probes should not replace the default calibration tasks.
        """
        seed_tasks = _clone_seed_tasks()
        existing_by_id = {
            task.get("id"): idx for idx, task in enumerate(self.tasks) if task.get("id")
        }
        existing_dims = {
            task.get("dimension")
            for task in self.tasks
            if task.get("dimension") in TASK_DIMENSIONS
        }
        added = 0
        updated = 0
        for task in seed_tasks:
            task_id = task["id"]
            if task_id in existing_by_id:
                self.tasks[existing_by_id[task_id]] = task
                updated += 1
                continue
            if task["dimension"] not in existing_dims:
                self.tasks.append(task)
                existing_dims.add(task["dimension"])
                added += 1
        if not self.tasks and not (added or updated):
            self.tasks = seed_tasks
            added = len(seed_tasks)
        if added or updated:
            self._save_tasks()
            logger.info("已同步默认校准任务：新增 %d 个，更新 %d 个", added, updated)
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
