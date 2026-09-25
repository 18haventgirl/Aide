"""MySQL 展示副本写入

对话真相在 checkpoint，这里只管"会话列表/历史页能看到什么"。计划里原本要新建
agent/history.py，实测发现 agent_session.save_message 已经在写 conversations/chat_messages
（探针跑完一轮，库里 3 human + 3 ai 齐全），再加一个 writer 只会双写。
所以本任务收敛为补真实缺口：被护栏拦下的回复，历史里要能看出它不是模型正常作答。
"""

import asyncio

from api.websocket_api import _concurrent_db_saver


class FakeSession:
    def __init__(self):
        self.saved = []

    async def save_message(self, content, role, sender_id=None, extra_data=None):
        self.saved.append((role, content, extra_data))
        return True


def _run_saver(items):
    session = FakeSession()
    queue = asyncio.Queue()

    async def drive():
        task = asyncio.create_task(_concurrent_db_saver(queue, session))
        for item in items:
            await queue.put(item)
        await queue.put(None)
        await task
        return session.saved

    return asyncio.run(drive())


def test_normal_turn_is_saved_as_plain_assistant_message():
    saved = _run_saver([("final_message", "上海明天多云", "model")])

    assert saved == [("assistant", "上海明天多云", None)]


def test_blocked_turn_marks_the_guardrail_source():
    saved = _run_saver([("final_message", "抱歉，这个请求超出了我的服务范围。", "guardrails")])

    assert saved[0][0] == "assistant"
    assert saved[0][2] == {"source": "guardrails"}


def test_stop_signal_writes_nothing_and_empty_text_is_skipped():
    assert _run_saver([]) == []
    assert _run_saver([("final_message", "", "model")]) == []


def test_save_failure_does_not_kill_the_saver():
    class ExplodingSession(FakeSession):
        async def save_message(self, *args, **kwargs):
            raise RuntimeError("MySQL 掉了")

    session = ExplodingSession()
    queue = asyncio.Queue()

    async def drive():
        task = asyncio.create_task(_concurrent_db_saver(queue, session))
        await queue.put(("final_message", "答案", "model"))
        await queue.put(("final_message", "第二条", "model"))
        await queue.put(None)
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(drive())      # 落库失败只记日志，不能把发送链路带崩、也不能卡死
