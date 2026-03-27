from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAI
from anthropic import Anthropic

from src.memory.retriever import MemoryRetriever
from src.memory.vector_store import VectorStore
from src.memory.memory_bank import MemoryBank
from src.belief.graph import BeliefGraph
from src.personality.prompt_builder import PromptBuilder
from src.personality.emotion_tracker import EmotionTracker

logger = logging.getLogger(__name__)

INNER_THINK_PROMPT = (
    "你是一个认知模拟器。模拟「我」收到消息后的第一反应——直觉、情绪、内心OS。\n"
    "不是回复对方，是模拟我脑子里闪过的念头。\n"
    "\n"
    "## 我的人格\n{personality}\n"
    "\n"
    "## 认知参数\n{cognitive_profile}\n"
    "\n"
    "## 我面对「{relationship_type}」时的情绪反应模式\n{emotion_boundaries}\n"
    "\n"
    "关系：{relationship}\n"
    "我上一轮情绪：{prev_emotion}\n"
    "\n"
    "最近对话：\n{history}\n"
    "\n"
    "对方发的：「{message}」\n"
    "\n"
    "只输出JSON：\n"
    '{{'
    '\n  "their_emotion": "对方的情绪(joy/excitement/touched/gratitude/pride/sadness/anger/anxiety/disappointment/wronged/coquettish/jealousy/heartache/longing/curiosity/neutral)",'
    '\n  "my_feeling": "我的情绪(joy/excitement/touched/gratitude/pride/sadness/anger/anxiety/disappointment/wronged/coquettish/jealousy/heartache/longing/curiosity/neutral)",'
    '\n  "feeling_intensity": 0.0到1.0,'
    '\n  "my_thought": "我脑子里冒出的第一个念头（口语化，10-20字）"'
    '\n}}\n'
    "\n"
    "要求：\n"
    "- 严格参考上面针对当前关系类型的「情绪反应模式」来判断情绪\n"
    "- my_thought 是第一反应，不是分析。像「卧槽」「笑死」「烦死了」「啥意思」这种\n"
)

VALID_EMOTIONS = {
    "joy", "excitement", "touched", "gratitude", "pride",
    "sadness", "anger", "anxiety", "disappointment", "wronged",
    "coquettish", "jealousy", "heartache", "longing",
    "curiosity", "neutral",
}

_REL_TYPE_LABELS = {
    "partner": "伴侣",
    "family": "家人",
    "friend": "朋友",
    "colleague": "同事",
    "stranger": "陌生人",
    "self": "本人",
    "default": "通用",
}


