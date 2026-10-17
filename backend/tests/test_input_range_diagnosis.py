import unittest

from medical.diagnose_input_ranges import pool_pack, retained_label_ids
from medical.evaluation.metrics import score_ranges
from medical.source_provenance import SourceResolver
from tests.test_evidence_contract import document, hits_for, reference
from tests.test_token_budget import chunker


class PoolRangeTests(unittest.TestCase):
    def test_equal_counts_cannot_hide_a_switch_between_two_conditions(self):
        doc = document()
        ref = reference(doc)
        def pack(span):
            from medical.source_provenance import body_hash
            return {"hits": [{"doc_id": doc.doc_id, "source_mapping": {"status": "verified_offsets",
                "document_version": doc.version, "body_sha256": body_hash(doc.body), "ranges": [span]}}]}
        a = retained_label_ids(pack(ref["required_conditions"][0]), [ref], {doc.doc_id: doc})
        b = retained_label_ids(pack(ref["required_conditions"][1]), [ref], {doc.doc_id: doc})
        self.assertEqual(len(a), len(b))
        self.assertNotEqual(a, b)
        self.assertEqual(len(a-b), 1)

    def test_correct_document_id_alone_is_not_a_source_range_match(self):
        doc = document()
        resolver = SourceResolver([doc])
        pack, unknown = pool_pack([{"doc_id": "A", "chunk_id": "not-a-real-chunk"}], resolver)
        self.assertEqual(len(unknown), 1)
        self.assertEqual(score_ranges(pack, [reference(doc)], resolver.documents)["retained_spans"], 0)

    def test_legacy_and_native_pools_both_resolve_the_real_ranked_text(self):
        doc = document()
        old = hits_for(doc)[0]
        maker = chunker()
        new = maker.chunks(doc)[0]
        for cid, resolver in ((old.chunk_id, SourceResolver([doc])), (new.chunk_id, SourceResolver([doc], maker))):
            pack, unknown = pool_pack([{"doc_id": "A", "chunk_id": cid}], resolver)
            self.assertEqual(unknown, [])
            scores = score_ranges(pack, [reference(doc)], resolver.documents)
            self.assertEqual(scores["retained_spans"], 1)
            self.assertEqual(scores["retained_conditions"], 2)


if __name__ == "__main__": unittest.main()
