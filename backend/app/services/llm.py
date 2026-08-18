from openai import OpenAI

from app.core.config import settings

client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.3) -> str:
    """调用 LLM，返回纯文本回复。"""
    resp = client.chat.completions.create(
        model=model or settings.llm_model,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content

def chat_stream(messages: list[dict], model: str | None = None, temperature: float = 0.3):
    """流式版本：LLM 生成一点就吐一点（生成器，逐块 yield）。"""
    resp = client.chat.completions.create(
        model=model or settings.llm_model,
        messages=messages,
        temperature=temperature,
        stream=True,
    )
    for chunk in resp:
        delta = chunk.choices[0].delta.content
        if delta:  # 有些 chunk 只有角色信息没有内容，跳过
            yield delta