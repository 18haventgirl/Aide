import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from agents.model_settings import ModelSettings

from agent.personal_assistant_manager import (
    PersonalAssistantContext,
    PersonalAssistantManager,
    _news_agent_failure_message,
)


class AgentCoordinationTests(unittest.TestCase):
    def test_triage_owns_multi_domain_requests_without_specialist_handoffs(self):
        manager = PersonalAssistantManager.__new__(PersonalAssistantManager)
        manager.model = "test-model"
        manager.model_settings = ModelSettings()
        manager._mcp_connected = False
        manager.agents = {}

        with redirect_stdout(StringIO()):
            manager._initialize_agents()

        triage = manager.agents["triage"]
        weather = manager.agents["weather"]
        news = manager.agents["news"]
        tool_names = {tool.name for tool in triage.tools}
        self.assertEqual(tool_names, {
            "consult_weather_agent", "consult_news_agent", "consult_recipe_agent",
        })
        self.assertEqual(weather.handoffs, [])
        self.assertEqual(news.handoffs, [])
        self.assertEqual(manager.agents["recipe"].handoffs, [])
        self.assertEqual(len(triage.handoffs), 5)
        self.assertEqual({agent.name for agent in triage.handoffs}, {
            "Weather Agent", "News Agent", "Recipe Agent",
            "Personal Assistant Agent", "Medical Health Agent",
        })

        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        context = SimpleNamespace(context=PersonalAssistantContext(
            user_id=1, user_name="测试用户", lat="Unknown", lng="Unknown",
            user_preferences={}, todos=[],
        ))
        triage_instructions = manager._get_triage_instructions(context, triage)
        weather_instructions = manager._get_weather_instructions(context, weather)
        tomorrow = (today + timedelta(days=1)).isoformat()
        self.assertIn(tomorrow, triage_instructions)
        self.assertIn(tomorrow, weather_instructions)
        self.assertIn("call each relevant consult_*_agent tool once", triage_instructions)
        self.assertIn("wait for every result", triage_instructions)
        self.assertNotIn("hand off to News Agent", weather_instructions)
        news_instructions = manager._get_news_instructions(context, news)
        self.assertNotIn("hand off to Weather Agent", news_instructions)
        self.assertIn("language='zh'", news_instructions)
        self.assertIn("limit at most 3", news_instructions)

    def test_nested_news_model_rejection_is_not_reported_as_news_api_failure(self):
        message = _news_agent_failure_message(
            None,
            RuntimeError("litellm.BadRequestError: OpenAIException - Content Exists Risk"),
        )
        self.assertIn("model provider's content policy", message)
        self.assertIn("does not mean the news API failed", message)
        self.assertNotIn("litellm", message)
        self.assertNotIn("Content Exists Risk", message)


if __name__ == "__main__":
    unittest.main()
