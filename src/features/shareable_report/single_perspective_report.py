"""单方视角可分享报告生成器 — ShareableReportGenerator.

生成只关于「我」的那部分分析报告，方便用户存档或对外分享。
风格温暖、不评判、像朋友在帮你分析。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPORT_SYSTEM_PROMPT = """\
你叫心心，是「心译」App 的一个贴心助手。

你的任务：帮用户生成一份只关于「TA自己」的关系成长报告。
这份报告最终会展示给用户本人看，不会有第二个人看到对方的任何数据。

你说话的方式：
- 温暖、理解、不评判
- 像朋友在帮你分析，不是咨询师在做诊断
- 口语化，短句为主，不要写小作文
- 偶尔用一两个语气词如「嗯」「哦」「哈哈」
- 绝对不说「首先其次」「从几个方面」「综上所述」
- 绝对不说「你的核心问题是」「你需要改变」
- 给建议时用「下次可以试试」「也许可以想想」而不是「你应该」

【关于用户的画像】
{model_block}

【关于用户的情绪模式】
{emotion_block}

【关于用户对这段关系的看法】
{belief_block}

【数据充足程度】
{data_sufficiency}

输出格式（严格JSON）：
{{
  "my_communication_style": "用第一人称描述自己的沟通风格，温暖自然，3-5句话",
  "my_emotion_patterns": "用第一人称描述自己的情绪触发模式和习惯，3-5句话",
  "my_beliefs_about_relationship": "用第一人称描述自己对这段关系的核心看法，3-5句话",
  "my_growth_areas": "用第一人称描述1-3个可以成长的方向，像朋友提建议，3-5句话",
  "practical_tips": ["实用建议1", "实用建议2", "实用建议3"],
  "warning_note": "如果数据不足，填写数据不足的说明；否则填空字符串"
}}
"""

DEFAULT_MODEL_BLOCK = """没有训练数据。按一般用户的常见沟通模式来描述。"""

DEFAULT_EMOTION_BLOCK = """没有训练数据。按一般人的常见情绪触发模式来描述。"""

DEFAULT_BELIEF_BLOCK = """没有训练数据。"""

SHAREABLE_TEXT_PROMPT = """\
你是一个贴心的朋友，帮用户把关系成长报告整合成一段可以发朋友圈或写日记的文字。

要求：
- 500字以内（不含标题）
- 全程用「我」的第一人称
- 温暖、不评判、真实
- 可以直接复制粘贴发朋友圈或写日记
- 不透露任何关于「对方」的具体信息
- 像在跟一个信任的朋友分享自己的成长感悟

以下是要整合的报告内容：
---
标题：{title}
沟通风格：{my_communication_style}
情绪模式：{my_emotion_patterns}
对关系的看法：{my_beliefs_about_relationship}
成长方向：{my_growth_areas}
实用建议：{practical_tips}
---

