"""推断引擎：从任务结果中提取思维模式。

不是记录用户说了什么，而是推断用户为什么这样选择。
从行为中反推逻辑（revealed preference），而不是相信自述（stated preference）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

INFERENCE_PROMPT = """你是认知心理学家。下面是一个人对一个认知探测任务的回答。

任务：
{task_prompt}

这个任务探测的维度：{probes}

用户的回答：
{response}

请分析（严格基于回答内容，不要脑补）：

1. **决策逻辑**：这个人做出选择的核心理由是什么？TA 的思考链条是怎样的？
2. **优先级排序**：在这个情境中，TA 把什么放在第一位？放弃了什么？
3. **隐含信念**：从这个选择能推断出 TA 有哪些底层信念？（格式：topic + stance + confidence 0-1）
4. **思维特征**：TA 是先理性分析再决策，还是先感觉再合理化？TA 考虑了几步？

输出严格 JSON 格式：
{{
  "decision_logic": "一句话概括决策逻辑",
  "priorities": ["第一优先", "第二优先", "被放弃的"],
  "inferred_beliefs": [
    {{"topic": "...", "stance": "...", "confidence": 0.7, "condition": "..."}}
  ],
  "thinking_style": "一句话描述思维特征",
  "evidence_quotes": ["直接引用的原文证据"]
}}"""


class InferenceEngine:
    """从认知任务的用户回答中推断思维模式。"""

    def __init__(self, api_client, model: str) -> None:
        self.client = api_client
        self.model = model

    def analyze_response(self, task_result: dict) -> dict:
        """Analyze a single task response to extract thinking patterns."""
        prompt = INFERENCE_PROMPT.format(
            task_prompt=task_result.get("prompt", ""),
            probes=", ".join(task_result.get("probes", [])),
            response=task_result.get("response", ""),
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是认知心理学家。只基于数据推断，不脑补。输出严格JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            text = resp.choices[0].message.content or ""
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except Exception as e:
            logger.warning("Inference failed for task %s: %s", task_result.get("task_id"), e)
            return {}

    def batch_analyze(self, task_results: list[dict]) -> list[dict]:
        """Analyze multiple task responses."""
        analyses = []
        for result in task_results:
            analysis = self.analyze_response(result)
            if analysis:
                analysis["task_id"] = result.get("task_id", "")
                analysis["dimension"] = result.get("dimension", "")
                analyses.append(analysis)
        return analyses

    def extract_beliefs_from_analyses(self, analyses: list[dict]) -> list[dict]:
        """Extract beliefs from all analyses, deduplicated by topic similarity."""
        all_beliefs = []
        for a in analyses:
            for b in a.get("inferred_beliefs", []):
                b["source"] = f"task_{a.get('task_id', '')}"
                all_beliefs.append(b)
        return all_beliefs

    def save_analyses(self, analyses: list[dict], filepath: str = "data/task_analyses.json") -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analyses, ensure_ascii=False, indent=2), "utf-8")
        logger.info("Saved %d task analyses to %s", len(analyses), filepath)

    @staticmethod
    def load_analyses(filepath: str = "data/task_analyses.json") -> list[dict]:
        path = Path(filepath)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, KeyError):
            return []
