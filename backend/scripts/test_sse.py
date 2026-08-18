import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000"


def ask(client: httpx.Client, session_id: str, question: str):
    print(f"\n{'=' * 50}\n问题: {question}")
    start = time.time()
    with client.stream("POST", f"{BASE}/api/chat/sessions/{session_id}/messages/stream",
                       json={"content": question}) as resp:
        event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event = line[len("event: "):]
                if event != "message_delta":
                    print(f"\n[{time.time() - start:5.2f}s] {event}")
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if event == "message_delta":
                    print(data["delta"], end="", flush=True)
                else:
                    print(f"          {json.dumps(data, ensure_ascii=False)[:120]}")


def main():
    with httpx.Client(timeout=120) as client:
        resp = client.post(f"{BASE}/api/chat/sessions", json={})
        resp.raise_for_status()
        session_id = resp.json()["id"]
        print(f"新会话: {session_id}")

        ask(client, session_id, "退货政策是什么")   # 走 knowledge：大量 delta
        ask(client, session_id, "帮我查下天气")     # 走拒答：单帧 delta
        print("\n--- 全部流结束 ---")


if __name__ == "__main__":
    main()
