from __future__ import annotations

from src.logging_config import get_logger

from .embedder import TextEmbedder
from .vector_store import VectorStore

logger = get_logger(__name__)


class MemoryRetriever:
    """高级检索逻辑，组合向量检索结果并格式化为 prompt 上下文。"""

    def __init__(
        self,
        vector_store: VectorStore,
        embedder: TextEmbedder,
        reranker=None,
        top_k_raw: int = 20,
        top_k_reranked: int = 5,
        emotion_tagger=None,
        emotion_boost_weight: float = 1.5,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.reranker = reranker
        self.top_k_raw = max(top_k_raw, 1)
        self.top_k_reranked = max(top_k_reranked, 1)
        self.emotion_tagger = emotion_tagger
        self.emotion_boost_weight = max(emotion_boost_weight, 1.0)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        contact_wxid: str | None = None,
        query_emotion: str | None = None,
    ) -> str:
        raw_top_k = max(top_k, self.top_k_raw)
        results = self.vector_store.search(
            query, self.embedder, top_k=raw_top_k, contact_filter=contact_wxid,
        )

        if not results:
            if contact_wxid:
                results = self.vector_store.search(
                    query, self.embedder, top_k=raw_top_k,
                )
            if not results:
                return "（没有找到相关记忆）"

        results = self._postprocess_hits(query, results, top_k, query_emotion=query_emotion)

        fragments: list[str] = []
        for i, hit in enumerate(results, 1):
            meta = hit["metadata"]
            date = meta.get("start_time", "未知时间")
            contact = meta.get("contact", "未知联系人")
            header = f"[记忆片段{i}] ({date} 与{contact}的对话)"
            fragments.append(f"{header}\n{hit['text']}")

        return "\n---\n".join(fragments)

    def _postprocess_hits(
        self,
        query: str,
        hits: list[dict],
        top_k: int,
        query_emotion: str | None = None,
    ) -> list[dict]:
        ranked_hits = [dict(hit) for hit in hits]

        if self.reranker:
            try:
                reranked_k = min(len(ranked_hits), max(top_k, self.top_k_reranked))
                reranked_hits = self.reranker.rerank(
                    query,
                    [hit["text"] for hit in ranked_hits],
                    top_k=reranked_k,
                )
                ranked_hits = self._merge_rerank_results(ranked_hits, reranked_hits)
            except Exception as exc:
                logger.warning("Rerank failed, falling back to vector order: %s", exc)

        if query_emotion:
            try:
                ranked_hits = self._apply_emotion_boost(query_emotion, ranked_hits)
            except Exception as exc:
                logger.warning("Emotion boost failed, falling back to current order: %s", exc)

        return ranked_hits[:top_k]

    def _merge_rerank_results(self, hits: list[dict], reranked_hits: list[dict]) -> list[dict]:
        if not reranked_hits:
            return hits

        merged: list[dict] = []
        used_indices: set[int] = set()
        for item in reranked_hits:
            for idx, hit in enumerate(hits):
                if idx in used_indices:
                    continue
                if hit["text"] != item["content"]:
                    continue
                merged_hit = dict(hit)
                merged_hit["rerank_score"] = float(item.get("score", 0.0))
                merged.append(merged_hit)
                used_indices.add(idx)
                break

        for idx, hit in enumerate(hits):
            if idx not in used_indices:
                merged.append(hit)

        return merged

    def _apply_emotion_boost(self, query_emotion: str, hits: list[dict]) -> list[dict]:
        if not hits:
            return hits
        if query_emotion == "neutral":
            return hits
        boosted: list[dict] = []
        match_count = 0
        for hit in hits:
            scored_hit = dict(hit)
            candidate_emotion = str(scored_hit.get("metadata", {}).get("emotion_tag", "neutral"))
            scored_hit["emotion_label"] = candidate_emotion
            score = self._base_score(scored_hit)
            if candidate_emotion == query_emotion:
                score *= self.emotion_boost_weight
                match_count += 1
            scored_hit["_retrieval_score"] = score
            boosted.append(scored_hit)

        boosted.sort(key=lambda hit: hit.get("_retrieval_score", self._base_score(hit)), reverse=True)
        logger.info(
            "emotion boost: query=%s, matched=%d/%d, weight=%.2f",
            query_emotion,
            match_count,
            len(boosted),
            self.emotion_boost_weight,
        )
        return boosted

    @staticmethod
    def _base_score(hit: dict) -> float:
        if "rerank_score" in hit:
            return float(hit["rerank_score"])
        dist = float(hit.get("distance", 1.0))
        return 1.0 / (1.0 + max(dist, 0.0))
