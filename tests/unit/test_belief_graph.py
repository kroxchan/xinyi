from __future__ import annotations

import json


class _FakeEmbedder:
    def embed_single(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


def test_update_belief_refreshes_embedding_and_persists(tmp_path):
    from src.belief.graph import BeliefGraph

    graph = BeliefGraph(filepath=str(tmp_path / "beliefs.json"), embedder=_FakeEmbedder())
    belief_id = graph.add_belief({
        "topic": "关系",
        "stance": "需要沟通",
        "confidence": 0.6,
        "source": "test",
    })

    original = list(graph._embeddings[belief_id])
    graph.update_belief(belief_id, {"topic": "关系边界", "stance": "需要直接沟通"})
    graph.save()

    assert graph.beliefs[belief_id]["topic"] == "关系边界"
    assert graph._embeddings[belief_id] != original

    saved = json.loads((tmp_path / "beliefs.json").read_text("utf-8"))
    assert saved["beliefs"][belief_id]["stance"] == "需要直接沟通"


def test_delete_belief_removes_related_contradictions(tmp_path):
    from src.belief.graph import BeliefGraph

    graph = BeliefGraph(filepath=str(tmp_path / "beliefs.json"))
    a = graph.add_belief({"topic": "A", "stance": "1"})
    b = graph.add_belief({"topic": "B", "stance": "2"})
    graph.add_contradiction(a, b, "冲突")

    graph.delete_belief(a)

    assert a not in graph.beliefs
    assert graph.get_contradictions() == []
