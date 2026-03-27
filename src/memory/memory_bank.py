"""Episodic memory bank — structured facts extracted from conversations.

Each memory has a confidence score that rises with repeated mentions across
different conversations / contacts.  Single off-hand remarks stay low-confidence
and are excluded from the prompt; only well-corroborated memories surface.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.memory.embedder import TextEmbedder

logger = logging.getLogger(__name__)

MEMORY_TYPES = ["fact", "event", "preference", "plan", "relationship", "habit"]

EXTRACTION_PROMPT = """\
你是一个记忆提取器。从下面的聊天记录中，**只从「我」说的话中**提取具体的事实性记忆。

记忆类型：
- fact: 客观事实（工作、住址、养宠物等）
- event: 发生过的事件（旅行、搬家、生病等）
- preference: 偏好（喜欢/不喜欢什么）
- plan: 计划或打算
- relationship: 人际关系信息（谁是谁）
- habit: 习惯（作息、运动、饮食规律等）

重要规则：
1. 只提取「我」明确说过的内容，不要推测
2. 对方说的不算我的记忆
3. 如果「我」的语气像开玩笑、夸张、反讽，标记 certainty 为 "low"
4. 如果是明确陈述的事实，标记 certainty 为 "high"
5. 如果不确定是否认真的，标记 certainty 为 "medium"
6. 每条记忆用一句话概括，不要太长

返回 JSON 数组，每个元素：
{{"type": "...", "content": "一句话描述", "certainty": "high|medium|low"}}

如果没有值得提取的记忆，返回空数组 []
不要输出任何 JSON 以外的内容。

