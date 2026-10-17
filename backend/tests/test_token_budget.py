"""Source visibility, long follow-ups and structured chunk regression tests.

The small tokenizer below makes offset/length edge cases deterministic. Real
pinned BGE tokenizer/model runs are separately archived by medical.experiment.
"""
import unittest

from medical.chat import clip_retrieval_query, contextual_facts_query, is_out_of_scope
from medical.evidence_contract import build_evidence_pack
from medical.evaluation.evidence import evaluate_evidence
from medical.source_provenance import SourceResolver
from medical.token_budget import PairBudget, prepare_pair
from medical.token_chunking import TokenChunker
from tests.test_evidence_contract import document, reference
from medical.schema import MedicalHit


class Encoded(dict):
    def sequence_ids(self): return self.sequences


class CharacterTokenizer:
    """Transparent unit fixture, NOT an embedding model or a quality baseline."""
    def __call__(self, text, pair=None, *, add_special_tokens=True, truncation=False,
                 return_offsets_mapping=False, max_length=None, **kwargs):
        ids, offsets = [], []
        for i, char in enumerate(text):
            if not char.isspace(): ids.append(ord(char)); offsets.append((i, i+1))
        if pair is None:
            row = Encoded(input_ids=ids)
            if return_offsets_mapping: row["offset_mapping"] = offsets
            return row
        second = self(pair, add_special_tokens=False, return_offsets_mapping=True)
        pids, poffsets = second["input_ids"], second["offset_mapping"]
        if truncation:
            while len(ids)+len(pids)+4 > max_length:
                if len(ids) > len(pids): ids.pop(); offsets.pop()
                else: pids.pop(); poffsets.pop()
        row = Encoded(self.prepare_for_model(ids, pids))
        row.sequences = [None]+[0]*len(ids)+[None, None]+[1]*len(pids)+[None]
        if return_offsets_mapping:
            row["offset_mapping"] = [(0, 0)]+offsets+[(0, 0)]*2+poffsets+[(0, 0)]
        return row

    def num_special_tokens_to_add(self, pair=False): return 4 if pair else 2

    def prepare_for_model(self, ids, pair_ids=None, **kwargs):
        combined = [0]+ids+[2]+([2]+pair_ids+[2] if pair_ids is not None else [])
        return {"input_ids": combined, "attention_mask": [1]*len(combined)}


def chunker(**kwargs):
    return TokenChunker(CharacterTokenizer(), tokenizer_sha256="fixture-not-model", **kwargs)


def hit_for(doc, chunk, expand=True):
    return MedicalHit(chunk_id=chunk.chunk_id, doc_id=doc.doc_id, title=doc.title,
                      section_path=chunk.section_path, text=chunk.context if expand else chunk.text,
                      source_org=doc.source_org, source_url=str(doc.source_url), source_sha256=doc.source_sha256,
                      document_version=doc.version)


class TokenBudgetTests(unittest.TestCase):
    def test_current_question_is_visible_after_long_history(self):
        query = contextual_facts_query("那出现哪些变化需要就医？", "此前明确提过咽痛。"*50)
        _, old = prepare_pair(CharacterTokenizer(), query, "标题\n"+"资料。"*200, policy="legacy")
        _, new = prepare_pair(CharacterTokenizer(), query, "标题\n"+"资料。"*200)
        start = query.index("那出现")
        self.assertFalse(any(a <= start < b for a, b in old["query_ranges"]))
        self.assertTrue(any(a <= start and b == len(query) for a, b in new["query_ranges"]))
        self.assertFalse(new["current_question_truncated"])
        self.assertEqual(new["actual_pair_tokens"], 256)

    def test_huge_question_keeps_head_tail_and_reports_omission(self):
        query = "开头"+"中间"*300+"结尾"
        inputs, trace = prepare_pair(CharacterTokenizer(), query, "正文。")
        self.assertTrue(trace["current_question_truncated"])
        self.assertEqual(trace["query_ranges"][0][0], 0)
        self.assertEqual(trace["query_ranges"][-1][1], len(query))
        self.assertLessEqual(len(inputs["input_ids"]), 256)

    def test_title_cannot_evict_body_and_special_tokens_are_counted(self):
        _, trace = prepare_pair(CharacterTokenizer(), "问题", "长标题"*100+"\n明确结论。")
        self.assertEqual(trace["retained_title_tokens"], 32)
        self.assertEqual(trace["retained_body_tokens"], len("明确结论。"))
        self.assertEqual(trace["special_tokens"], 4)
        self.assertTrue(any(a >= 301 for a, b in trace["passage_ranges"]))

    def test_legacy_policy_is_exact_historical_tokenization(self):
        tokenizer = CharacterTokenizer()
        query, passage = "过去。"*100, "标题\n"+"内容。"*100
        inputs, _ = prepare_pair(tokenizer, query, passage, policy="legacy")
        raw = tokenizer(query, passage, truncation=True, max_length=256)
        self.assertEqual(inputs, raw)

    def test_transport_cap_preserves_current_question_and_scope_uses_full_text(self):
        question = "现在的问题"+"补充说明。"*150+"该如何观察？"
        original = contextual_facts_query(question, "我的降压药能停掉吗？"*100)
        self.assertTrue(is_out_of_scope(original))
        clipped = clip_retrieval_query(original)
        self.assertLessEqual(len(clipped), 1000)
        self.assertIn("该如何观察？", clipped)
        self.assertEqual(clip_retrieval_query("短问句"), "短问句")

    def test_invalid_token_budgets_fail_explicitly(self):
        for values in ({"max_length": 513}, {"max_length": True}, {"query_max_tokens": 250}, {"title_max_tokens": -1}):
            with self.subTest(values=values), self.assertRaises(ValueError): PairBudget(**values)


