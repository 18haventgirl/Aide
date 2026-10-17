"""Acceptance gates must detect loss even when the right document was hit."""
import copy
import unittest

from medical.compare_stage2 import audit_label_origins, gate_result, paired_changes, retained


def results():
    common = {"document_recall_at_budget": 1, "unanswerable_rejection_rate": .75,
              "evidence_span_recall_at_budget": 1, "critical_condition_retention": 1}
    probes = [{"id": f"EVS{i:02d}", "rerank_visible_ranges": {"evidence_spans": 1, "retained_spans": 1},
               "range_metrics": {"evidence_spans": 1, "retained_spans": 1}} for i in (1, 2, 3)]
    evidence = {**common, "critical_conditions": 10, "retained_conditions": 10, "details": probes}
    return {"evidence-regression": {"hybrid": dict(common), "rerank": evidence},
            "token-input-regression": {"hybrid": dict(common), "rerank": {**common, "details": [
                {"id": "TKF01", "rerank_inputs": [{"query_ranges": [[0, 5]]}]}]}}}


class ComparisonTests(unittest.TestCase):
    def test_editorial_scope_labels_are_disclosed_without_rewriting_frozen_cases(self):
        from medical.experiment import MEDICAL, load_suite
        from medical.knowledge_base import load_corpus
        _, groups = load_suite(MEDICAL/"evaluation/suite_v5.json")
        audit = audit_label_origins(groups, load_corpus(MEDICAL/"source_corpus"))
        self.assertEqual({row["case"] for row in audit["flags"]}, {"EVS09", "EVF03", "TKT03"})
        self.assertTrue(all(row["field"] == "required_conditions" for row in audit["flags"]))

    def test_paired_changes_do_not_turn_missing_range_labels_into_perfect_scores(self):
        before = [{"id": "a", "document_recall_at_budget": 0},
                  {"id": "b", "document_recall_at_budget": 1}]
        after = [{"id": "a", "document_recall_at_budget": 1},
                 {"id": "b", "document_recall_at_budget": 0}]
        delta = paired_changes(before, after)
        self.assertEqual(delta["document_recall"]["wins"], ["a"])
        self.assertEqual(delta["document_recall"]["losses"], ["b"])
        self.assertEqual(delta["final_spans"]["unmeasured"], 2)
        self.assertEqual(delta["final_spans"]["ties"], 0)

    def test_all_predeclared_gates_pass_only_with_visible_and_final_evidence(self):
        value = results()
        report = gate_result(value, copy.deepcopy(value), [{"id": "TKF01", "query": "完整的问题"}])
        self.assertTrue(report["input_and_regression_gates_passed"])

    def test_document_match_does_not_cover_missing_model_evidence(self):
        value, baseline = results(), results()
        value["evidence-regression"]["rerank"]["details"][0]["rerank_visible_ranges"]["retained_spans"] = 0
        report = gate_result(value, baseline, [{"id": "TKF01", "query": "完整的问题"}])
        self.assertFalse(report["input_and_regression_gates_passed"])
        self.assertFalse(report["three_probes"]["EVS01"]["model_input"])

    def test_condition_negative_and_query_tail_regressions_are_independent_failures(self):
        value, baseline = results(), results()
        value["evidence-regression"]["rerank"].update(retained_conditions=9, unanswerable_rejection_rate=.5)
        value["token-input-regression"]["rerank"]["details"][0]["rerank_inputs"][0]["query_ranges"] = [[0, 2]]
        report = gate_result(value, baseline, [{"id": "TKF01", "query": "完整的问题"}])
        for name in ("all_ten_labelled_conditions_retained", "negative_filter_not_below_same_code_legacy256", "current_question_checks"):
            self.assertFalse(report["gates"][name])
        self.assertFalse(retained("数字12", [[0, 2]]))


if __name__ == "__main__": unittest.main()