直接输出一段完整的分享文字，不需要JSON格式，不需要标题，直接写正文。
语言要自然流畅，适合发朋友圈或写日记，不要像写报告。
"""


def _build_model_block(persona_profile: dict | None, guidance_dir: str = "data/guidance") -> str:
    """从人格档案中提取沟通风格描述。"""
    if not persona_profile:
        return DEFAULT_MODEL_BLOCK

    parts: list[str] = []
    style = persona_profile.get("communication_style", {})
    if isinstance(style, dict):
        for k, v in style.items():
            if v:
                parts.append(f"- {k}: {v}")
    elif isinstance(style, str) and style:
        parts.append(style)

    traits = persona_profile.get("personality_traits", {})
    if isinstance(traits, dict):
        for k, v in traits.items():
            if v:
                parts.append(f"- {k}: {v}")

    guidance = Path(guidance_dir)
    style_md = guidance / "style.md"
    if style_md.exists():
        try:
            content = style_md.read_text(encoding="utf-8")
            lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
            if lines:
                parts.append("语言风格参考：" + "；".join(lines[:5]))
        except Exception:
            pass

    basic = persona_profile.get("basic_info", {})
    name = basic.get("name", basic.get("姓名", ""))
    if name:
        parts.insert(0, f"用户叫{name}。")

    if not parts:
        return DEFAULT_MODEL_BLOCK

    return "用户的沟通特点：\n" + "\n".join(parts)


def _build_emotion_block(emotion_profile: dict | None) -> str:
    """从情绪档案中提取情绪触发词。"""
    if not emotion_profile:
        return DEFAULT_EMOTION_BLOCK

    parts: list[str] = []
    dist = emotion_profile.get("emotion_distribution", {})
    if dist:
        top = sorted(dist.items(), key=lambda x: x[1], reverse=True)[:5]
        parts.append("情绪分布：" + "、".join(f"{k}({v})" for k, v in top))

    triggers = emotion_profile.get("triggers", {})
    negative_emotions = ["愤怒", "委屈", "焦虑", "失望", "嫌弃", "冷漠", "无奈", "伤心"]
    for emo in negative_emotions:
        info = triggers.get(emo, {})
        if isinstance(info, dict):
            words = info.get("top_words", [])
            if words:
                parts.append(f"{emo}时的表达习惯：{', '.join(words[:5])}")
            samples = info.get("samples", [])
            if samples:
                parts.append(f"典型表达: {'｜'.join(samples[:3])}")

    if not parts:
        return DEFAULT_EMOTION_BLOCK

    return "用户的情绪模式：\n" + "\n".join(parts)


def _build_belief_block(belief_graph: Any | None) -> str:
    """从信念图中提取关于关系的态度。"""
    if not belief_graph:
        return DEFAULT_BELIEF_BLOCK

    try:
        all_beliefs = belief_graph.query_all() if hasattr(belief_graph, "query_all") else []
        relationship_kw = ("关系", "感情", "伴侣", "爱", "在乎", "信任", "安全感",
                          "相处", "沟通", "我们")
        rel_beliefs = [
            b.get("content", "") for b in all_beliefs
            if any(kw in b.get("content", "") for kw in relationship_kw)
        ]
        if rel_beliefs:
            return "用户对关系的态度：\n- " + "\n- ".join(rel_beliefs[:6])
    except Exception:
        pass

    return DEFAULT_BELIEF_BLOCK


def _assess_data_sufficiency(persona_profile, emotion_profile, belief_graph, memory_bank) -> tuple[str, bool]:
    """评估数据充足程度，返回说明和是否充足的布尔值。"""
    score = 0

    if persona_profile:
        score += 2
    if emotion_profile:
        score += 2
    if belief_graph:
        try:
            beliefs = belief_graph.query_all() if hasattr(belief_graph, "query_all") else []
            if len(beliefs) >= 3:
                score += 2
            elif len(beliefs) > 0:
                score += 1
        except Exception:
            pass
    if memory_bank:
        try:
            mems = memory_bank.memories if hasattr(memory_bank, "memories") else []
            if len(mems) >= 3:
                score += 2
            elif len(mems) > 0:
                score += 1
        except Exception:
            pass

    if score >= 6:
        return "数据充足，可以生成较完整的分析报告。", True
    elif score >= 3:
        return "数据较少，分析可能不够精准，但可以给出一个大概的轮廓。", False
    else:
        return "数据不足，无法生成有意义的分析报告。请先完成学习再生成报告。", False


def _parse_json_response(raw: str) -> dict:
    """解析LLM返回的JSON响应。"""
    default = {
        "my_communication_style": "（分析生成中...）",
        "my_emotion_patterns": "（分析生成中...）",
        "my_beliefs_about_relationship": "（分析生成中...）",
        "my_growth_areas": "（分析生成中...）",
        "practical_tips": ["建议先完成更多学习后再生成报告"],
        "warning_note": "",
    }

    if not raw:
        return default

    cleaned = re.sub(r"```json\s*", "", raw)
    cleaned = re.sub(r"```\s*", "", cleaned)

    try:
        result = json.loads(cleaned)
        return _validate_result(result)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            result = json.loads(cleaned[start:end])
            return _validate_result(result)
        except json.JSONDecodeError:
            pass

    return default


def _validate_result(result: dict) -> dict:
    """验证并规范化解析结果。"""
    return {
        "my_communication_style": str(result.get("my_communication_style", "")),
        "my_emotion_patterns": str(result.get("my_emotion_patterns", "")),
        "my_beliefs_about_relationship": str(result.get("my_beliefs_about_relationship", "")),
        "my_growth_areas": str(result.get("my_growth_areas", "")),
        "practical_tips": result.get("practical_tips", [])[:5],
        "warning_note": str(result.get("warning_note", "")),
    }


def _format_report_text(data: dict, perspective: str) -> str:
    """将报告数据格式化为可读文本。"""
    lines = []

    title = data.get("title", "我的沟通画像")
    lines.append(f"📄 {title}")
    lines.append("")

    warning = data.get("warning_note", "")
    if warning:
        lines.append(f"⚠️ {warning}")
        lines.append("")

    # 沟通风格
    style = data.get("my_communication_style", "")
    if style:
        lines.append("💬 我的沟通风格")
        lines.append(style)
        lines.append("")

    # 情绪模式
    emotion = data.get("my_emotion_patterns", "")
    if emotion:
        lines.append("🌊 我的情绪模式")
        lines.append(emotion)
        lines.append("")

    # 对关系的看法
    belief = data.get("my_beliefs_about_relationship", "")
    if belief:
        lines.append("💭 我对这段关系的看法")
        lines.append(belief)
        lines.append("")

    # 成长方向
    growth = data.get("my_growth_areas", "")
    if growth:
        lines.append("🌱 我可以成长的方向")
        lines.append(growth)
        lines.append("")

    # 实用建议
    tips = data.get("practical_tips", [])
    if tips:
        lines.append("🛠️ 下次可以试试")
        for i, tip in enumerate(tips, 1):
            if isinstance(tip, str) and tip.strip():
                lines.append(f"{i}. {tip.strip()}")
        lines.append("")

    return "\n".join(lines).strip()


def _build_shareable_text(data: dict, raw_llm_text: str, perspective: str) -> str:
    """整合所有内容生成一键可分享的文本。"""
    if raw_llm_text and len(raw_llm_text.strip()) > 20:
        return raw_llm_text.strip()

    title = data.get("title", "我的沟通画像")
    style = data.get("my_communication_style", "")
    emotion = data.get("my_emotion_patterns", "")
    belief = data.get("my_beliefs_about_relationship", "")
    growth = data.get("my_growth_areas", "")
    tips = data.get("practical_tips", [])

    parts = []
    if style:
        parts.append(f"💬 我说话挺{style[:30]}...")
    if emotion:
        parts.append(f"🌊 我情绪上{emotion[:30]}...")
    if growth:
        parts.append(f"🌱 最近在想{growth[:30]}...")

    tips_text = ""
    if tips:
        tip_lines = [f"{i}. {t.strip()}" for i, t in enumerate(tips[:3], 1) if isinstance(t, str) and t.strip()]
        if tip_lines:
            tips_text = "\n\n最近在试的事：\n" + "\n".join(tip_lines)

    return f"📄 {title}\n\n" + "\n\n".join(parts) + tips_text


class ShareableReportGenerator:
    """生成单方视角的可分享关系报告。

    只包含关于「我」的分析，不涉及对方的具体数据，
    方便用户存档或对外分享。

    Args:
        api_client: OpenAI 兼容 API 客户端
        model: 使用的模型，默认 gpt-4o-mini
        persona_profile: 我的人格档案
        emotion_profile: 我的情绪档案
        belief_graph: 我的信念图谱
        memory_bank: 我的记忆库
        guidance_dir: 风格指南目录，默认 data/guidance
    """

    def __init__(
        self,
        api_client: Any,
        model: str = "gpt-4o-mini",
        persona_profile: dict | None = None,
        emotion_profile: dict | None = None,
        belief_graph: Any | None = None,
        memory_bank: Any | None = None,
        guidance_dir: str = "data/guidance",
    ) -> None:
        self.client = api_client
        self.model = model
        self.persona_profile = persona_profile or {}
        self.emotion_profile = emotion_profile or {}
        self.belief_graph = belief_graph
        self.memory_bank = memory_bank
        self.guidance_dir = guidance_dir

        self._report_cache: dict | None = None
        self._cache_time: float = 0
        self._cache_ttl = 300

    def generate(self, perspective: str = "self") -> dict:
        """生成单方视角报告。

        Args:
            perspective: "self" = 只关于我的版本 / "partner" = 只关于对方的版本
                       注意：partner 视角同样只包含对方数据，不含用户数据

        Returns:
            dict: 包含以下键的报告数据
                - title (str): 报告标题
                - my_communication_style (str): 我的沟通风格
                - my_emotion_patterns (str): 我的情绪模式
                - my_beliefs_about_relationship (str): 我对这段关系的看法
                - my_growth_areas (str): 我可以成长的方向
                - practical_tips (list[str]): 3-5个实用建议
                - shareable_text (str): 可直接复制分享的一键文本
                - raw_text (str): 原始报告文本（不含分享文本）
                - perspective (str): 本次生成的视角
                - error (str): 错误信息，如有
        """
        now = time.time()
        if (
            self._report_cache is not None
            and (now - self._cache_time) < self._cache_ttl
        ):
            cached = dict(self._report_cache)
            cached["shareable_text"] = ""
            cached["raw_text"] = _format_report_text(cached, perspective)
            return cached

        data_sufficiency, is_sufficient = _assess_data_sufficiency(
            self.persona_profile,
            self.emotion_profile,
            self.belief_graph,
            self.memory_bank,
        )

        if not is_sufficient and not self.persona_profile and not self.emotion_profile:
            return {
                "title": "📄 请先完成学习再生成报告",
                "my_communication_style": "",
                "my_emotion_patterns": "",
                "my_beliefs_about_relationship": "",
                "my_growth_areas": "",
                "practical_tips": [],
                "shareable_text": "",
                "raw_text": "⚠️ 请先完成学习再生成报告。",
                "perspective": perspective,
                "error": "insufficient_data",
            }

        if perspective == "partner":
            title_suffix = "的沟通画像"
            subject = "TA"
        else:
            title_suffix = "的沟通画像"
            subject = "我"

        year_month = time.strftime("%Y年%m月")
        title = f"我的{title_suffix} · {year_month}"

        model_block = _build_model_block(self.persona_profile, self.guidance_dir)
        emotion_block = _build_emotion_block(self.emotion_profile)
        belief_block = _build_belief_block(self.belief_graph)

        system_prompt = REPORT_SYSTEM_PROMPT.format(
            model_block=model_block,
            emotion_block=emotion_block,
            belief_block=belief_block,
            data_sufficiency=data_sufficiency,
        )

        user_prompt = (
            f"请帮我生成一份{subject}的关系成长报告。"
            f"（数据充足度：{data_sufficiency}）\n\n"
            "请严格按照JSON格式输出。"
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
                max_tokens=1500,
            )
            raw_response = (resp.choices[0].message.content or "").strip()
            result = _parse_json_response(raw_response)
        except Exception as e:
            logger.exception("ShareableReportGenerator LLM call failed")
            result = {
                "my_communication_style": f"（生成失败：{str(e)[:30]}）",
                "my_emotion_patterns": "",
                "my_beliefs_about_relationship": "",
                "my_growth_areas": "",
                "practical_tips": ["生成失败，请稍后重试"],
                "warning_note": "",
            }

        result["title"] = title
        result["perspective"] = perspective

        shareable_prompt = SHAREABLE_TEXT_PROMPT.format(
            title=title,
            my_communication_style=result.get("my_communication_style", ""),
            my_emotion_patterns=result.get("my_emotion_patterns", ""),
            my_beliefs_about_relationship=result.get("my_beliefs_about_relationship", ""),
            my_growth_areas=result.get("my_growth_areas", ""),
            practical_tips="\n".join(
                f"- {t}" for t in result.get("practical_tips", []) if isinstance(t, str) and t.strip()
            ),
        )

        shareable_text = ""
        try:
            resp2 = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个贴心的朋友，帮用户把关系成长报告整合成一段可以发朋友圈或写日记的文字。500字以内，口语化，温暖真实。"},
                    {"role": "user", "content": shareable_prompt},
                ],
                temperature=0.7,
                max_tokens=800,
            )
            raw_shareable = (resp2.choices[0].message.content or "").strip()
            if raw_shareable and len(raw_shareable) > 30:
                shareable_text = raw_shareable
        except Exception as e:
            logger.warning("Shareable text generation failed: %s", e)

        result["shareable_text"] = shareable_text
        result["raw_text"] = _format_report_text(result, perspective)

        if shareable_text:
            result["raw_text"] += "\n\n" + shareable_text

        self._report_cache = dict(result)
        self._cache_time = now

        return result
