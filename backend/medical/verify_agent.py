"""Explicit live integration check, using synthetic questions and no user storage.

Uses the real agent instructions, shared LiteLLM model factory and retrieval tool.
Empty/unavailable cases inject tool failures to test generation continuity.
This is not a browser/WebSocket or clinical quality test.
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from .huatuo_lite import write_report
from .answer_audit import audit_answer


async def verify(output: Path):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if urlsplit(os.getenv("OPENAI_API_BASE_URL", "")).hostname != "api.deepseek.com":
        raise ValueError("this verification is scoped to the configured official DeepSeek endpoint")
    import torch
    torch.set_num_threads(2)
    from agents import Agent, Runner, RunContextWrapper, function_tool, set_tracing_disabled
    from agents.model_settings import ModelSettings
    from agent.personal_assistant_manager import PersonalAssistantContext, PersonalAssistantManager
    set_tracing_disabled(True)
    manager = PersonalAssistantManager.__new__(PersonalAssistantManager)
    model = manager._create_model()
    context = PersonalAssistantContext(user_id=0, user_name="离线验收", lat="Unknown", lng="Unknown",
                                       user_preferences={}, todos=[], conversation_id="synthetic-verification")
    path = Path(__file__).resolve().parents[1] / "mcp-serve" / "medical_tools.py"
    spec = importlib.util.spec_from_file_location("verification_medical_tools", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Capture:
        def tool(self, func):
            self.search = func
            return func

    capture = Capture()
    module.register_medical_tools(capture)
    report = {"scope": "agent_tool_model_integration_without_mcp_transport_or_ui", "cases": []}
    for scenario in ("grounded", "not_covered", "unavailable"):
        calls = []

        @function_tool
        async def medical_search(query: str, top_k: int = 5, prior_user_facts: str = "") -> str:
            """Search adult Chinese general health knowledge before answering."""
            if scenario == "grounded":
                payload = json.loads(await asyncio.to_thread(capture.search, query, top_k, "adult", "CN", prior_user_facts))
            else:
                payload = {"knowledge_status": scenario, "hits": [], "urgency": "routine", "scope": "general_health"}
            calls.append(payload)
            return json.dumps(payload, ensure_ascii=False)

        agent = Agent(name="Medical Health Agent", model=model, tools=[medical_search],
                      model_settings=ModelSettings(temperature=0.1, top_p=1.0),
                      instructions=manager._get_medical_instructions(RunContextWrapper(context=context), None))
        try:
            result = await asyncio.wait_for(Runner.run(agent, "成年人一周运动多长时间比较合适？", context=context, max_turns=5), 90)
            usage = result.context_wrapper.usage
            answer = str(result.final_output)
            passed = bool(calls and answer.strip() and usage.total_tokens > 0)
            if scenario == "grounded":
                passed = passed and any(c.get("knowledge_status") == "grounded" for c in calls)
                passed = passed and all(not h["doc_id"].startswith("HTL-") for c in calls for h in c.get("hits", []))
            report["cases"].append({"scenario": scenario, "passed": passed, "tool_calls": len(calls),
                                    "total_tokens": usage.total_tokens, "answer": answer,
                                    "quantity_audit": audit_answer(answer, [h for c in calls for h in c.get("hits", [])]),
                                    "retrieval_statuses": [c["knowledge_status"] for c in calls]})
        except Exception as error:
            report["cases"].append({"scenario": scenario, "passed": False, "error_type": type(error).__name__})
        write_report(output, report)
        print(json.dumps({k:v for k,v in report["cases"][-1].items() if k != "answer"}, ensure_ascii=False), flush=True)
    if not all(c["passed"] for c in report["cases"]):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True, help="makes billable calls to configured official DeepSeek")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(verify(args.output))
