"""临时探针：走真实 HTTP + WebSocket 验证新引擎的完整会话（不提交）"""

import asyncio
import json
import os
import sys
import time
from urllib.request import Request, urlopen

import websockets

API = os.getenv("PROBE_API", "http://127.0.0.1:8100/api")
WS = os.getenv("PROBE_WS", "ws://127.0.0.1:8100/ws")


def _post(path, payload):
    request = Request(API + path, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


async def _turn(ws, text, seen, timeout=180):
    # 与前端 lib/websocket.ts 一致：conversation_id 走 metadata，不走 URL 参数
    await ws.send(json.dumps({"type": "chat", "content": text,
                              "conversation_id": CONVERSATION,
                              "metadata": {"conversation_id": CONVERSATION},
                              "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
        data = json.loads(raw)
        content = data.get("content")
        if not isinstance(content, dict):
            continue
        kind = content.get("type") or ("completion" if content.get("is_finished") else "snapshot")
        seen[kind] = seen.get(kind, 0) + 1
        if kind == "delta":
            seen["delta_text"] = seen.get("delta_text", "") + content.get("delta", "")
        elif kind in ("tool_call", "tool_output"):
            seen.setdefault("tools", []).append(
                f"{kind}:{content.get('tool')} args={content.get('arguments', '')}"[:150])
        elif kind == "node_update":
            seen.setdefault("nodes", []).append(f"{content.get('node')}/{content.get('status')}")
        elif kind == "tools_list":
            seen["agent_tools"] = [a["name"] for a in content.get("agents", [])]
            seen["tool_count"] = len(content.get("tools", []))
        if content.get("type") == "completion" or content.get("is_finished"):
            final = content.get("final_response", content)
            return {
                "note": content.get("message"),
                "text": final.get("raw_response", ""),
                "is_error": final.get("is_error"),
                "error_message": final.get("error_message", ""),
                "current_agent": final.get("current_agent"),
                "events": [e.get("type") for e in final.get("events", [])],
                "guardrails": [(g.get("name"), g.get("passed"), g.get("reasoning", "")[:30])
                               for g in final.get("guardrails", [])],
                "tool_names": [t.get("name") for t in final.get("tools", [])][:5],
                "context": final.get("context"),
            }
    raise AssertionError("等待 completion 超时")


async def main():
    stamp = int(time.time())
    account = _post("/auth/register", {
        "username": f"lgprobe{stamp}", "email": f"lgprobe{stamp}@example.com",
        "password": "Probe-12345", "name": "探针用户"})
    if not account.get("success"):
        raise AssertionError(f"注册失败：{account}")
    token = account["data"]["access_token"]
    info = account["data"]["user_info"]
    user_id = str(info.get("user_id") or info.get("id"))
    print(f"USER id={user_id} info={json.dumps(info, ensure_ascii=False)[:160]}")

    global CONVERSATION
    CONVERSATION = f"probe-{stamp}"
    conversation = CONVERSATION
    url = f"{WS}?user_id={user_id}&username=lgprobe{stamp}&token={token}&conversation_id={conversation}"
    seen = {}
    async with websockets.connect(url, max_size=20_000_000) as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
        print("HANDSHAKE:", hello.get("content") if isinstance(hello.get("content"), str)
              else hello.get("type"))

        first = await _turn(ws, "你好，我叫小林，在广州做安卓开发。请记住这些。", seen)
        print("TURN1:", json.dumps({k: v for k, v in first.items() if k != "context"},
                                   ensure_ascii=False)[:500])

        second = await _turn(ws, "我叫什么名字？在哪个城市做什么工作？", seen)
        print("TURN2:", json.dumps({k: v for k, v in second.items() if k != "context"},
                                   ensure_ascii=False)[:500])

        third = await _turn(ws, "明天广州天气怎么样？", seen)
        print("TURN3:", json.dumps({k: v for k, v in third.items() if k != "context"},
                                   ensure_ascii=False)[:500])

    print("FRAMES:", json.dumps({k: v for k, v in seen.items()
                                 if k not in ("delta_text", "nodes", "tools")}, ensure_ascii=False))
    print("NODES:", " | ".join(seen.get("nodes", [])[:14]))
    print("TOOLS:", " | ".join(seen.get("tools", [])[:6]))
    print("STREAMED_CHARS:", len(seen.get("delta_text", "")))

    ok = (not first["is_error"] and not second["is_error"] and not third["is_error"]
          and "小林" in second["text"] and "广州" in second["text"]
          and seen.get("delta", 0) > 3 and seen.get("completion") == 3
          and any("weather" in t for t in seen.get("tools", [])))
    print("VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