聊天记录：
{text}
"""

MIN_CONFIDENCE_FOR_PROMPT = 0.4


class Memory:
    __slots__ = (
        "id", "type", "content", "confidence", "certainty",
        "mentions", "sources", "first_seen", "last_seen", "embedding",
    )

    def __init__(self, data: dict) -> None:
        self.id: int = data.get("id", 0)
        self.type: str = data.get("type", "fact")
        self.content: str = data.get("content", "")
        self.confidence: float = data.get("confidence", 0.3)
        self.certainty: str = data.get("certainty", "medium")
        self.mentions: int = data.get("mentions", 1)
        self.sources: list[str] = data.get("sources", [])
        self.first_seen: float = data.get("first_seen", time.time())
        self.last_seen: float = data.get("last_seen", time.time())
        self.embedding: list[float] | None = data.get("embedding")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "confidence": round(self.confidence, 3),
            "certainty": self.certainty,
            "mentions": self.mentions,
            "sources": self.sources,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    def reinforce(self, source: str = "", certainty: str = "medium") -> None:
        """Boost confidence when the same memory is mentioned again."""
        self.mentions += 1
        self.last_seen = time.time()
        if source and source not in self.sources:
            self.sources.append(source)
        cert_boost = {"high": 0.15, "medium": 0.08, "low": 0.03}
        self.confidence = min(1.0, self.confidence + cert_boost.get(certainty, 0.05))
        source_bonus = min(0.1, len(self.sources) * 0.03)
        self.confidence = min(1.0, self.confidence + source_bonus)
        if certainty == "high" and self.certainty != "high":
            self.certainty = "high"


class MemoryBank:
    def __init__(
        self,
        filepath: str = "data/memories.json",
        embedder: TextEmbedder | None = None,
    ) -> None:
        self.filepath = Path(filepath)
        self.embedder = embedder
        self.memories: list[Memory] = []
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                for d in data.get("memories", []):
                    self.memories.append(Memory(d))
                self._next_id = data.get("next_id", len(self.memories) + 1)
            except Exception as e:
                logger.error("Failed to load memory bank: %s", e)

    def save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "next_id": self._next_id,
            "memories": [m.to_dict() for m in self.memories],
        }
        self.filepath.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def count(self) -> int:
        return len(self.memories)

    def add(self, mem_type: str, content: str, certainty: str = "medium",
            source: str = "") -> Memory:
        """Add a new memory or reinforce an existing similar one."""
        existing = self._find_similar(content)
        if existing:
            existing.reinforce(source=source, certainty=certainty)
            return existing
        cert_base = {"high": 0.5, "medium": 0.3, "low": 0.15}
        m = Memory({
            "id": self._next_id,
            "type": mem_type,
            "content": content,
            "confidence": cert_base.get(certainty, 0.3),
            "certainty": certainty,
            "mentions": 1,
            "sources": [source] if source else [],
            "first_seen": time.time(),
            "last_seen": time.time(),
        })
        if self.embedder:
            m.embedding = self.embedder.embed_single(content)
        self._next_id += 1
        self.memories.append(m)
        return m

    def _find_similar(self, content: str, threshold: float = 0.85) -> Memory | None:
        """Find an existing memory that is semantically very similar."""
        if not self.embedder or not self.memories:
            return self._find_by_text_overlap(content)
        query_vec = self.embedder.embed_single(content)
        best, best_sim = None, 0.0
        for m in self.memories:
            if m.embedding is None:
                continue
            sim = self._cosine(query_vec, m.embedding)
            if sim > best_sim:
                best_sim = sim
                best = m
        return best if best_sim >= threshold else None

    def _find_by_text_overlap(self, content: str) -> Memory | None:
        for m in self.memories:
            if len(content) < 4 or len(m.content) < 4:
                continue
            shorter = content if len(content) <= len(m.content) else m.content
            longer = m.content if len(content) <= len(m.content) else content
            if shorter in longer:
                return m
        return None

    def query(self, text: str, top_k: int = 5,
              min_confidence: float = MIN_CONFIDENCE_FOR_PROMPT) -> list[Memory]:
        """Retrieve relevant memories above the confidence threshold."""
        candidates = [m for m in self.memories if m.confidence >= min_confidence]
        if not candidates:
            return []
        if not self.embedder:
            candidates.sort(key=lambda m: -m.confidence)
            return candidates[:top_k]
        query_vec = self.embedder.embed_single(text)
        scored = []
        for m in candidates:
            if m.embedding is None:
                m.embedding = self.embedder.embed_single(m.content)
            sim = self._cosine(query_vec, m.embedding)
            relevance = sim * 0.6 + m.confidence * 0.4
            scored.append((m, relevance))
        scored.sort(key=lambda x: -x[1])
        return [m for m, _ in scored[:top_k]]

    def format_for_prompt(self, memories: list[Memory]) -> str:
        if not memories:
            return ""
        lines = []
        for m in memories:
            conf_tag = "确定" if m.confidence >= 0.7 else "可能"
            lines.append(f"- [{conf_tag}] {m.content}")
        return "\n".join(lines)

    def extract_from_text(self, text: str, api_client, model: str,
                          source: str = "") -> list[Memory]:
        """Use LLM to extract memories from conversation text."""
        if len(text) < 20:
            return []
        prompt = EXTRACTION_PROMPT.format(text=text[:3000])
        try:
            resp = api_client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content or "[]"
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            items = json.loads(raw)
            if not isinstance(items, list):
                return []
        except Exception as e:
            logger.warning("Memory extraction failed: %s", e)
            return []

        added = []
        for item in items:
            if not isinstance(item, dict):
                continue
            content = item.get("content", "").strip()
            mem_type = item.get("type", "fact")
            certainty = item.get("certainty", "medium")
            if not content or len(content) < 2:
                continue
            if mem_type not in MEMORY_TYPES:
                mem_type = "fact"
            if certainty not in ("high", "medium", "low"):
                certainty = "medium"
            m = self.add(mem_type, content, certainty=certainty, source=source)
            added.append(m)
        return added

    def batch_extract(self, conversations: list[dict], api_client, model: str,
                      top_n_contacts: int = 8, samples_per_contact: int = 15) -> int:
        """Batch extract memories from training conversations."""
        from collections import Counter
        by_contact: dict[str, list[dict]] = {}
        for conv in conversations:
            contact = conv.get("contact", "")
            if not contact:
                continue
            by_contact.setdefault(contact, []).append(conv)

        contact_counts = Counter({c: len(v) for c, v in by_contact.items()})
        top_contacts = [c for c, _ in contact_counts.most_common(top_n_contacts)]

        total = 0
        for contact in top_contacts:
            convs = by_contact[contact]
            step = max(1, len(convs) // samples_per_contact)
            sampled = convs[::step][:samples_per_contact]
            for conv in sampled:
                text = conv.get("text", "")
                if len(text) < 30:
                    continue
                added = self.extract_from_text(
                    text, api_client, model,
                    source=contact[:20],
                )
                total += len(added)

        self.save()
        logger.info("Memory bank: extracted %d memories from %d contacts "
                     "(total %d, high-conf %d)",
                     total, len(top_contacts), self.count(),
                     sum(1 for m in self.memories if m.confidence >= 0.7))
        return total

    def rebuild_embeddings(self) -> None:
        if not self.embedder:
            return
        for m in self.memories:
            if m.embedding is None:
                m.embedding = self.embedder.embed_single(m.content)

    def clear(self) -> None:
        self.memories.clear()
        self._next_id = 1

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
