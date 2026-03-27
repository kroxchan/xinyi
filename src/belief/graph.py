from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.memory.embedder import TextEmbedder

logger = logging.getLogger(__name__)


class BeliefGraph:
    def __init__(self, filepath: str = "data/beliefs.json", embedder: TextEmbedder | None = None) -> None:
        self.filepath = Path(filepath)
        self.beliefs: dict[str, dict] = {}
        self.contradictions: list[tuple[str, str, str]] = []
        self.embedder = embedder
        self._embeddings: dict[str, list[float]] = {}
        self._next_id = 1
        self._load()

    def _load(self) -> None:
        if not self.filepath.exists():
            logger.info("Belief file not found, starting with empty graph: %s", self.filepath)
            return
        try:
            data = json.loads(self.filepath.read_text(encoding="utf-8"))
            self.beliefs = data.get("beliefs", {})
            self.contradictions = [tuple(c) for c in data.get("contradictions", [])]
            self._embeddings = data.get("embeddings", {})
            if self.beliefs:
                max_id = max(int(k.split("_")[1]) for k in self.beliefs if k.startswith("belief_"))
                self._next_id = max_id + 1
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to load belief file: %s", e)

    def add_belief(self, belief: dict) -> str:
        belief_id = f"belief_{self._next_id:04d}"
        self._next_id += 1

        now = datetime.now(timezone.utc).isoformat()
        entry = {
            **belief,
            "id": belief_id,
            "created_at": now,
            "updated_at": now,
            "source_conversations": belief.get("source_conversations", []),
        }
        self.beliefs[belief_id] = entry
        if self.embedder is not None:
            text = entry.get("topic", "") + " " + entry.get("stance", "")
            self._embeddings[belief_id] = self.embedder.embed_single(text)
        return belief_id

    def update_belief(self, belief_id: str, updates: dict) -> None:
        if belief_id not in self.beliefs:
            raise KeyError(f"Belief not found: {belief_id}")
        self.beliefs[belief_id].update(updates)
        self.beliefs[belief_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def query_by_topic(self, topic: str, top_k: int = 5) -> list[dict]:
        if self.embedder is not None:
            return self._query_by_embedding(topic, top_k)
        return self._query_by_ngram(topic, top_k)

    def _query_by_embedding(self, topic: str, top_k: int) -> list[dict]:
        self._ensure_embeddings()
        query_vec = self.embedder.embed_single(topic)
        scored: list[tuple[float, dict]] = []
        for belief_id, belief in self.beliefs.items():
            if belief_id not in self._embeddings:
                continue
            sim = self._cosine_similarity(query_vec, self._embeddings[belief_id])
            scored.append((sim, belief))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in scored[:top_k]]

    def _query_by_ngram(self, topic: str, top_k: int) -> list[dict]:
        query_grams: set[str] = set()
        for n in range(2, 5):
            for i in range(len(topic) - n + 1):
                query_grams.add(topic[i:i + n])
        if not query_grams:
            query_grams = {topic} if topic else set()

        scored: list[tuple[int, dict]] = []
        for belief in self.beliefs.values():
            belief_text = belief.get("topic", "") + belief.get("stance", "")
            score = sum(1 for gram in query_grams if gram in belief_text)
            if score > 0:
                scored.append((score, belief))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in scored[:top_k]]

    def query_all(self) -> list[dict]:
        return list(self.beliefs.values())

    def get_contradictions(self) -> list[tuple]:
        return list(self.contradictions)

    def add_contradiction(self, belief_a: str, belief_b: str, explanation: str) -> None:
        self.contradictions.append((belief_a, belief_b, explanation))

    def _ensure_embeddings(self) -> None:
        """Compute embeddings for beliefs that aren't cached yet."""
        if self.embedder is None:
            return
        missing_ids = [bid for bid in self.beliefs if bid not in self._embeddings]
        if not missing_ids:
            return
        texts = [
            self.beliefs[bid].get("topic", "") + " " + self.beliefs[bid].get("stance", "")
            for bid in missing_ids
        ]
        vectors = self.embedder.embed(texts)
        for bid, vec in zip(missing_ids, vectors):
            self._embeddings[bid] = vec
        logger.info("Computed embeddings for %d beliefs", len(missing_ids))

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def save(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "beliefs": self.beliefs,
            "contradictions": [list(c) for c in self.contradictions],
            "embeddings": self._embeddings,
        }
        self.filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Saved %d beliefs to %s", len(self.beliefs), self.filepath)

    def count(self) -> int:
        return len(self.beliefs)
