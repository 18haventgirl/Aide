import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from agents.model_settings import ModelSettings

from agent.personal_assistant_manager import PersonalAssistantContext, PersonalAssistantManager


class AgentCoordinationTests(unittest.TestCase):
    def test_weather_and_news_can_both_serve_one_request(self):
        manager = PersonalAssistantManager.__new__(PersonalAssistantManager)
        manager.model = "test-model"
        manager.model_settings = ModelSettings()
        manager._mcp_connected = False
        manager.agents = {}

        with redirect_stdout(StringIO()):
            manager._initialize_agents()
            manager._setup_agent_relationships()
            manager._setup_agent_relationships()

        triage = manager.agents["triage"]
        weather = manager.agents["weather"]
        news = manager.agents["news"]
        tool_names = {tool.name for tool in triage.tools}
        self.assertIn("consult_weather_agent", tool_names)
        self.assertIn("consult_news_agent", tool_names)
        self.assertEqual(weather.handoffs.count(news), 1)
        self.assertEqual(news.handoffs.count(weather), 1)

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


if __name__ == "__main__":
    unittest.main()
