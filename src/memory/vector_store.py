from __future__ import annotations

import chromadb
from rich.progress import track

from .embedder import TextEmbedder

BATCH_SIZE = 100


class VectorStore:
    """ChromaDB 向量数据库操作，持久化到本地磁盘。"""

    def __init__(
        self,
        persist_dir: str = "data/chroma_db",
        collection_name: str = "conversations",
    ) -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_conversations(
        self,
        conversations: list[dict],
        embedder: TextEmbedder,
    ) -> None:
        for i in track(
            range(0, len(conversations), BATCH_SIZE),
            description="写入向量库",
        ):
            batch = conversations[i : i + BATCH_SIZE]
            ids = [c["id"] for c in batch]
            documents = [c["text"] for c in batch]
            metadatas = [
                {
                    "contact": c["contact"],
                    "start_time": c["start_time"],
                    "end_time": c["end_time"],
                    "turn_count": c["turn_count"],
                    "emotion_tag": c.get("emotion_tag", "neutral"),
                }
                for c in batch
            ]
            embeddings = embedder.embed(documents)

            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embeddings,
            )

    def search(
        self,
        query: str,
        embedder: TextEmbedder,
        top_k: int = 5,
        contact_filter: str | None = None,
    ) -> list[dict]:
        query_embedding = embedder.embed_single(query)
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if contact_filter:
            kwargs["where"] = {"contact": contact_filter}
        results = self.collection.query(**kwargs)

        hits: list[dict] = []
        for idx in range(len(results["ids"][0])):
            hits.append(
                {
                    "id": results["ids"][0][idx],
                    "text": results["documents"][0][idx],
                    "metadata": results["metadatas"][0][idx],
                    "distance": results["distances"][0][idx],
                }
            )
        return hits

    def sample_conversations(
        self,
        contact_filter: str | None = None,
        n: int = 10,
    ) -> list[dict]:
        """Fetch a random-ish sample of conversations for few-shot prompting."""
        import random
        kwargs: dict = {"include": ["documents", "metadatas"]}
        if contact_filter:
            kwargs["where"] = {"contact": contact_filter}

        try:
            total = self.collection.count()
            if total == 0:
                return []
            limit = min(total, 200)
            offset = random.randint(0, max(0, total - limit))
            results = self.collection.get(
                limit=limit, offset=offset, **kwargs,
            )
        except Exception:
            results = self.collection.get(limit=50, **kwargs)

        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        items = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            items.append({"text": doc, "metadata": meta})

        if contact_filter:
            items = [it for it in items if it["metadata"].get("contact") == contact_filter]

        good = [it for it in items if 30 < len(it["text"]) < 500 and it["text"].count("我:") >= 2]
        if len(good) < n:
            good = [it for it in items if len(it["text"]) > 20]
        random.shuffle(good)
        return good[:n]

    def count(self) -> int:
        return self.collection.count()

    def clear(self) -> None:
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def has_metadata_key(self, key: str, sample_limit: int = 200) -> bool:
        if self.count() == 0:
            return False
        try:
            results = self.collection.get(limit=sample_limit, include=["metadatas"])
            metadatas = results.get("metadatas", []) or []
            return any(isinstance(meta, dict) and meta.get(key) not in (None, "") for meta in metadatas)
        except Exception:
            return False
