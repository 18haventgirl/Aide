"""Guard risk language and keep offline queries aligned with the MCP tool."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from medical.chat import is_urgent
from medical.evaluate import evaluate, QUERY_CONTRACT


class QueryContractTests(unittest.TestCase):
    def test_emergency_word_order_and_colloquial_variants(self):
        questions = [
            "刚才讲话含糊，一只胳膊抬不起来，脸也歪了。",
            "这次头痛突然特别剧烈，比以前都严重，而且一直吐。",
            "我突然头疼得很剧烈，还反复吐。",
            "言语突然不清楚，口角歪斜。",
            "右臂突然使不上劲了。",
            "胸口压着疼，冷汗不停地冒，气不够用。",
            "呼吸越来越困难，现在连一句完整的话都说不出来。",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_urgent(question))

    def test_explicit_denials_and_mild_history_do_not_match(self):
        questions = [
            "我没有胸痛，也没有冷汗。",
            "胸口不痛，只是有一点出汗。",
            "没有呼吸困难，跑步后有点累。",
            "我不想自杀，我想了解心理健康。",
            "脸没有歪，讲话没有含糊，手臂没有无力。",
            "小时候偶尔头痛，今天没有呕吐，也没有呼吸困难。",
            "今天普通头痛有点想吐，没有突然剧烈的头痛。",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertFalse(is_urgent(question))

    def test_negated_symptom_does_not_hide_other_positive_signals(self):
        self.assertTrue(is_urgent("没有胸痛，但是呼吸困难。"))
        self.assertTrue(is_urgent("我没有呕吐，突然说话不清，右臂无力。"))

    def test_offline_queries_match_tool_explicit_facts_and_bounds(self):
        spec = importlib.util.spec_from_file_location(
            "query_contract_medical_tools", Path(__file__).resolve().parents[1] / "mcp-serve/medical_tools.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class Capture:
            def tool(self, function):
                self.search = function
                return function

        class Search:
            def search(self, query, limit=20):
                self.query = query
                return []

        capture = Capture()
        module.register_medical_tools(capture)
        questions = [("已经吸了很多年，现在还有收益吗？", "我在问专业戒烟服务。"),
                     ("原来的瓶子要留着吗？", "我在看家庭常备药的保存注意事项。"),
                     ("那吃完饭呢？", "我在问活动假牙的清洁。"),
                     ("饮水\n健康" * 250, "用户事实" * 200)]
        for question, facts in questions:
            search = Search()
            result = evaluate(search, [{"id": "contract", "kind": "followup", "query": question,
                                       "history": facts, "expected_doc_ids": ["A"]}], 5)
            with patch.object(module, "search_with_metrics", return_value=[]) as actual_search:
                tool_result = json.loads(capture.search(question, prior_user_facts=facts))
            self.assertEqual(result["query_contract"], QUERY_CONTRACT)
            self.assertEqual(actual_search.call_args.args[0], search.query)
            self.assertLessEqual(len(search.query), 1000)
            self.assertEqual(tool_result["knowledge_status"], "not_covered")

    def test_scope_gate_uses_full_input_before_search_truncation(self):
        question = "一般健康问题" * 300 + "帮我看这张检查单是不是患病了"
        class Search:
            def search(self, query, limit=20):
                raise AssertionError("clinical decision must be gated before truncating")
        result = evaluate(Search(), [{"id": "long-clinical", "kind": "unanswerable", "query": question}], 5)
        self.assertEqual(result["unanswerable_rejection_rate"], 1)


if __name__ == "__main__":
    unittest.main()
