import unittest
from medical.answer_audit import audit_answer, quantities


class AnswerAuditTests(unittest.TestCase):
    def test_detects_observed_headache_duration_problem(self):
        report = audit_answer("建议连续记录4–8周，就诊时带上。", [
            {"doc_id": "HEADACHE", "text": "建议记录发作时间、持续多久、哪里痛。"}])
        self.assertEqual(report["unmatched_count"], 1)
        self.assertEqual(report["observations"][0]["key"], "4-8周")

    def test_normalizes_width_range_and_units(self):
        report = audit_answer("运动１５０～３００分钟，药物5mg，体温38.5℃。", [
            {"doc_id": "A", "text": "150至300分钟，5毫克，38.5摄氏度。"}])
        self.assertEqual(report["quantity_count"], 3)
        self.assertEqual(report["unmatched_count"], 0)

    def test_same_number_different_unit_is_not_a_match(self):
        self.assertEqual(audit_answer("5毫克", [{"text": "5毫升"}])["unmatched_count"], 1)

    def test_list_numbers_links_and_citations_are_not_quantities(self):
        self.assertEqual(quantities("1. 休息 [E2] https://example.org/7天"), [])

    def test_match_does_not_claim_entailment_or_correctness(self):
        result = audit_answer("必须等5天才能就医", [{"doc_id": "A", "text": "不要等待5天才就医"}])
        self.assertEqual(result["observations"][0]["status"], "lexical_match_only")
        self.assertIn("not_medical_or_semantic", result["scope"])

    def test_no_evidence_still_reports_without_blocking_generation(self):
        self.assertEqual(audit_answer("观察2天", [])["unmatched_count"], 1)
        self.assertEqual(audit_answer("及时就医", [])["quantity_count"], 0)

    def test_repeated_quantity_deduplicates(self):
        self.assertEqual(audit_answer("5天，5天", [])["quantity_count"], 1)


if __name__ == "__main__":
    unittest.main()
