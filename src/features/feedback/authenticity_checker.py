"""真实性检查器 — 「不像 TA」即时反馈

当用户感觉分身回复不像真实的 TA 时，提供：
1. 真实性评分（0-1，越高越像）
2. 具体差异描述
3. 真实对话参考片段
4. 再训练建议
"""
from __future__ import annotations

import json
import logging
from typing import Any

from src.logging_config import get_logger

logger = get_logger(__name__)

MIN_CONVERSATION_COUNT = 5
RETRIEVAL_TOP_K = 10
FINAL_EXAMPLES_COUNT = 3

AUTHENTICITY_CHECK_PROMPT = """\
你是一位亲密关系语言分析师，帮助用户判断 AI 分身的回复是否像真人。

【任务】
对比「AI分身回复」与「真实对话片段」，分析差异并给出评估。

【AI分身回复】
{agent_reply}

【真实对话片段】
{real_examples}

【档案信息】
- 姓名：{name}
- 沟通风格：{style_hint}
- 情绪习惯：{emotion_hint}

【分析要求】
请从以下维度对比：
1. 语气温度：太热情/太冷淡/刚好？
2. 表达长度：太长/太短/符合习惯？
3. 词汇选择：用了对方不常用的词/说法？
4. 逻辑结构：太有条理/太碎/自然？
5. 情感表达：太直接/太含蓄/符合性格？

【输出格式】请严格输出以下 JSON（不要输出任何其他内容）：
{{
    "authenticity_score": <0.0到1.0的浮点数，越高越像>,
    "deviation_notes": "<30字以内的人类可读差异描述>",
    "real_examples": ["<真实片段1>", "<真实片段2>", "<真实片段3>"],
    "retrain_suggestion": "<50字以内的再训练建议>"
}}
"""


