"""Digital twin evaluation system.

Provides quantitative metrics to measure "how close is the twin to the real person":
1. Style consistency  — message length, emoji usage, punctuation patterns
2. Semantic similarity — embedding similarity between twin replies and real replies
3. Self-consistency    — ask the same question N times, measure answer variance
4. Blind test          — format real vs twin replies for human A/B evaluation
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.memory.embedder import TextEmbedder

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    style_score: float = 0.0
    semantic_score: float = 0.0
    consistency_score: float = 0.0
    detail: dict = field(default_factory=dict)

    @property
    def overall(self) -> float:
        return round(
            self.style_score * 0.3
            + self.semantic_score * 0.4
            + self.consistency_score * 0.3,
            3,
        )

    def summary(self) -> str:
        lines = [
            f"综合评分: {self.overall:.1%}",
            f"  风格一致性: {self.style_score:.1%}",
            f"  语义相似度: {self.semantic_score:.1%}",
            f"  自我一致性: {self.consistency_score:.1%}",
        ]
        if self.detail.get("style"):
            d = self.detail["style"]
            lines.append(f"  └ 长度偏差: {d.get('length_diff', 0):.1f}字, "
                         f"表情偏差: {d.get('emoji_diff', 0):.2f}")
        if self.detail.get("semantic"):
            d = self.detail["semantic"]
            lines.append(f"  └ 平均余弦相似度: {d.get('avg_cosine', 0):.3f}, "
                         f"测试对数: {d.get('pair_count', 0)}")
        if self.detail.get("consistency"):
            d = self.detail["consistency"]
            lines.append(f"  └ 平均回答相似度: {d.get('avg_similarity', 0):.3f}, "
                         f"测试题数: {d.get('question_count', 0)}")
        return "\n".join(lines)


class TwinEvaluator:
    """Evaluate digital twin quality against real conversation data."""

    def __init__(
        self,
        chat_engine,
        embedder: TextEmbedder | None = None,
        persona_profile: dict | None = None,
        contact_registry=None,
        twin_mode: str = "self",
    ) -> None:
        self.chat_engine = chat_engine
        self.embedder = embedder
        self.profile = persona_profile or {}
        self._contact_registry = contact_registry
        self.twin_mode = twin_mode

    def evaluate(
        self,
        test_conversations: list[dict],
        n_style_samples: int = 100,
        n_semantic_samples: int = 30,
        consistency_questions: list[str] | None = None,
        consistency_repeats: int = 3,
    ) -> EvalResult:
        result = EvalResult()

        qa_pairs = self._extract_qa_pairs(test_conversations)
        if not qa_pairs:
            logger.warning("No QA pairs found for evaluation")
            return result

        result.style_score, result.detail["style"] = self._eval_style(
            qa_pairs, n_style_samples
        )

        if self.embedder:
            result.semantic_score, result.detail["semantic"] = self._eval_semantic(
                qa_pairs, n_semantic_samples
            )

        if consistency_questions:
            result.consistency_score, result.detail["consistency"] = (
                self._eval_consistency(consistency_questions, consistency_repeats)
            )
        else:
            result.consistency_score = result.semantic_score

        return result

    def _extract_qa_pairs(
        self, conversations: list[dict], context_turns: int = 5,
    ) -> list[dict]:
        """Extract (context, question, real_answer) triples from conversations.

        conversation_builder 已根据 twin_mode 翻转过角色：
        - role="self" 始终是被训练方（twin_mode=self 时是我，partner 时是对象）
        - role="other" 始终是对话另一方
        因此这里统一用 other→self：other 提问，self 的真实回复作为基准。
        """
        pairs = []
        for conv in conversations:
            turns = conv.get("turns", [])
            contact = conv.get("contact", "")
            for i in range(len(turns) - 1):
                if turns[i]["role"] == "other" and turns[i + 1]["role"] == "self":
                    q = turns[i]["content"].strip()
                    a = turns[i + 1]["content"].strip()
                    if len(q) < 2 or len(a) < 2:
                        continue
                    ctx: list[dict] = []
                    for j in range(max(0, i - context_turns), i):
                        role = "assistant" if turns[j]["role"] == "self" else "user"
                        ctx.append({"role": role, "content": turns[j]["content"]})
                    pairs.append({
                        "question": q,
                        "real_answer": a,
                        "context": ctx,
                        "contact": contact,
                    })
        return pairs

    def _eval_style(
        self, qa_pairs: list[dict], n_samples: int
    ) -> tuple[float, dict]:
        """Compare style metrics between twin replies and real replies."""
        samples = random.sample(qa_pairs, min(n_samples, len(qa_pairs)))

        real_lengths = []
        twin_lengths = []
        real_emoji_counts = []
        twin_emoji_counts = []

        emoji_re = re.compile(r"\[[\u4e00-\u9fff\w]+\]")

        for pair in samples:
            try:
                twin_reply = self._reply_with_context(pair)
            except Exception:
                continue

            real = pair["real_answer"]
            real_lengths.append(len(real))
            twin_lengths.append(len(twin_reply))
            real_emoji_counts.append(len(emoji_re.findall(real)))
            twin_emoji_counts.append(len(emoji_re.findall(twin_reply)))

        if not real_lengths:
            return 0.0, {}

        avg_real_len = sum(real_lengths) / len(real_lengths)
        avg_twin_len = sum(twin_lengths) / len(twin_lengths)
        length_diff = abs(avg_real_len - avg_twin_len)
        length_score = max(0, 1.0 - length_diff / max(avg_real_len, 1))

        avg_real_emoji = sum(real_emoji_counts) / len(real_emoji_counts)
        avg_twin_emoji = sum(twin_emoji_counts) / len(twin_emoji_counts)
        emoji_diff = abs(avg_real_emoji - avg_twin_emoji)
        emoji_score = max(0, 1.0 - emoji_diff / max(avg_real_emoji, 0.5))

        score = length_score * 0.6 + emoji_score * 0.4

        return round(score, 3), {
            "length_diff": round(length_diff, 1),
            "emoji_diff": round(emoji_diff, 2),
            "avg_real_len": round(avg_real_len, 1),
            "avg_twin_len": round(avg_twin_len, 1),
            "samples_tested": len(real_lengths),
        }

    def _eval_semantic(
        self, qa_pairs: list[dict], n_samples: int
    ) -> tuple[float, dict]:
        """Compute embedding similarity between twin replies and real replies."""
        import math

        samples = random.sample(qa_pairs, min(n_samples, len(qa_pairs)))
        similarities = []

        for pair in samples:
            try:
                twin_reply = self._reply_with_context(pair)
            except Exception:
                continue

            real = pair["real_answer"]
            try:
                vecs = self.embedder.embed([real, twin_reply])
                sim = self._cosine(vecs[0], vecs[1])
                similarities.append(sim)
            except Exception:
                continue

        if not similarities:
            return 0.0, {}

        avg_sim = sum(similarities) / len(similarities)
        return round(avg_sim, 3), {
            "avg_cosine": round(avg_sim, 3),
            "min_cosine": round(min(similarities), 3),
            "max_cosine": round(max(similarities), 3),
            "pair_count": len(similarities),
        }

    def _eval_consistency(
        self, questions: list[str], repeats: int
    ) -> tuple[float, dict]:
        """Ask the same questions multiple times and measure answer consistency."""
        import math

        question_scores = []

        for q in questions:
            answers = []
            for _ in range(repeats):
                try:
                    reply = self.chat_engine.quick_reply(q)
                    answers.append(reply)
                except Exception:
                    try:
                        answers.append(self._simple_chat(q))
                    except Exception:
                        continue

            if len(answers) < 2 or not self.embedder:
                continue

            vecs = self.embedder.embed(answers)
            pair_sims = []
            for i in range(len(vecs)):
                for j in range(i + 1, len(vecs)):
                    pair_sims.append(self._cosine(vecs[i], vecs[j]))

            if pair_sims:
                question_scores.append(sum(pair_sims) / len(pair_sims))

        if not question_scores:
            return 0.0, {}

        avg = sum(question_scores) / len(question_scores)
        return round(avg, 3), {
            "avg_similarity": round(avg, 3),
            "question_count": len(question_scores),
        }

    def generate_blind_test(
        self, qa_pairs: list[dict], n: int = 10
    ) -> list[dict]:
        """Generate A/B blind test items for human evaluation.

        Each test item includes the preceding conversation context so testers
        can judge replies in their original conversational setting.
        """
        samples = random.sample(qa_pairs, min(n, len(qa_pairs)))
        tests = []

        for pair in samples:
            try:
                twin_reply = self._reply_with_context(pair)
            except Exception:
                continue

            real = pair["real_answer"]
            options = [
                {"text": real, "is_real": True},
                {"text": twin_reply, "is_real": False},
            ]
            random.shuffle(options)
            tests.append({
                "question": pair["question"],
                "context": pair.get("context", []),
                "contact": pair.get("contact", ""),
                "option_a": options[0]["text"],
                "option_b": options[1]["text"],
                "answer": "A" if options[0]["is_real"] else "B",
            })

        return tests

    def _reply_with_context(self, pair: dict) -> str:
        """Generate a twin reply using the pair's preceding conversation context.

        Only passes chat_history (preceding turns) — does NOT filter by
        contact_wxid to avoid degrading memory/few-shot retrieval quality
        when per-contact data is sparse.
        """
        ctx = pair.get("context", [])
        result = self.chat_engine.chat(
            pair["question"],
            chat_history=ctx,
            contact_wxid=None,
            contact_context=None,
        )
        if isinstance(result, dict):
            return result.get("content", result.get("reply", str(result)))
        return str(result)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        import math
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
