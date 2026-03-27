from __future__ import annotations

import logging
import uuid

from src.belief.extractor import BeliefExtractor
from src.belief.graph import BeliefGraph
from src.memory.vector_store import VectorStore
from src.memory.embedder import TextEmbedder

logger = logging.getLogger(__name__)


class LearningLoop:
    """对话后学习循环——从新对话中提取信念并更新图谱。"""

    def __init__(
        self,
        belief_extractor: BeliefExtractor,
        belief_graph: BeliefGraph,
        vector_store: VectorStore,
        embedder: TextEmbedder,
    ) -> None:
        self.belief_extractor = belief_extractor
        self.belief_graph = belief_graph
        self.vector_store = vector_store
        self.embedder = embedder

    def learn_from_conversation(
        self,
        conversation_text: str,
        conversation_id: str | None = None,
    ) -> int:
        if not conversation_id:
            conversation_id = f"live_{uuid.uuid4().hex[:8]}"

        new_beliefs = self.belief_extractor.extract_beliefs(conversation_text)
        added_count = 0

        for belief in new_beliefs:
            topic = belief.get("topic", "")
            if not topic:
                continue

            existing = self.belief_graph.query_by_topic(topic, top_k=1)

            if existing and existing[0].get("topic") == topic:
                old = existing[0]
                new_confidence = min(1.0, old.get("confidence", 0.5) + 0.1)
                self.belief_graph.update_belief(
                    old["id"], {"confidence": new_confidence}
                )
            else:
                belief.setdefault("confidence", 0.6)
                belief.setdefault("source", conversation_id)
                self.belief_graph.add_belief(belief)
                added_count += 1

        conv_doc = {
            "id": conversation_id,
            "text": conversation_text,
            "contact": "live_chat",
            "start_time": "",
            "end_time": "",
            "turn_count": conversation_text.count("\n") + 1,
        }
        self.vector_store.add_conversations([conv_doc], self.embedder)

        self.belief_graph.save()

        logger.info(
            "学习完成: 提取 %d 条信念, 新增 %d 条", len(new_beliefs), added_count
        )
        return added_count

    def learn_from_task_result(
        self,
        inferred_beliefs: list[dict],
        source: str = "task",
    ) -> int:
        """Write beliefs extracted by inference engine (from cognitive tasks) into the graph."""
        added = 0
        for belief in inferred_beliefs:
            topic = belief.get("topic", "")
            if not topic:
                continue
            existing = self.belief_graph.query_by_topic(topic, top_k=1)
            if existing and existing[0].get("topic") == topic:
                old = existing[0]
                new_conf = min(1.0, old.get("confidence", 0.5) + 0.1)
                self.belief_graph.update_belief(old["id"], {"confidence": new_conf})
            else:
                belief.setdefault("confidence", 0.6)
                belief.setdefault("source", source)
                self.belief_graph.add_belief(belief)
                added += 1
        self.belief_graph.save()
        return added

    def batch_extract_beliefs(
        self,
        conversations: list[dict],
        top_n_contacts: int = 5,
        samples_per_contact: int = 30,
    ) -> int:
        """Batch extract beliefs from training conversations."""
        from collections import Counter

        by_contact: dict[str, list[dict]] = {}
        for conv in conversations:
            contact = conv.get("contact", "")
            if not contact or "@chatroom" in contact:
                continue
            by_contact.setdefault(contact, []).append(conv)

        contact_counts = Counter({c: len(v) for c, v in by_contact.items()})
        top_contacts = [c for c, _ in contact_counts.most_common(top_n_contacts)]

        total_added = 0
        for contact in top_contacts:
            convs = by_contact[contact]
            step = max(1, len(convs) // samples_per_contact)
            sampled = convs[::step][:samples_per_contact]

            for conv in sampled:
                text = conv.get("text", "")
                if not text or len(text) < 20:
                    continue
                try:
                    new_beliefs = self.belief_extractor.extract_beliefs(text)
                    for belief in new_beliefs:
                        topic = belief.get("topic", "")
                        if not topic:
                            continue
                        existing = self.belief_graph.query_by_topic(topic, top_k=1)
                        if existing and existing[0].get("topic") == topic:
                            old = existing[0]
                            new_conf = min(1.0, old.get("confidence", 0.5) + 0.1)
                            self.belief_graph.update_belief(old["id"], {"confidence": new_conf})
                        else:
                            belief.setdefault("confidence", 0.6)
                            belief.setdefault("source", "batch_" + contact[:20])
                            self.belief_graph.add_belief(belief)
                            total_added += 1
                except Exception as e:
                    logger.warning("Belief extraction failed: %s", e)

        self.belief_graph.save()
        logger.info("Batch beliefs: %d new from %d contacts", total_added, len(top_contacts))
        return total_added
