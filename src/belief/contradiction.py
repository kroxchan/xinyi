import json
import logging

logger = logging.getLogger(__name__)

DETECTION_PROMPT = """你是一个逻辑矛盾检测专家。请分析以下信念列表，找出其中可能存在矛盾或冲突的信念对。

信念列表：
{beliefs_json}

要求：
1. 只标记真正存在逻辑矛盾或立场冲突的信念对
2. 不要标记仅仅是不同话题的信念
3. 返回严格的 JSON 数组格式

返回格式：
[{{"belief_a": "belief_id", "belief_b": "belief_id", "explanation": "矛盾原因"}}]

如果没有发现矛盾，返回空数组 []。"""

BATCH_SIZE = 20


class ContradictionDetector:
    def __init__(
        self,
        api_provider: str = "openai",
        api_key: str = "",
        model: str = "gpt-4o-mini",
    ) -> None:
        self.api_provider = api_provider
        self.model = model

        if api_provider == "openai":
            import openai
            self.client = openai.OpenAI(api_key=api_key)
        elif api_provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            raise ValueError(f"Unsupported api_provider: {api_provider}")

    def detect(self, beliefs: list[dict]) -> list[dict]:
        if len(beliefs) < 2:
            return []

        all_contradictions: list[dict] = []
        batches = self._make_batches(beliefs)

        for batch in batches:
            try:
                result = self._detect_batch(batch)
                all_contradictions.extend(result)
            except Exception as e:
                logger.error("Contradiction detection batch failed: %s", e)

        return all_contradictions

    def _make_batches(self, beliefs: list[dict]) -> list[list[dict]]:
        batches: list[list[dict]] = []
        for i in range(0, len(beliefs), BATCH_SIZE):
            batches.append(beliefs[i : i + BATCH_SIZE])
        return batches

    def _detect_batch(self, beliefs: list[dict]) -> list[dict]:
        summary = [
            {"id": b.get("id", ""), "topic": b.get("topic", ""), "stance": b.get("stance", "")}
            for b in beliefs
        ]
        prompt = DETECTION_PROMPT.format(beliefs_json=json.dumps(summary, ensure_ascii=False, indent=2))

        try:
            raw = self._call_llm(prompt)
            result = json.loads(raw)

            if isinstance(result, dict) and "contradictions" in result:
                result = result["contradictions"]

            if not isinstance(result, list):
                logger.warning("LLM returned non-list for contradictions")
                return []

            return [
                {
                    "belief_a": c.get("belief_a", ""),
                    "belief_b": c.get("belief_b", ""),
                    "explanation": c.get("explanation", ""),
                }
                for c in result
                if isinstance(c, dict)
            ]
        except json.JSONDecodeError:
            logger.error("Failed to parse contradiction detection response")
            return []

    def _call_llm(self, prompt: str) -> str:
        if self.api_provider == "openai":
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个逻辑矛盾检测专家，只返回 JSON 格式数据。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or "[]"
        else:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            return response.content[0].text
