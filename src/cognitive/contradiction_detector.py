"""矛盾检测器：系统的神经系统。

发现矛盾 → 生成任务 → 采集行为 → 更新信念 → 解决矛盾。
不只是标记冲突，而是主动触发探测来验证。

来自原始架构："矛盾检测是系统的神经系统——
它连接所有层——发现矛盾→生成任务→采集行为→更新信念→解决矛盾。
没有这个，系统只是在堆数据，不是在学习。"
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

CONTRADICTION_CHECK_PROMPT = """你是逻辑分析师。下面是一个人的信念图谱中的所有信念条目。
请检查是否存在矛盾、不一致或条件依赖关系。

信念列表：
{beliefs}

{new_belief_section}

请找出所有矛盾对，输出 JSON 数组：
[
  {{
    "belief_a": "信念A的id或内容摘要",
    "belief_b": "信念B的id或内容摘要",
    "type": "direct_conflict | conditional_conflict | tension",
    "explanation": "为什么矛盾",
    "resolution_hint": "可能的解释（比如：在不同条件下成立）",
    "probe_question": "如果要验证这个矛盾，应该问什么问题或出什么任务"
  }}
]

如果没有矛盾，输出空数组 []。"""


class ContradictionDetector:
    """检测信念图谱中的矛盾，触发追问任务。"""

    def __init__(self, api_client, model: str) -> None:
        self.client = api_client
        self.model = model

    def check_new_belief(
        self,
        new_belief: dict,
        existing_beliefs: list[dict],
    ) -> list[dict]:
        """Check if a new belief contradicts existing ones."""
        if not existing_beliefs:
            return []

        belief_text = "\n".join(
            f"[{b.get('id', '?')}] {b.get('topic', '')}: {b.get('stance', '')} "
            f"(条件: {b.get('condition', '无')}, 置信度: {b.get('confidence', '?')})"
            for b in existing_beliefs[:30]
        )
        new_text = (
            f"[新] {new_belief.get('topic', '')}: {new_belief.get('stance', '')} "
            f"(条件: {new_belief.get('condition', '无')}, 来源: {new_belief.get('source', '?')})"
        )

        prompt = CONTRADICTION_CHECK_PROMPT.format(
            beliefs=belief_text,
            new_belief_section=f"\n新加入的信念（重点检查这条与现有的冲突）：\n{new_text}",
        )

        return self._call_llm(prompt)

    def full_scan(self, all_beliefs: list[dict]) -> list[dict]:
        """Scan entire belief graph for contradictions."""
        if len(all_beliefs) < 2:
            return []

        belief_text = "\n".join(
            f"[{b.get('id', '?')}] {b.get('topic', '')}: {b.get('stance', '')} "
            f"(条件: {b.get('condition', '无')}, 置信度: {b.get('confidence', '?')})"
            for b in all_beliefs[:50]
        )

        prompt = CONTRADICTION_CHECK_PROMPT.format(
            beliefs=belief_text,
            new_belief_section="",
        )

        return self._call_llm(prompt)

    def _call_llm(self, prompt: str) -> list[dict]:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是逻辑分析师，擅长检测信念体系中的矛盾。输出严格JSON数组。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            text = resp.choices[0].message.content or ""
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(text)
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.warning("Contradiction check failed: %s", e)
            return []

    def generate_probe_tasks(
        self,
        contradictions: list[dict],
        task_library,
    ) -> list[dict]:
        """For each contradiction, create a dynamic probe task if one doesn't exist."""
        new_tasks = []
        for c in contradictions:
            probe_q = c.get("probe_question", "")
            if not probe_q:
                continue
            task = {
                "id": f"probe_{hash(probe_q) % 10000:04d}",
                "dimension": "contradiction_probe",
                "prompt": probe_q,
                "probes": [c.get("type", ""), c.get("explanation", "")[:50]],
                "target_contradiction": c.get("explanation", ""),
            }
            task_library.add_dynamic_task(task)
            new_tasks.append(task)
        return new_tasks
