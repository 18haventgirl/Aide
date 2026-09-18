"""Manual local Aide medical-mode smoke test; never prints authentication tokens."""

import asyncio
import json
import os
from urllib.parse import urlencode

import httpx
import websockets


async def main() -> None:
    password = os.getenv("AIDE_TEST_PASSWORD")
    if not password:
        raise SystemExit("Set AIDE_TEST_PASSWORD for the local test account")
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=15) as client:
        response = await client.post("/api/auth/login", json={"username": "admin", "password": password})
        response.raise_for_status()
        data = response.json()["data"]
        token = data["access_token"]
        user_id = str(data["user_info"]["user_id"])
    url = "ws://127.0.0.1:8000/ws?" + urlencode({"user_id": user_id, "token": token})
    async with websockets.connect(url, max_size=2**20) as socket:
        await asyncio.wait_for(socket.recv(), 10)  # authenticated welcome
        for query in ("吃得清淡是不是只要少放盐？", "感冒时一定要输液才好得快吗？",
                      "胸口疼还冒冷汗，怎么处理？", "我这份胃镜报告能确诊胃癌吗？",
                      "明天杭州天气怎么样？"):
            await socket.send(json.dumps({"type": "chat", "content": query, "metadata": {"mode": "medical"}}, ensure_ascii=False))
            for _ in range(30):
                event = json.loads(await asyncio.wait_for(socket.recv(), 60))
                if event.get("type") == "ai_response" and event.get("content", {}).get("type") == "completion":
                    result = event["content"]["final_response"]
                    print(json.dumps({
                        "query": query, "status": result.get("knowledge_status"),
                        "answer": result.get("raw_response"),
                        "citations": [(c["evidence_id"], c["doc_id"]) for c in result.get("citations", [])],
                    }, ensure_ascii=True))
                    break
            else:
                raise RuntimeError("no medical completion received")


if __name__ == "__main__":
    asyncio.run(main())
