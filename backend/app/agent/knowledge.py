"""知识库 Agent：提示词构建 + 拒答判定（纯函数，无 IO，可单测）。"""

SYSTEM_PROMPT = """你是电商平台的客服知识助手。严格遵守：
1. 只能依据【知识片段】回答，禁止编造片段里没有的信息。
2. 引用来源时标注编号，如 [kb-001]。
3. 若知识片段不足以回答，只回复：抱歉，这个问题我需要转人工处理。
4. 回答控制在3句话以内。"""


def build_messages(question: str, chunks: list[dict],
                   system_prompt: str | None = None) -> list[dict]:
    """system_prompt：租户覆盖的人设模板（BYOK 提示词自定义），None = 平台默认。"""
    context = "\n\n".join(f"[{c['id']}] {c['title']}：{c['content']}" for c in chunks)
    return [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
        {"role": "user", "content": f"【知识片段】\n{context}\n\n【顾客问题】\n{question}"},
    ]


def is_refusal(answer: str) -> bool:
    return "转人工" in answer