class ChatEngine:
    """主对话引擎，编排记忆检索、信念查询、情绪追踪与 LLM 调用。"""

    def __init__(self, config: dict) -> None:
        self.provider: str = config.get("provider", "openai")
        self.model: str = config.get("model", "gpt-4o-mini")
        self.top_k_vectors: int = config.get("top_k_vectors", 5)
        self.top_k_beliefs: int = config.get("top_k_beliefs", 3)

        if self.provider in ("openai", "gemini"):
            kwargs = {"api_key": config["api_key"]}
            if config.get("base_url"):
                kwargs["base_url"] = config["base_url"]
            if config.get("headers"):
                kwargs["default_headers"] = config["headers"]
            self.client: Any = OpenAI(**kwargs)
        elif self.provider == "anthropic":
            self.client = Anthropic(api_key=config["api_key"])
        else:
            raise ValueError(f"不支持的 provider: {self.provider}")

        self.memory_retriever: MemoryRetriever | None = None
        self.belief_graph: BeliefGraph | None = None
        self.prompt_builder: PromptBuilder | None = None
        self.vector_store: VectorStore | None = None
        self.emotion_tracker: EmotionTracker | None = None
        self.memory_bank: MemoryBank | None = None

    def set_components(
        self,
        memory_retriever: MemoryRetriever,
        belief_graph: BeliefGraph,
        prompt_builder: PromptBuilder,
        vector_store: VectorStore | None = None,
        emotion_tracker: EmotionTracker | None = None,
        memory_bank: MemoryBank | None = None,
    ) -> None:
        self.memory_retriever = memory_retriever
        self.belief_graph = belief_graph
        self.prompt_builder = prompt_builder
        self.vector_store = vector_store
        self.emotion_tracker = emotion_tracker
        self.memory_bank = memory_bank

    def chat(
        self,
        user_message: str,
        chat_history: list[dict] | None = None,
        contact_wxid: str | None = None,
        contact_context: dict | None = None,
    ) -> str:
        if not all([self.memory_retriever, self.belief_graph, self.prompt_builder]):
            return "系统尚未初始化完成，请先导入数据。"

        # --- Stage 1: inner thinking + retrieval in parallel ---
        inner_thought: dict | None = None
        memories = ""
        beliefs_text = ""
        episodic_text = ""
        few_shot: list[str] = []

        def _do_think():
            return self._inner_think(user_message, chat_history, contact_context)

        def _do_retrieve():
            q = user_message
            mem = self.memory_retriever.retrieve(q, top_k=self.top_k_vectors, contact_wxid=contact_wxid)
            bel_raw = self.belief_graph.query_by_topic(user_message, top_k=self.top_k_beliefs)
            bel_lines: list[str] = []
            for b in bel_raw:
                line = f"- 关于「{b.get('topic', '')}」: {b.get('stance', '')}"
                if b.get("condition"):
                    line += f"（前提：{b['condition']}）"
                bel_lines.append(line)
            ep = ""
            if self.memory_bank:
                hits = self.memory_bank.query(user_message, top_k=5)
                ep = self.memory_bank.format_for_prompt(hits)
            fs = self._get_few_shot_examples(contact_wxid)
            return mem, "\n".join(bel_lines), ep, fs

        with ThreadPoolExecutor(max_workers=2) as pool:
            think_future = pool.submit(_do_think)
            retrieve_future = pool.submit(_do_retrieve)

            try:
                inner_thought = think_future.result(timeout=30)
            except Exception as e:
                logger.warning("Inner think timeout/error: %s", e)
                return "⚠ 思考模块API超时，请重试"
            try:
                memories, beliefs_text, episodic_text, few_shot = retrieve_future.result(timeout=20)
            except Exception as e:
                logger.warning("Retrieval timeout/error: %s", e)

        if inner_thought is None:
            return "⚠ 思考模块API返回异常，请重试"

        # --- Stage 1.5: update emotion from inner thought (reactive) ---
        emotion_prompt = ""
        emotion_transition = ""
        if self.emotion_tracker:
            if inner_thought.get("my_feeling"):
                self.emotion_tracker.set_reactive_emotion(
                    inner_thought["my_feeling"],
                    confidence=inner_thought.get("feeling_intensity", 0.7),
                    their_emotion=inner_thought.get("their_emotion"),
                    contagion=inner_thought.get("contagion", "slight"),
                )
            else:
                self.emotion_tracker.update_from_history(chat_history)
            emotion_prompt = self.emotion_tracker.get_emotion_prompt()
            emotion_transition = self.emotion_tracker.get_emotion_transition_hint()

        # --- Stage 2: build prompt with inner thought and generate reply ---
        system_prompt = self.prompt_builder.build_system_prompt(
            retrieved_memories=memories,
            retrieved_beliefs=beliefs_text,
            episodic_memories=episodic_text,
            contact_context=contact_context,
            few_shot_examples=few_shot,
            emotion_prompt=emotion_prompt,
            emotion_transition=emotion_transition,
            inner_thought=inner_thought,
        )

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": user_message})

        return self._call_llm(messages)

    def quick_reply(self, message: str) -> str:
        """Stateless single-turn reply for evaluation — no chat history."""
        return self.chat(message, chat_history=[], contact_wxid=None, contact_context=None)

    def _get_few_shot_examples(self, contact_wxid: str | None = None) -> list[str]:
        if not self.vector_store:
            return []
        try:
            samples = self.vector_store.sample_conversations(
                contact_filter=contact_wxid, n=8,
            )
            if len(samples) < 3 and contact_wxid:
                samples = self.vector_store.sample_conversations(n=8)
            return [s["text"] for s in samples if s.get("text")]
        except Exception as e:
            logger.warning("Failed to get few-shot examples: %s", e)
            return []

    def _resolve_emotion_boundaries(self, rel_type: str) -> str:
        """Load emotion boundaries for the given relationship type, fallback to default."""
        if not self.prompt_builder:
            return "（暂无数据，使用直觉判断）"
        eb = self.prompt_builder.emotion_boundaries
        if not eb:
            return "（暂无数据，使用直觉判断）"

        # New format: dict keyed by relationship type
        if isinstance(eb, dict):
            boundaries = eb.get(rel_type) or eb.get("default") or []
            if not boundaries:
                first_key = next(iter(eb), None)
                boundaries = eb.get(first_key, []) if first_key else []
                if boundaries:
                    return self._format_boundaries(boundaries) + "\n（注意：此数据来自其他关系类型，仅供参考）"
            if boundaries:
                return self._format_boundaries(boundaries)
            return "（该关系类型暂无数据，使用直觉判断）"

        # Legacy format: flat list
        return self._format_boundaries(eb)

    @staticmethod
    def _format_boundaries(boundaries: list[dict]) -> str:
        lines = []
        for b in boundaries:
            stimulus = b.get("stimulus", "")
            emotion = b.get("emotion", "")
            intensity = b.get("intensity", "")
            evidence = b.get("evidence", "")
            if stimulus and emotion:
                line = f"- {stimulus} → {emotion}({intensity})"
                if evidence:
                    line += f"  证据: {evidence}"
                lines.append(line)
        return "\n".join(lines) if lines else "（暂无数据，使用直觉判断）"

    def _inner_think(
        self,
        user_message: str,
        chat_history: list[dict] | None,
        contact_context: dict | None,
    ) -> dict | None:
        """Stage 1: cognitive appraisal + inner monologue before replying."""
        recent = (chat_history or [])[-6:]
        history_lines: list[str] = []
        for m in recent:
            speaker = "对方" if m.get("role") == "user" else "我"
            history_lines.append(f"{speaker}: {m.get('content', '')}")
        history_text = "\n".join(history_lines) if history_lines else "（刚开始聊天）"

        personality = ""
        if self.prompt_builder and self.prompt_builder.thinking_model:
            lines = self.prompt_builder.thinking_model.strip().split("\n")
            personality = "\n".join(lines[:20])

        rel_desc = "未知关系"
        rel_type = "default"
        if contact_context:
            rel_label = contact_context.get("relationship_label", "")
            rel_name = contact_context.get("display_name", "")
            bg = contact_context.get("background", "")
            rel_type = contact_context.get("relationship", "default")
            parts = [p for p in [rel_label, rel_name, bg] if p]
            if parts:
                rel_desc = "，".join(parts)

        prev_emotion = "neutral"
        if self.emotion_tracker:
            from src.personality.emotion_tracker import EMOTION_LABELS
            prev_emotion = EMOTION_LABELS.get(
                self.emotion_tracker.current_emotion,
                self.emotion_tracker.current_emotion,
            )

        cog_profile = "（暂无认知参数，使用默认）"
        if self.prompt_builder and hasattr(self.prompt_builder, "cognitive_profile"):
            cp = self.prompt_builder.cognitive_profile
            if cp:
                cp_map = {
                    "emotional_reactivity": "情绪反应性",
                    "thinking_style": "思考风格",
                    "conflict_strategy": "冲突策略",
                    "contagion_susceptibility": "情绪易感性",
                    "response_tempo": "反应节奏",
                    "system2_threshold": "深度思考阈值",
                }
                cp_lines = [f"{label}：{cp[k]}" for k, label in cp_map.items() if cp.get(k)]
                if cp_lines:
                    cog_profile = "\n".join(cp_lines)

        emo_boundaries_text = self._resolve_emotion_boundaries(rel_type)

        rel_type_label = _REL_TYPE_LABELS.get(rel_type, rel_type)
        prompt_text = INNER_THINK_PROMPT.format(
            personality=personality,
            cognitive_profile=cog_profile,
            emotion_boundaries=emo_boundaries_text,
            relationship_type=rel_type_label,
            relationship=rel_desc,
            prev_emotion=prev_emotion,
            history=history_text,
            message=user_message,
        )

        max_retries = 10
        for attempt in range(max_retries):
            try:
                if self.provider in ("openai", "gemini"):
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt_text}],
                        temperature=0.6,
                        max_tokens=150,
                    )
                    raw = resp.choices[0].message.content or ""
                elif self.provider == "anthropic":
                    resp = self.client.messages.create(
                        model=self.model,
                        max_tokens=150,
                        messages=[{"role": "user", "content": prompt_text}],
                    )
                    raw = resp.content[0].text
                else:
                    return None

                raw = raw.strip()
                if not raw:
                    logger.warning("Inner think: empty response (attempt %d/%d)", attempt + 1, max_retries)
                    continue

                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

                result = json.loads(raw)

                if result.get("my_feeling") not in VALID_EMOTIONS:
                    result["my_feeling"] = "neutral"
                if result.get("their_emotion") not in VALID_EMOTIONS:
                    result["their_emotion"] = "neutral"

                intensity = result.get("feeling_intensity")
                if intensity is not None:
                    result["feeling_intensity"] = max(0.0, min(1.0, float(intensity)))
                else:
                    result["feeling_intensity"] = 0.5

                logger.info(
                    "Inner think: feeling=%s(%.1f) thought=%s",
                    result.get("my_feeling"),
                    result.get("feeling_intensity", 0),
                    result.get("my_thought", "")[:40],
                )
                return result

            except json.JSONDecodeError:
                logger.warning("Inner think: JSON parse failed (attempt %d/%d)", attempt + 1, max_retries)
                continue
            except Exception:
                logger.warning("Inner think: error (attempt %d/%d)", attempt + 1, max_retries, exc_info=True)
                continue
        logger.error("Inner think: all %d attempts failed", max_retries)
        return None

    @staticmethod
    def _clean_reply(text: str) -> str:
        """Post-process to ensure reply looks like a real WeChat message."""
        import re
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
        lines = [re.sub(r'^\d+[\.\)]\s*', '', l) for l in lines]
        return ' '.join(lines) if len(lines) > 1 else (lines[0] if lines else text)

    def _call_llm(self, messages: list[dict]) -> str:
        try:
            if self.provider in ("openai", "gemini"):
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=0.9,
                    max_tokens=150,
                )
                raw = resp.choices[0].message.content or ""
                return self._clean_reply(raw)

            if self.provider == "anthropic":
                system_text = ""
                chat_messages: list[dict] = []
                for m in messages:
                    if m["role"] == "system":
                        system_text = m["content"]
                    else:
                        chat_messages.append(m)

                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=150,
                    system=system_text,
                    messages=chat_messages,
                )
                raw = resp.content[0].text
                return self._clean_reply(raw)

        except Exception as e:
            logger.exception("LLM 调用失败")
            return f"抱歉，回复生成失败：{e}"

        return "不支持的 API 提供商"
