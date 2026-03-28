"""发前对齐引擎 — PreSendAligner。

参考 MEDIATOR_SYSTEM_PROMPT 风格：短句、口语化、像朋友发微信。
复用 PartnerAdvisor 的人格数据和情绪画像，模拟对方视角。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

ALIGN_SYSTEM_PROMPT = """\
你叫心心，是一款叫「心译」的 App 里的一个小助手。

你的任务很简单：帮用户在想发消息之前，先看看对方可能会怎么理解。

你不评判用户想说什么对不对、好不好。
你只是帮你看到：这句话传到对方那里，可能会触发什么。

你说话的方式：
- 像朋友发微信，不写文章
- 短句，一两句话一段
- 口语化，不说教
- 不用表情包，偶尔用一两个字如「嗯」「哦」「哈哈」
- 绝对不说「首先其次」「从几个方面」「综上所述」
- 绝对不说「你的感受」「我理解你」「我建议」
- 给出改写时，保持原意，只调整语气和措辞

【关于对方的画像】
{model_block}

【关于对方容易触发的情绪】
{emotion_block}

输出格式（严格 JSON）：
{{
  "how_they_hear": "描述对方可能听到的版本（第一人称，模拟对方的心声）",
  "their_emotion": "预测对方最可能被触发的1-2个情绪关键词，如：委屈/生气/无奈/心凉",
  "one_tip": "一句话建议，实用、具体、不说教",
  "rewrites": ["改写1：语气更软的版本", "改写2：更中性/理性的版本"]
}}
"""

DEFAULT_MODEL_BLOCK = """\
你不太了解这个人。只能根据一般情侣的沟通习惯来推测。
假设对方是一个有正常情感需求的普通人。"""

DEFAULT_EMOTION_BLOCK = """\
没有训练数据。按一般情侣的常见情绪触发模式来推测。
- 负面触发词：「你总是」「你从来不」「凭什么」「算了」「随便」
- 容易引起防御的表达：指责、直接否定、翻旧账
- 让人感到被理解的表达：先说感受、少用「你」开头"""


def _build_model_block(partner) -> str:
    """从 PartnerAdvisor 实例提取沟通风格描述。"""
    if not partner.persona_profile:
        return DEFAULT_MODEL_BLOCK

    style_parts: list[str] = []
    style = partner.persona_profile.get("communication_style", {})
    if style:
        for k, v in style.items():
            if v:
                style_parts.append(f"- {k}: {v}")

    traits = partner.persona_profile.get("personality_traits", {})
    if traits:
        for k, v in traits.items():
            if v:
                style_parts.append(f"- {k}: {v}")

    basic = partner.persona_profile.get("basic_info", {})
    name = basic.get("name", basic.get("姓名", "TA"))
    if name and name != "TA":
        style_parts.insert(0, f"对方叫{name}。")

    if not style_parts:
        return DEFAULT_MODEL_BLOCK

    return "对方的特点：\n" + "\n".join(style_parts)


def _build_emotion_block(partner) -> str:
    """从 PartnerAdvisor 实例提取情绪触发词。"""
    if not partner.emotion_profile:
        return DEFAULT_EMOTION_BLOCK

    parts: list[str] = []
    triggers = partner.emotion_profile.get("triggers", {})

    negative_emotions = ["愤怒", "委屈", "焦虑", "失望", "嫌弃", "冷漠", "无奈"]
    for emo in negative_emotions:
        info = triggers.get(emo, {})
        if isinstance(info, dict):
            words = info.get("top_words", [])
            if words:
                parts.append(f"触发{emo}的词: {', '.join(words[:5])}")
            samples = info.get("samples", [])
            if samples:
                parts.append(f"典型表达: {'｜'.join(samples[:3])}")

    if not parts:
        return DEFAULT_EMOTION_BLOCK

    return "对方在负面情绪下的表达习惯：\n" + "\n".join(parts)


class PreSendAligner:
    """发前对齐引擎。

    复用 PartnerAdvisor 的人格数据，从对方视角分析用户想发送的消息。
    """

    def __init__(
        self,
        api_client: Any,
        partner_advisor_instance: Any,
        model: str = "gpt-4o-mini",
    ) -> None:
        self.client = api_client
        self.partner = partner_advisor_instance
        self.model = model
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        model_block = _build_model_block(self.partner)
        emotion_block = _build_emotion_block(self.partner)
        return ALIGN_SYSTEM_PROMPT.format(
            model_block=model_block,
            emotion_block=emotion_block,
        )

    def align(self, draft: str) -> dict:
        """分析草稿，返回对齐结果。

        Args:
            draft: 用户想发送的消息草稿

        Returns:
            dict: {
                "how_they_hear": str,      # TA 听到的版本（第一人称）
                "their_emotion": str,        # TA 可能触发的情绪
                "one_tip": str,              # 一句话建议
                "rewrites": list[str],      # 2 个备选改写
            }

        Raises:
            ValueError: 草稿为空时
            RuntimeError: API 调用失败时
        """
        if not draft or not draft.strip():
            raise ValueError("草稿不能为空")

        # 检查是否有训练数据
        has_training = bool(
            self.partner.persona_profile
            or self.partner.emotion_profile
            or self.partner.thinking_model
        )

        user_content = (
            f"我想发这条消息：\n「{draft.strip()}」\n\n"
            f"帮我分析一下：对方可能会怎么理解？我需要注意什么？"
        )

        if not has_training:
            user_content += (
                "\n\n（提示：还没有对方的训练数据，按一般情侣的常见模式来分析）"
            )

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=800,
            )
            raw = (resp.choices[0].message.content or "").strip()
        except TimeoutError:
            raise RuntimeError("请求超时，请稍后重试")
        except Exception as e:
            logger.exception("PreSendAligner LLM call failed")
            raise RuntimeError(f"分析失败：{e}")

        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> dict:
        """解析 LLM 返回的 JSON 响应。"""
        default = {
            "how_they_hear": "（解析失败，请稍后重试）",
            "their_emotion": "未知",
            "one_tip": "直接发也没关系，重要的是真诚",
            "rewrites": ["（改写解析失败）"],
        }

        if not raw:
            return default

        # 尝试从 markdown 代码块中提取 JSON
        import re

        # 移除常见的 markdown 代码块标记
        cleaned = re.sub(r"```json\s*", "", raw)
        cleaned = re.sub(r"```\s*", "", cleaned)

        # 尝试找到 JSON 对象
        try:
            # 尝试直接解析
            result = json.loads(cleaned)
            return self._validate_result(result)
        except json.JSONDecodeError:
            pass

        # 尝试找第一个 { 到最后一个 }
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(cleaned[start:end])
                return self._validate_result(result)
            except json.JSONDecodeError:
                pass

        # 回退：尝试从纯文本中提取字段
        return self._parse_fallback(raw)

    def _validate_result(self, result: dict) -> dict:
        """验证并规范化解析结果。"""
        return {
            "how_they_hear": str(result.get("how_they_hear", "")),
            "their_emotion": str(result.get("their_emotion", "未知")),
            "one_tip": str(result.get("one_tip", "")),
            "rewrites": result.get("rewrites", []),
        }

    def _parse_fallback(self, raw: str) -> dict:
        """无法解析 JSON 时的回退处理。"""
        import re

        result = {
            "how_they_hear": "",
            "their_emotion": "",
            "one_tip": "",
            "rewrites": [],
        }

        # 尝试用正则匹配各字段
        patterns = {
            "how_they_hear": r"对方听到[：:]\s*(.+?)(?=\n|$)",
            "their_emotion": r"情绪[：:]\s*(.+?)(?=\n|$)",
            "one_tip": r"建议[：:]\s*(.+?)(?=\n|$)",
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, raw, re.DOTALL)
            if match:
                result[key] = match.group(1).strip()

        # 尝试找改写
        rewrite_matches = re.findall(r"改写\d*[：:]\s*「?(.+?)」?(?=\n|改写|$)", raw, re.DOTALL)
        if len(rewrite_matches) >= 2:
            result["rewrites"] = [r.strip() for r in rewrite_matches[:2]]
        elif rewrite_matches:
            result["rewrites"] = [rewrite_matches[0].strip()]

        # 如果所有字段都为空，返回原始内容作为摘要
        if not any(result.values()):
            result["how_they_hear"] = raw[:200]
            result["one_tip"] = "请参考上方分析结果"

        return result
