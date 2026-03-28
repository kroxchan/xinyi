"""BM25 关键词搜索 — 与向量检索互补。

在日志文件中进行 BM25 关键词搜索，与 ChromaDB 向量检索形成互补。
使用纯 Python 实现（基于 rank_bm25 库或简单词频统计）。

BM25 优势：
- 关键词精确匹配（向量检索可能漏掉）
- 对短查询效果好
- 计算速度快

Example:
    bm25 = BM25Search(Path("data/twin_workspace/logs"))
    bm25.reindex()  # 初次使用或日志更新后
    results = bm25.search("工作 压力", top_k=3)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from rank_bm25 import BM25Okapi
    HAS_RANK_BM25 = True
except ImportError:
    HAS_RANK_BM25 = False

from src.logging_config import get_logger

logger = get_logger(__name__)


class BM25Search:
    """轻量级 BM25 搜索，搜索日志文件。

    实现策略：
    - 优先使用 rank_bm25 库（如果已安装）
    - 否则使用简单词频统计作为替代

    特性：
    - 自动索引日志文件
    - 增量更新（新增日志无需完全重建索引）
    - 与向量检索互补的关键词搜索
    """

    def __init__(
        self,
        logs_dir: str | Path = "data/twin_workspace/logs",
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.k1 = k1
        self.b = b

        # 索引数据
        self._documents: list[str] = []  # 分词后的文档
        self._doc_sources: list[Path] = []  # 文档来源文件
        self._doc_ids: list[str] = []  # 文档 ID（会话 ID）
        self._tokenized_docs: list[list[str]] = []

        # BM25 索引（使用 rank_bm25 库时）
        self._bm25: Any = None

        # 简单索引（不使用 rank_bm25 库时）
        self._simple_index: list[dict[str, int]] = []
        self._avg_doc_len = 0

        # 尝试加载/构建索引
        self._load_index()

    def _tokenize(self, text: str) -> list[str]:
        """中文分词（简单实现，使用字符级分词 + 停用词过滤）。"""
        if not text:
            return []

        # 预处理
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)

        # 简单分词：按空格分割，然后过滤
        tokens = []
        for word in text.split():
            word = word.strip()
            if len(word) >= 2:
                tokens.append(word)

        return tokens

    def _load_index(self) -> None:
        """加载日志文件并构建索引。"""
        self._documents.clear()
        self._doc_sources.clear()
        self._doc_ids.clear()
        self._tokenized_docs.clear()

        if not self.logs_dir.exists():
            logger.debug("Logs directory does not exist, no index to load")
            return

        # 扫描所有日志文件
        for log_file in sorted(self.logs_dir.glob("????-??-??.md"), reverse=True):
            try:
                content = log_file.read_text(encoding="utf-8")
                if not content.strip():
                    continue

                # 提取会话段落
                sessions = self._extract_sessions(content)

                for session_content, session_id in sessions:
                    tokens = self._tokenize(session_content)
                    if tokens:
                        self._documents.append(session_content)
                        self._doc_sources.append(log_file)
                        self._doc_ids.append(session_id)
                        self._tokenized_docs.append(tokens)

            except Exception as e:
                logger.warning("Failed to index %s: %s", log_file.name, e)

        # 构建 BM25 索引
        if self._tokenized_docs:
            if HAS_RANK_BM25:
                self._bm25 = BM25Okapi(self._tokenized_docs)
                logger.info("Built BM25 index with %d documents", len(self._tokenized_docs))
            else:
                self._build_simple_index()
                logger.info("Built simple index with %d documents", len(self._tokenized_docs))

    def _extract_sessions(self, content: str) -> list[tuple[str, str]]:
        """从日志内容中提取会话段落。"""
        sessions = []

        # 按 ### 会话 分割
        pattern = re.compile(r"### 会话 (\S+)")
        parts = pattern.split(content)

        if len(parts) < 2:
            # 没有会话分隔，按日期文件作为单个文档
            return [(content, "full")]

        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                session_id = parts[i]
                session_content = parts[i + 1]
                sessions.append((session_content[:500], session_id))  # 限制长度

        return sessions if sessions else [(content, "full")]

    def _build_simple_index(self) -> None:
        """构建简单索引（不使用 rank_bm25 库时）。"""
        self._simple_index = []
        total_len = 0

        for doc in self._tokenized_docs:
            self._simple_index.append(Counter(doc))
            total_len += len(doc)

        self._avg_doc_len = total_len / len(self._tokenized_docs) if self._tokenized_docs else 0

    def _simple_bm25_score(self, query_tokens: list[str], doc_idx: int) -> float:
        """简单 BM25 评分实现。"""
        if doc_idx >= len(self._simple_index) or self._avg_doc_len == 0:
            return 0.0

        doc_counter = self._simple_index[doc_idx]
        doc_len = sum(doc_counter.values())

        score = 0.0
        N = len(self._simple_index)
        doc_freq = Counter()

        # 计算文档频率
        for doc in self._simple_index:
            for token in doc:
                doc_freq[token] += 1

        for token in query_tokens:
            if token not in doc_counter:
                continue

            df = doc_freq.get(token, 0)
            if df == 0:
                continue

            # IDF
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
            # TF
            tf = doc_counter[token]
            # BM25 TF 正规化
            tf_norm = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * doc_len / self._avg_doc_len))

            score += idf * tf_norm

        return score

    def reindex(self) -> int:
        """重新构建索引。

        Returns:
            索引的文档数量
        """
        self._load_index()
        return len(self._documents)

    def add_document(self, content: str, doc_id: str = "") -> None:
        """添加单个文档到索引。

        Args:
            content: 文档内容
            doc_id: 文档 ID
        """
        tokens = self._tokenize(content)
        if not tokens:
            return

        self._documents.append(content)
        self._doc_sources.append(self.logs_dir)
        self._doc_ids.append(doc_id)
        self._tokenized_docs.append(tokens)

        if HAS_RANK_BM25 and self._bm25 is not None:
            self._bm25 = BM25Okapi(self._tokenized_docs)
        elif self._simple_index is not None:
            self._simple_index.append(Counter(tokens))
            self._avg_doc_len = sum(sum(c.values()) for c in self._simple_index) / len(self._simple_index)

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """BM25 搜索。

        Args:
            query: 搜索查询
            top_k: 返回结果数量

        Returns:
            结果列表，每项包含 doc_id, content, source, score
        """
        if not self._tokenized_docs:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        # 计算每个文档的 BM25 得分
        scores: list[tuple[int, float]] = []

        if HAS_RANK_BM25 and self._bm25 is not None:
            raw_scores = self._bm25.get_scores(query_tokens)
            for i, score in enumerate(raw_scores):
                if score > 0:
                    scores.append((i, score))
        else:
            for i in range(len(self._tokenized_docs)):
                score = self._simple_bm25_score(query_tokens, i)
                if score > 0:
                    scores.append((i, score))

        # 按得分排序
        scores.sort(key=lambda x: -x[1])

        # 构建结果
        results = []
        for doc_idx, score in scores[:top_k]:
            results.append({
                "doc_id": self._doc_ids[doc_idx],
                "content": self._documents[doc_idx][:300],
                "source": str(self._doc_sources[doc_idx].name),
                "score": round(score, 4),
            })

        return results

    def search_multi(self, queries: list[str], top_k: int = 3) -> dict[str, list[dict]]:
        """多查询搜索。

        Args:
            queries: 查询列表
            top_k: 每个查询返回的结果数

        Returns:
            字典，key 为查询，value 为结果列表
        """
        results = {}
        for query in queries:
            results[query] = self.search(query, top_k=top_k)
        return results

    def count(self) -> int:
        """返回索引中的文档数量。"""
        return len(self._documents)

    def get_stats(self) -> dict[str, Any]:
        """获取索引统计信息。"""
        return {
            "document_count": len(self._documents),
            "avg_doc_length": self._avg_doc_len,
            "has_rank_bm25": HAS_RANK_BM25,
            "logs_dir": str(self.logs_dir),
        }
