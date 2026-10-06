"""Invoke real SDK FunctionTools with disposable storage and trusted contexts."""
import asyncio
from datetime import datetime
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agents import RunContextWrapper
from agents.tool_context import ToolContext
from agent.health_tools import health_create_record, health_get_records, health_update_record, health_function_tools
from agent.personal_assistant_manager import PersonalAssistantContext, PersonalAssistantManager
from agent.agent_session import AgentSession
from tests import test_health_memory as storage_tests


class HealthAgentToolTests(unittest.TestCase):
    # Reuse storage setup only, without inheriting its test methods.
    setUp = storage_tests.HealthMemoryTests.setUp
    tearDown = storage_tests.HealthMemoryTests.tearDown
    count = storage_tests.HealthMemoryTests.count
    def context(self, user=1, message="41", conversation="conversation-a"):
        return RunContextWrapper(context=PersonalAssistantContext(user_id=user, user_name="合成用户",
            lat="Unknown", lng="Unknown", user_preferences={}, todos=[], conversation_id=conversation,
            health_message_id=message, health_reference_at=datetime(2026, 10, 6, 20)))

    def invoke(self, tool, context, arguments):
        raw = json.dumps(arguments, ensure_ascii=False)
        runtime = ToolContext.from_agent_context(context, tool_call_id="synthetic-call",
                                              tool_name=tool.name, tool_arguments=raw)
        with patch("agent.health_tools._service", return_value=self.service):
            return json.loads(asyncio.run(tool.on_invoke_tool(runtime, raw)))

    def test_schema_never_accepts_model_identity_or_provenance(self):
        forbidden = {"user_id", "source_conversation_id", "source_message_id", "idempotency_key"}
        for tool in health_function_tools():
            self.assertFalse(forbidden.intersection(tool.params_json_schema["properties"]))

    def test_same_message_retry_and_distinct_message(self):
        arguments = {"record_type": "symptom", "title": "合成头痛", "date_text": "昨天", "event_index": 0}
        first = self.invoke(health_create_record, self.context(), arguments)
        retry = self.invoke(health_create_record, self.context(), arguments)
        next_message = self.invoke(health_create_record, self.context(message="42"), arguments)
        self.assertTrue(first["success"])
        self.assertEqual(first["record"]["id"], retry["record"]["id"])
        self.assertNotEqual(first["record"]["id"], next_message["record"]["id"])
        self.assertEqual(first["record"]["source_message_id"], "41")
        self.assertEqual(first["record"]["source_conversation_id"], "conversation-a")
        self.assertEqual(first["record"]["observed_at"], "2026-10-05T00:00:00")

    def test_reads_use_current_user_across_conversations(self):
        self.service.create_record(1, **self.facts)
        self.service.create_record(2, **self.facts)
        result = self.invoke(health_get_records, self.context(conversation="conversation-b"), {})
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["user_id"], 1)

    def test_missing_trusted_message_cannot_write(self):
        result = self.invoke(health_create_record, self.context(message=None), {"record_type": "symptom", "title": "合成头痛"})
        self.assertFalse(result["success"])
        self.assertEqual(self.count(), (0, 0))

    def test_tool_correction_does_not_overwrite_another_user(self):
        record = self.service.create_record(2, **self.facts)
        result = self.invoke(health_update_record, self.context(), {"record_id": record.id, "summary": "错误用户"})
        self.assertEqual(result["error"], "not_found")
        self.assertEqual(self.service.get_record(2, record.id).summary, "合成测试")

    def test_context_provenance_excluded_from_serialized_model_view(self):
        context = self.context().context
        self.assertNotIn("health_message_id", context.model_dump())
        self.assertNotIn("health_reference_at", context.model_dump())
        other = context.model_copy(deep=True)
        other.health_message_id = "another-message"
        self.assertEqual(context.health_message_id, "41")

    def test_old_mcp_health_tools_are_filtered_out(self):
        manager = PersonalAssistantManager.__new__(PersonalAssistantManager)
        filter_context = SimpleNamespace(agent=SimpleNamespace(name="Medical Health Agent"))
        self.assertFalse(manager._tool_filter(filter_context, SimpleNamespace(name="health_create_record")))
        self.assertTrue(manager._tool_filter(filter_context, SimpleNamespace(name="medical_search")))

    def test_session_rejects_foreign_conversation_before_loading_history(self):
        session = AgentSession.__new__(AgentSession)
        session._closed = True
        session.db_client = SimpleNamespace(_initialized=True)
        session.user_id = 2
        session.conversation_id_str = "foreign"
        session.conversation_service = Mock()
        session.conversation_service.get_conversation_by_id_str.return_value = SimpleNamespace(user_id=1)
        session._load_messages_to_cache = AsyncMock()
        self.assertFalse(asyncio.run(session.initialize()))
        session._load_messages_to_cache.assert_not_awaited()

    def test_saved_message_id_comes_from_storage(self):
        session = AgentSession.__new__(AgentSession)
        session._closed = True
        session._initialized = True
        session.conversation_id_str = "owned"
        session.chat_message_service = Mock()
        session.chat_message_service.create_message_by_id_str.return_value = SimpleNamespace(id=77)
        session._message_cache = []
        session._state = {"input_items": []}
        session.max_messages = 100
        self.assertTrue(asyncio.run(session.save_message("合成事实", "user")))
        self.assertEqual(session.last_saved_user_message_id, "77")


if __name__ == "__main__":
    unittest.main()
