"""主动探测系统：本人模式下的动态任务注入。

在和用户对话过程中，发现逻辑盲点或内部矛盾时，
主动生成针对性的情境任务来验证——而不是走预设流程。

来自原始架构：
"分身在和你对话的过程中，发现了某个逻辑盲点或内部矛盾，
它可以主动生成一个针对性的任务来验证——而不是走预设的问卷流程。
比如：它发现你在谈钱的时候说'不在乎回报'，但在另一个场景里你的选择却很计较得失。
它不直接问你'你到底在不在乎钱'——它给你出一道资源分配题，看你怎么分。"
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

BLIND_SPOT_DETECT_PROMPT = """你是一个认知心理学家。下面是一段正在进行的对话历史和这个人已有的信念图谱。

对话历史（最近几轮）：
{chat_history}

已有信念图谱（部分）：
{beliefs}

请分析：
1. 这段对话中，这个人是否暴露了与已有信念矛盾的倾向？
2. 是否有某个信念维度在对话中被触及，但现有图谱中缺乏数据？
3. 是否有 "说一套做一套" 的迹象？

如果发现了盲点或矛盾，设计一个自然的追问（不像考试题，而是像聊天中自然会问的问题），
用来验证这个盲点。

如果没有发现有价值的盲点，返回 null。

输出 JSON：
{{
  "detected": true/false,
  "type": "contradiction | blind_spot | inconsistency",
  "description": "发现了什么",
  "evidence": "从对话中的哪句话推断的",
  "probe": {{
    "mode": "natural_question | scenario_task",
    "content": "自然追问或情境任务的内容",
    "target": "想验证的具体信念/维度"
  }}
}}

如果没有发现：{{"detected": false}}"""


class ActiveProbe:
    """本人模式下的主动探测系统。"""

    def __init__(self, api_client, model: str) -> None:
        self.client = api_client
        self.model = model
        self.probe_cooldown: int = 0
        self.min_turns_between_probes: int = 5
        self.probes_this_session: list[dict] = []

    def should_probe(self, turn_count: int) -> bool:
        """Decide if we should attempt a probe based on conversation state."""
        if turn_count < 3:
            return False
        if self.probe_cooldown > 0:
            self.probe_cooldown -= 1
            return False
        return turn_count % self.min_turns_between_probes == 0

    def detect_and_probe(
        self,
        chat_history: list[dict],
        beliefs: list[dict],
    ) -> dict | None:
        """Analyze conversation for blind spots and generate a probe if found."""
        history_text = "\n".join(
            f"{'我' if m.get('role') == 'assistant' else '对方'}: {m.get('content', '')}"
            for m in (chat_history or [])[-10:]
        )

        belief_text = "\n".join(
            f"- {b.get('topic', '')}: {b.get('stance', '')} (置信度: {b.get('confidence', '?')})"
            for b in beliefs[:20]
        )

        prompt = BLIND_SPOT_DETECT_PROMPT.format(
            chat_history=history_text,
            beliefs=belief_text,
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是认知心理学家。分析对话中的信念盲点。输出严格JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
            )
            text = resp.choices[0].message.content or ""
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            result = json.loads(text)

            if result.get("detected"):
                self.probe_cooldown = self.min_turns_between_probes
                self.probes_this_session.append(result)
                return result
            return None
        except Exception as e:
            logger.warning("Active probe detection failed: %s", e)
            return None

    def format_probe_as_message(self, probe_result: dict) -> str | None:
        """Convert a probe detection result into a natural chat message."""
        if not probe_result or not probe_result.get("detected"):
            return None
        probe = probe_result.get("probe", {})
        return probe.get("content")

    def reset_session(self) -> None:
        self.probe_cooldown = 0
        self.probes_this_session = []