class TokenChunkTests(unittest.TestCase):
    def test_token_index_is_isolated_idempotent_and_expands_after_selection(self):
        import chromadb
        from medical.knowledge_base import MedicalKnowledgeBase, RESEARCH_COLLECTION_NAME
        from tests.test_medical_rag import ConstantEmbedding
        client = chromadb.EphemeralClient()
        maker = chunker(child_tokens=100, context_tokens=300)
        kb = MedicalKnowledgeBase(client, ConstantEmbedding(), "BAAI/bge-small-zh-v1.5-fixture",
                                  research_mode=True, chunker=maker)
        try:
            doc = document(body="# 章节\n"+"合成背景句子。"*50+"明确结论。关键条件甲。关键条件乙。")
            first = kb.sync([doc])
            second = kb.sync([doc])
            self.assertEqual(first["indexed_chunks"], second["indexed_chunks"])
            self.assertEqual(second["removed_chunks"], 0)
            self.assertNotEqual(kb.collection.name, RESEARCH_COLLECTION_NAME)
            hits = kb.search("合成问题")
            self.assertGreater(len(hits), 0)
            for hit in hits:
                self.assertEqual(hit.text, maker.records[(doc.doc_id, hit.chunk_id)].context)
            pack = build_evidence_pack(hits, resolver=SourceResolver([doc], maker))
            self.assertEqual(pack["diagnostics"]["unmapped_chunks"], 0)
        finally:
            client.delete_collection(kb.collection.name)

    def test_all_source_characters_survive_long_sentence_splitting(self):
        doc = document(body="# 长句\n"+"长句没有标点"*100+"。")
        maker = chunker(child_tokens=100, context_tokens=180)
        chunks = maker.chunks(doc)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(any(c.boundary_split for c in chunks))
        covered = {i for c in chunks for _, _, a, b in c.segments for i in range(a, b)}
        required = {i for i in range(doc.body.index("长句没有"), len(doc.body)) if not doc.body[i].isspace()}
        self.assertTrue(required.issubset(covered))
        self.assertTrue(all(maker.count(c.text) <= 100 for c in chunks))

    def test_no_cross_section_context_and_repeated_text_has_exact_offsets(self):
        doc = document(body="# 第一节\n相同句子。\n# 第二节\n相同句子。")
        maker = chunker()
        chunks = maker.chunks(doc)
        resolver = SourceResolver([doc], maker)
        self.assertEqual(len(chunks), 2)
        packs = [build_evidence_pack([hit_for(doc, c)], resolver=resolver) for c in chunks]
        ranges = [p["hits"][0]["source_mapping"]["ranges"] for p in packs]
        self.assertTrue(all(p["diagnostics"]["unmapped_chunks"] == 0 for p in packs))
        self.assertNotEqual(ranges[0], ranges[1])
        self.assertNotIn("第二节", chunks[0].context)

    def test_qa_question_retained_for_each_answer_child_across_blank_lines(self):
        doc = document(body="# 问答\n问：哪些情况需要就医？\n\n答："+"需要注意相关变化。"*40+"\n\n问：第二个问题？\n答：第二个回答。")
        maker = chunker(child_tokens=100, context_tokens=180)
        chunks = maker.chunks(doc)
        first = [c for c in chunks if "第二个" not in c.text]
        self.assertGreater(len(first), 1)
        self.assertTrue(all(c.kind == "qa" and "问：哪些情况需要就医？" in c.text for c in first))
        self.assertTrue(all("第二个" not in c.context for c in first))

    def test_table_row_keeps_real_header_and_its_source_mapping(self):
        doc = document(body="# 表格\n| 项目 | 数值 |\n| --- | --- |\n| 指标甲 | 12 |\n| 指标乙 | 24 |")
        maker = chunker()
        chunks = maker.chunks(doc)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(c.kind == "table" and "项目 | 数值" in c.text for c in chunks))
        self.assertNotIn("指标乙", chunks[0].context)
        pack = build_evidence_pack([hit_for(doc, c) for c in chunks], resolver=SourceResolver([doc], maker))
        self.assertEqual(pack["diagnostics"]["unmapped_chunks"], 0)

    def test_expanded_parent_retains_both_conditions_and_metadata_does_not_count(self):
        doc = document(body="# 章节\n"+"普通背景句子。"*30+"明确结论。关键条件甲。关键条件乙。")
        maker = chunker(child_tokens=100, context_tokens=350)
        chunks = maker.chunks(doc)
        chosen = next(c for c in chunks if "明确结论" in c.text)
        resolver = SourceResolver([doc], maker)
        pack = build_evidence_pack([hit_for(doc, chosen)], resolver=resolver)
        from medical.evaluation.metrics import score_ranges
        self.assertEqual(score_ranges(pack, [reference(doc)], resolver.documents)["retained_conditions"], 2)
        hit = hit_for(doc, chosen, expand=False)
        mapping = resolver.resolve_intervals(hit, [[0, len(doc.title)]])
        self.assertEqual(mapping["ranges"], [])

    def test_ids_include_chunk_configuration_and_document_version(self):
        doc = document()
        a, b = chunker(child_tokens=100), chunker(child_tokens=120)
        self.assertNotEqual(a.chunks(doc)[0].chunk_id, b.chunks(doc)[0].chunk_id)
        self.assertNotEqual(a.chunks(doc)[0].chunk_id, a.chunks(doc.model_copy(update={"version": 2}))[0].chunk_id)
        self.assertEqual(a.chunks(doc), a.chunks(doc))

    def test_real_heading_in_title_is_mapped_once_without_duplicating_it(self):
        doc = document(body="# 合成资料A\n明确结论。关键条件甲。关键条件乙。")
        maker = chunker()
        chunk = maker.chunks(doc)[0]
        self.assertEqual(chunk.text.count("合成资料A"), 1)
        resolver = SourceResolver([doc], maker)
        hit = hit_for(doc, chunk)
        mapping = resolver.resolve_intervals(hit, [[0, len(doc.title)]])
        self.assertEqual(mapping["ranges"], [[2, 2+len(doc.title)]])
        self.assertEqual(resolver.resolve(hit.model_copy(update={"section_path": "伪造章节"}), hit.text)["status"], "unmapped")

    def test_oversized_question_header_is_a_build_failure(self):
        doc = document(body="# 问答\n问："+"超长问题"*100+"\n答：内容。")
        with self.assertRaisesRegex(ValueError, "header exceeds"): chunker().chunks(doc)

    def test_model_visibility_is_not_confused_with_full_context(self):
        doc = document()
        maker = chunker()
        chunk = maker.chunks(doc)[0]
        hit = hit_for(doc, chunk, expand=False)
        cut = hit.text.index("明确结论")
        class Search:
            def search(self, query, limit=5): return [hit_for(doc, chunk)]
            def candidate_trace(self):
                return {"rerank_visibility": [{"hit": hit, "input": {"passage_ranges": [[0, cut]]}}]}
        case = {"id": "visibility", "query": "合成问题", "expected_doc_ids": [doc.doc_id], "expected_evidence": [reference(doc)]}
        result = evaluate_evidence(Search(), [case], [doc], resolver=SourceResolver([doc], maker))
        self.assertEqual(result["evidence_span_recall_at_budget"], 1)
        self.assertEqual(result["rerank_visible_span_recall"], 0)

    def test_requested_model_visibility_keeps_failed_cases_in_denominator(self):
        doc = document()
        class Broken:
            def search(self, *args, **kwargs): raise RuntimeError("injected")
        case = {"id": "broken-visible", "query": "合成问题", "expected_doc_ids": [doc.doc_id], "expected_evidence": [reference(doc)]}
        result = evaluate_evidence(Broken(), [case], [doc], measure_rerank_visibility=True)
        self.assertEqual(result["rerank_visible_span_recall"], 0)
        self.assertEqual(result["rerank_visible_condition_retention"], 0)
        self.assertEqual(result["unverified_rerank_visibility_cases"], 1)
        self.assertEqual(result["rerank_visibility_spans"], 1)


if __name__ == "__main__": unittest.main()
