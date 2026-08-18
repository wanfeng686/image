"""开发自检脚本：验证 LLM 连通性。在 backend/ 目录下运行: python scripts/test_llm.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 把 backend/ 加入搜索路径，否则 import 不到 app

from openai import OpenAI  # noqa: E402

from app.core.config import settings  # noqa: E402


def main():
    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    resp = client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": "你是电商客服助手，请用一句话做自我介绍。"}],
    )
    print("模型返回:", resp.choices[0].message.content)
    print("本次用量:", resp.usage)


if __name__ == "__main__":
    main()