class AuthenticityChecker:
    """检查分身回复的真实性，对比真实对话给出反馈。"""

    def __init__(
        self,
        api_client: Any,
        vector_store: Any,
        persona_profile: dict | None = None,
        emotion_profile: dict | None = None,
        embedder: Any | None = None,
        model: str = "gpt-4o-mini",
    ) -> None:
        self.client = api_client
        self.vector_store = vector_store
        self.persona_profile = persona_profile or {}
        self.emotion_profile = emotion_profile or {}
        self.embedder = embedder
        self.model = model

    def _get_style_hint(self) -> str:
        """从人格档案中提取沟通风格提示。"""
        style = self.persona_profile.get("communication_style", {})
        if isinstance(style, dict):
            parts = []
            tone = style.get("tone", "")
            if tone:
                parts.append(f"语气{tone}")
            formality = style.get("formality", "")
            if formality:
                parts.append(f"正式程度{formality}")
            return "、".join(parts) if parts else "口语化、自然"
        if isinstance(style, str) and style:
            return style
        return "口语化、自然、像微信聊天"

    def _get_emotion_hint(self) -> str:
        """从情绪档案中提取情绪习惯提示。"""
        expr = self.emotion_profile.get("emotion_expression", {})
        if isinstance(expr, dict):
            parts = []
            for emo, info in list(expr.items())[:3]:
                if isinstance(info, dict):
                    style = info.get("expression_style", "")
                    if style:
                        parts.append(f"{emo}时：{style[:20]}")
                elif isinstance(info, list):
                    words = info[:3]
                    if words:
                        parts.append(f"{emo}常用：{', '.join(words)}")
            return "；".join(parts) if parts else ""
        return ""

    def _retrieve_real_examples(self, twin_reply: str, contact_wxid: str | None = None) -> list[str]:
        """从向量库中检索与分身回复语义相关的真实对话片段。"""
        if self.vector_store is None:
            return []

        if self.vector_store.count() < MIN_CONVERSATION_COUNT:
            return []

        try:
            hits = self.vector_store.search(
                query=twin_reply,
                embedder=self.embedder,
                top_k=RETRIEVAL_TOP_K,
                contact_filter=contact_wxid,
            )

            examples = []
            for hit in hits:
                text = hit.get("text", "")
                if len(text) > 15 and text.count("我:") >= 1:
                    examples.append(text.strip())
                if len(examples) >= FINAL_EXAMPLES_COUNT:
                    break

            if len(examples) < FINAL_EXAMPLES_COUNT:
                fallback = self.vector_store.sample_conversations(
                    contact_filter=contact_wxid,
                    n=FINAL_EXAMPLES_COUNT,
                )
                for item in fallback:
                    text = item.get("text", "")
                    if text not in examples and len(text) > 15:
                        examples.append(text.strip())
                    if len(examples) >= FINAL_EXAMPLES_COUNT:
                        break

            return examples[:FINAL_EXAMPLES_COUNT]

        except Exception as e:
            logger.warning("Failed to retrieve real examples: %s", e)
            return []

    def _parse_llm_response(self, raw: str) -> dict:
        """解析 LLM 返回的 JSON 响应。"""
        import re

        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return {
                "authenticity_score": 0.5,
                "deviation_notes": "无法分析，请稍后重试",
                "real_examples": [],
                "retrain_suggestion": "建议先进行更多对话训练",
            }

        try:
            result = json.loads(match.group())
            return {
                "authenticity_score": float(result.get("authenticity_score", 0.5)),
                "deviation_notes": str(result.get("deviation_notes", "无法分析")),
                "real_examples": list(result.get("real_examples", []))[:FINAL_EXAMPLES_COUNT],
                "retrain_suggestion": str(result.get("retrain_suggestion", "建议继续训练")),
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Failed to parse authenticity check response: %s", e)
            return {
                "authenticity_score": 0.5,
                "deviation_notes": "分析结果解析失败",
                "real_examples": [],
                "retrain_suggestion": "建议继续训练",
            }

    def check(self, twin_reply: str, contact_wxid: str | None = None) -> dict:
        """检查分身回复的真实性。

        Args:
            twin_reply: 分身的回复内容
            contact_wxid: 可选，联系人的微信ID用于过滤

        Returns:
            dict: 包含以下键：
                - authenticity_score (float): 0.0-1.0，越高越像
                - deviation_notes (str): 不像的地方（人类可读）
                - real_examples (list[str]): 真实对话片段（2-3条）
                - retrain_suggestion (str): 再训练建议
                - insufficient_data (bool): 数据不足标志
        """
        if not twin_reply or not twin_reply.strip():
            return {
                "authenticity_score": 0.0,
                "deviation_notes": "回复内容为空",
                "real_examples": [],
                "retrain_suggestion": "请先让分身回复后再检查",
                "insufficient_data": False,
            }

        conversation_count = 0
        if self.vector_store:
            try:
                conversation_count = self.vector_store.count()
            except Exception:
                pass

        if conversation_count < MIN_CONVERSATION_COUNT:
            return {
                "authenticity_score": 0.5,
                "deviation_notes": "数据不足，难以准确判断",
                "real_examples": [],
                "retrain_suggestion": f"当前仅有 {conversation_count} 条对话，建议积累至少 {MIN_CONVERSATION_COUNT} 条后再检查",
                "insufficient_data": True,
            }

        real_examples = self._retrieve_real_examples(twin_reply, contact_wxid)

        if not real_examples:
            return {
                "authenticity_score": 0.5,
                "deviation_notes": "未能找到相关真实对话",
                "real_examples": [],
                "retrain_suggestion": "建议先进行更多对话训练",
                "insufficient_data": False,
            }

        basic = self.persona_profile.get("basic_info", {})
        name = basic.get("name", basic.get("姓名", "TA"))

        examples_text = "\n---\n".join(
            f"[片段{i+1}]\n{ex}"
            for i, ex in enumerate(real_examples)
        )

        prompt = AUTHENTICITY_CHECK_PROMPT.format(
            agent_reply=twin_reply.strip(),
            real_examples=examples_text,
            name=name,
            style_hint=self._get_style_hint(),
            emotion_hint=self._get_emotion_hint() or "无特殊情绪习惯记录",
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一位专业的亲密关系语言分析师，输出必须严格符合JSON格式。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=800,
            )
            raw_response = (resp.choices[0].message.content or "").strip()
            result = self._parse_llm_response(raw_response)
            result["insufficient_data"] = False
            return result

        except Exception as e:
            logger.exception("Authenticity check failed")
            return {
                "authenticity_score": 0.5,
                "deviation_notes": f"检查失败：{str(e)[:20]}",
                "real_examples": real_examples,
                "retrain_suggestion": "建议稍后重试检查",
                "insufficient_data": False,
            }
