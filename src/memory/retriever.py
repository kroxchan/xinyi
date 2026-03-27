from __future__ import annotations

from .embedder import TextEmbedder
from .vector_store import VectorStore


class MemoryRetriever:
    """高级检索逻辑，组合向量检索结果并格式化为 prompt 上下文。"""

    def __init__(self, vector_store: VectorStore, embedder: TextEmbedder) -> None:
        self.vector_store = vector_store
        self.embedder = embedder

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        contact_wxid: str | None = None,
    ) -> str:
        results = self.vector_store.search(
            query, self.embedder, top_k=top_k, contact_filter=contact_wxid,
        )

        if not results:
            if contact_wxid:
                results = self.vector_store.search(
                    query, self.embedder, top_k=top_k,
                )
            if not results:
                return "（没有找到相关记忆）"

        fragments: list[str] = []
        for i, hit in enumerate(results, 1):
            meta = hit["metadata"]
            date = meta.get("start_time", "未知时间")
            contact = meta.get("contact", "未知联系人")
            header = f"[记忆片段{i}] ({date} 与{contact}的对话)"
            fragments.append(f"{header}\n{hit['text']}")

        return "\n---\n".join(fragments)
