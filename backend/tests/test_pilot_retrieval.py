import unittest
from types import SimpleNamespace

from medical.pilot_retrieval import fuse, rerank
from medical.pilot_evaluate import metrics


def row(name):
    return {"id": name, "question": "问题", "answer": "未经核实的回答", "answer_eligible": False}


class PilotRetrievalTests(unittest.TestCase):
    def test_rrf_merges_ids_and_never_promotes_evidence(self):
        dense = [row("A"), row("B"), row("A")]
        lexical = [row("B"), row("C")]
        result = fuse(dense, lexical)
        self.assertEqual([r["id"] for r in result], ["B", "A", "C"])
        self.assertTrue(all(r["answer_eligible"] is False for r in result))
        self.assertAlmostEqual(result[1]["fusion_score"], .6/61)

    def test_reranker_can_change_order_without_mutating_inputs(self):
        candidates = fuse([row("A"), row("B")], [])
        model = SimpleNamespace(score=lambda q, p: [.01, .99])
        result, status = rerank("问题", candidates, model)
        self.assertEqual(status, "applied")
        self.assertEqual(result[0]["id"], "B")
        self.assertFalse(result[0]["answer_eligible"])
        self.assertNotIn("rerank_score", candidates[0])

    def test_corrupt_scores_fall_back_without_partial_results(self):
        candidates = fuse([row("A"), row("B")], [])
        for scores in ([.9], [.9, float("nan")], [.9, float("inf")], [-1, .9]):
            result, status = rerank("问题", candidates, SimpleNamespace(score=lambda q,p: scores))
            self.assertEqual(status, "fallback:ValueError")
            self.assertEqual(result, candidates)

    def test_metrics_count_multiple_relevant_documents_not_just_hit_rate(self):
        cases = [{"expected_ids": ["A", "B"], "dense": [row("A"), row("C")]}]
        result = metrics(cases, "dense")
        self.assertEqual(result["recall_at_5"], .5)
        self.assertEqual(result["mrr_at_5"], 1)
        self.assertLess(result["ndcg_at_5"], 1)

    def test_existing_evaluator_uses_true_multilabel_recall(self):
        from medical.evaluate import evaluate
        kb = SimpleNamespace(search=lambda q, limit: [SimpleNamespace(doc_id="A")])
        result = evaluate(kb, [{"id": "case", "query": "饮水", "expected_doc_ids": ["A", "B"]}], 5)
        self.assertEqual(result["recall_at_5"], .5)
        self.assertEqual(result["metric_version"], "multi_relevant_v2")


if __name__ == "__main__":
    unittest.main()
