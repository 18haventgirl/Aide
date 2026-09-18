"""Medical answer validation at the boundary between the model and the UI."""

import asyncio
import json
import unittest
from types import SimpleNamespace

from medical.answering import MedicalModelUnavailable, answer_with_evidence
from medical.chat import contextual_query
from medical.schema import MedicalHit


class FakeCompletions:
    def __init__(self, draft):
        self.draft = draft

    async def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=json.dumps(self.draft))
        )])


def fake_client(draft):
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(draft)))


def hit(doc_id):
    return MedicalHit(
        chunk_id=f"{doc_id}-1", doc_id=doc_id, title=f"来源{doc_id}", section_path="第一节",
        text="清淡饮食应少盐、少油、少糖。", source_org="官方来源",
        source_url=f"https://example.org/{doc_id}",
    )


class MedicalAnsweringTests(unittest.TestCase):
    def test_short_followup_uses_previous_user_question_only(self):
        query = contextual_query("那需要去医院吗？", [
            {"role": "user", "content": "咳嗽两个多星期了"},
            {"role": "assistant", "content": "上一轮回答不应成为检索证据"},
        ])
        self.assertIn("咳嗽两个多星期了", query)
        self.assertNotIn("上一轮回答", query)

    def test_only_used_evidence_is_shown(self):
        draft = {"status": "answered", "statements": [
            {"text": "清淡饮食不只是少盐。", "evidence_ids": ["E1"]},
        ]}
        result = asyncio.run(answer_with_evidence("清淡饮食是什么？", [hit("A"), hit("B")], client=fake_client(draft)))
        self.assertEqual(result.status, "evidence_cited")
        self.assertEqual([source["doc_id"] for source in result.citations], ["A"])
        self.assertIn("[E1]", result.text)
        self.assertNotIn("来源B", result.text)

    def test_unknown_evidence_fails_closed(self):
        draft = {"status": "answered", "statements": [
            {"text": "可以自行停药。", "evidence_ids": ["E99"]},
        ]}
        with self.assertRaises(MedicalModelUnavailable):
            asyncio.run(answer_with_evidence("能停药吗？", [hit("A")], client=fake_client(draft)))

    def test_insufficient_answer_has_no_source_claim(self):
        draft = {"status": "insufficient", "statements": []}
        result = asyncio.run(answer_with_evidence("超出范围", [hit("A")], client=fake_client(draft)))
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.citations, [])


if __name__ == "__main__":
    unittest.main()
