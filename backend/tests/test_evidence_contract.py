"""Meaningful evidence-budget, provenance and failure-denominator contracts."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from medical.chunking import chunk_document
from medical.evidence_contract import EvidenceBudget, build_evidence_pack, canonical_hash
from medical.evaluate import evaluate, validate_cases
from medical.evaluation.evidence import evaluate_evidence
from medical.evaluation.metrics import score_ranges, validate_references
from medical.experiment import MEDICAL, load_suite, run_experiment
from medical.schema import MedicalDocument, MedicalHit
from medical.source_provenance import SourceResolver, body_hash, chunk_key


def document(did="A", body="# 章节\n明确结论。关键条件甲。关键条件乙。"):
    return MedicalDocument(doc_id=did, version=1, title=f"合成资料{did}", topic="合成测试",
                           audience="成年人", source_org="合成测试机构", source_url=f"https://example.org/{did}",
                           source_published_at="2024-01-01", status="source_checked", reviewer="source test",
                           reviewed_at="2026-01-01", next_review_at="2099-01-01", license_note="合成测试数据",
                           source_sha256="0"*64, source_locator="合成章节", source_collected_at="2026-01-01", body=body)


def hits_for(doc):
    return [MedicalHit(chunk_id=chunk_key(doc, chunk), doc_id=doc.doc_id, title=doc.title,
                       section_path=chunk.section_path, text=f"{doc.title}\n{chunk.section_path}\n{chunk.text}",
                       source_org=doc.source_org, source_url=str(doc.source_url), source_sha256=doc.source_sha256,
                       document_version=doc.version, status=doc.status, reviewed_at=doc.reviewed_at)
            for chunk in chunk_document(doc.body, doc.title)]


def reference(doc):
    def span(text):
        start = doc.body.index(text)
        return [start, start+len(text)]
    return {"doc_id": doc.doc_id, "version": doc.version, "body_sha256": body_hash(doc.body),
            "ranges": [span("明确结论")], "required_conditions": [span("关键条件甲"), span("关键条件乙")]}


class Search:
    def __init__(self, hits, broken=False): self.hits, self.broken = hits, broken
    def search(self, query, limit=20):
        self.limit = limit
        if self.broken: raise RuntimeError("injected retrieval failure")
        return self.hits[:limit]


class EvidenceContractTests(unittest.TestCase):
    def test_exact_reconstruction_and_both_conditions(self):
        doc = document()
        pack = build_evidence_pack(hits_for(doc), resolver=SourceResolver([doc]))
        scores = score_ranges(pack, [reference(doc)], {doc.doc_id: doc})
        self.assertEqual(scores["retained_spans"], 1)
        self.assertEqual(scores["retained_conditions"], 2)
        self.assertEqual(pack["diagnostics"]["unmapped_chunks"], 0)

    def test_document_match_without_required_text_does_not_pass(self):
        doc = document()
        hit = hits_for(doc)[0]
        cut = hit.text.index("关键条件乙")
        budget = EvidenceBudget(max_chars_per_chunk=cut)
        pack = build_evidence_pack([hit], budget, SourceResolver([doc]))
        scores = score_ranges(pack, [reference(doc)], {doc.doc_id: doc})
        self.assertEqual(scores["retained_spans"], 1)
        self.assertEqual(scores["retained_conditions"], 1)
        self.assertTrue(pack["hits"][0]["content_truncated"])
        # The visible prefix contains no bytes from the second condition.
        self.assertNotIn("关键条件乙", pack["hits"][0]["text"])

    def test_forged_content_version_and_source_are_unmapped(self):
        doc = document()
        hit, resolver = hits_for(doc)[0], SourceResolver([doc])
        for changes in ({"text": hit.text+"伪造"}, {"document_version": 2},
                        {"source_sha256": "1"*64}, {"source_url": "https://evil.invalid/"},
                        {"chunk_id": "unknown"}):
            with self.subTest(changes=changes):
                pack = build_evidence_pack([hit.model_copy(update=changes)], resolver=resolver)
                self.assertEqual(pack["hits"][0]["source_mapping"]["status"], "unmapped")
                self.assertEqual(score_ranges(pack, [reference(doc)], resolver.documents)["retained_spans"], 0)

    def test_ambiguous_repeated_section_does_not_guess_offsets(self):
        doc = document(body="# 第一节\n完全相同的句子。\n# 第二节\n完全相同的句子。")
        pack = build_evidence_pack(hits_for(doc), resolver=SourceResolver([doc]))
        self.assertEqual(pack["diagnostics"]["unmapped_chunks"], 2)

    def test_generated_heading_is_not_counted_as_body_evidence(self):
        doc = document()
        hit = hits_for(doc)[0]
        pack = build_evidence_pack([hit], EvidenceBudget(max_chars_per_chunk=len(doc.title)), SourceResolver([doc]))
        self.assertEqual(pack["hits"][0]["source_mapping"]["ranges"], [])

    def test_real_section_heading_can_preserve_source_scope(self):
        doc = document(body="# 仅适用于流感\n明确结论。关键条件甲。关键条件乙。")
        hit = hits_for(doc)[0]
        pack = build_evidence_pack([hit], resolver=SourceResolver([doc]))
        start = doc.body.index("仅适用于流感")
        ref = {**reference(doc), "required_conditions": [[start, start+len("仅适用于流感")]]}
        self.assertEqual(score_ranges(pack, [ref], {doc.doc_id: doc})["retained_conditions"], 1)

    def test_chunk_doc_and_content_budgets_are_deterministic(self):
        docs = [document(str(i), "# 章节\n"+"同一主题句子。"*120) for i in range(3)]
        hits = [hit for doc in docs for hit in hits_for(doc)]
        resolver = SourceResolver(docs)
        budget = EvidenceBudget(max_chunks=5, max_content_chars=100, max_chars_per_chunk=70)
        pack = build_evidence_pack([hits[0], hits[0]]+hits[1:], budget, resolver)
        self.assertEqual(pack["diagnostics"]["content_chars"], 100)
        self.assertEqual(pack["diagnostics"]["omissions"]["duplicate_chunk"], 1)
        self.assertEqual(pack["pack_sha256"], build_evidence_pack([hits[0], hits[0]]+hits[1:], budget, resolver)["pack_sha256"])
        self.assertNotEqual(pack["pack_sha256"], build_evidence_pack(hits, EvidenceBudget(max_content_chars=90), resolver)["pack_sha256"])

    def test_per_document_cap_and_single_chunk_request(self):
        doc = document(body="# 章节\n"+"合成句子。"*240)
        pack = build_evidence_pack(hits_for(doc), resolver=SourceResolver([doc]))
        self.assertEqual(pack["diagnostics"]["selected_chunks"], 2)
        one = build_evidence_pack(hits_for(doc), EvidenceBudget(max_chunks=1), SourceResolver([doc]))
        self.assertEqual(len(one["hits"]), 1)

    def test_empty_pack_never_loads_corpus_and_has_no_perfect_metrics(self):
        with patch("medical.evidence_contract.default_resolver", side_effect=AssertionError("must not load")):
            self.assertEqual(build_evidence_pack([])["hits"], [])
        result = evaluate_evidence(Search([]), [{"id": "negative", "kind": "unanswerable", "query": "测试"}], [])
        self.assertIsNone(result["evidence_span_recall_at_budget"])
        self.assertIsNone(result["critical_condition_retention"])

    def test_five_documents_cannot_replace_five_actual_chunks(self):
        docs = [document(did, "# 章节\n"+did+"合成句子。"*120) for did in ("A", "B", "C", "D", "E")]
        hits = hits_for(docs[0])[:2]+[hits_for(doc)[0] for doc in docs[1:]]
        case = {"id": "budget", "query": "合成检索问题", "expected_doc_ids": ["E"]}
        old = evaluate(Search(hits), [case], 5)
        search = Search(hits)
        current = evaluate_evidence(search, [case], docs)
        self.assertEqual(old["recall_at_5"], 1)
        self.assertEqual(current["document_recall_at_budget"], 0)
        self.assertEqual(search.limit, 5)

    def test_errors_are_not_successful_rejections_or_removed_from_denominator(self):
        doc = document()
        cases = [{"id": "positive", "query": "合成问题", "expected_doc_ids": ["A"], "expected_evidence": [reference(doc)]},
                 {"id": "negative", "query": "不存在的资料", "kind": "unanswerable"}]
        result = evaluate_evidence(Search([], broken=True), cases, [doc])
        self.assertEqual(result["error_cases"], 2)
        self.assertEqual(result["document_recall_at_budget"], 0)
        self.assertEqual(result["evidence_span_recall_at_budget"], 0)
        self.assertEqual(result["unanswerable_rejection_rate"], 0)

    def test_label_snapshot_and_ranges_fail_before_search(self):
        doc = document()
        case = {"id": "bad", "query": "合成问题", "expected_doc_ids": ["A"], "expected_evidence": [reference(doc)]}
        for change in ({"body_sha256": "wrong"}, {"version": True}, {"ranges": [[-1, 4]]}, {"ranges": [[0, 99999]]}, {"ranges": []}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_references([{**case, "expected_evidence": [{**reference(doc), **change}]}], [doc])
        with self.assertRaises(ValueError):
            validate_cases([{**case, "kind": "unanswerable"}])

    def test_tool_and_evaluator_send_identical_pack(self):
        doc = document()
        hits = hits_for(doc)
        spec = importlib.util.spec_from_file_location("evidence_medical_tools", MEDICAL.parent / "mcp-serve/medical_tools.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        class Capture:
            def tool(self, function): self.search = function; return function
        capture = Capture()
        module.register_medical_tools(capture)
        with patch.object(module, "search_with_metrics", return_value=hits), patch.object(module, "last_search_metrics", return_value={}), patch("medical.evidence_contract.default_resolver", return_value=SourceResolver([doc])):
            actual = json.loads(capture.search("合成健康问题"))
        result = evaluate_evidence(Search(hits), [{"id": "same", "query": "合成健康问题", "expected_doc_ids": ["A"]}], [doc])
        self.assertEqual({**actual["evidence"], "hits": actual["hits"]}, result["details"][0]["evidence_pack"])

    def test_preflight_failure_is_saved_and_existing_result_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/"failure.json"
            with self.assertRaises(ValueError):
                run_experiment(MEDICAL/"evaluation/suite_v3.json", MEDICAL/"source_corpus", out, profiles=["unknown"])
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(report["complete"])
            self.assertEqual(report["stage"], "preflight")
            previous = out.read_bytes()
            with self.assertRaises(FileExistsError):
                run_experiment(MEDICAL/"evaluation/suite_v3.json", MEDICAL/"source_corpus", out)
            self.assertEqual(out.read_bytes(), previous)

    def test_resource_guard_failure_is_structured_before_model_load(self):
        from medical.resource_budget import MemoryBudgetError
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/"memory.json"
            with patch("medical.resource_budget.require_available", side_effect=MemoryBudgetError("injected")), self.assertRaises(MemoryBudgetError):
                run_experiment(MEDICAL/"evaluation/suite_v3.json", MEDICAL/"source_corpus", out, groups=["chinese-symptoms"])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["failure_type"], "MemoryBudgetError")

    def test_new_evidence_dataset_has_bound_ranges_and_frozen_hash(self):
        from medical.knowledge_base import load_corpus
        _, groups = load_suite(MEDICAL/"evaluation/suite_v4.json")
        cases = groups["evidence-regression"]
        self.assertEqual(len(cases), 24)
        self.assertEqual(sum(bool(c.get("expected_evidence")) for c in cases), 16)
        validate_references(cases, load_corpus(MEDICAL/"source_corpus"))

    def test_forbidden_sources_and_unknown_errors_are_not_silently_ignored(self):
        docs = [document("A"), document("B")]
        case = {"id": "forbidden", "query": "合成问题", "expected_doc_ids": ["A"], "forbidden_doc_ids": ["B"]}
        result = evaluate_evidence(Search(hits_for(docs[0])+hits_for(docs[1])), [case], docs)
        self.assertEqual(result["forbidden_hit_rate_at_budget"], 1)
        self.assertEqual(result["details"][0]["forbidden_retrieved"], ["B"])
        failed = evaluate_evidence(Search([], broken=True), [case], docs)
        self.assertIsNone(failed["forbidden_hit_rate_at_budget"])
        self.assertEqual(failed["forbidden_unverified_cases"], 1)


if __name__ == "__main__": unittest.main()
