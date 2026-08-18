import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.llm import chat_stream

print("开始流式输出：", flush=True)
for token in chat_stream([{"role": "user", "content": "用一句话介绍你自己"}]):
    print(token, end="", flush=True)
print("\n--- 流式完成 ---")
