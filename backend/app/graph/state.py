from typing import TypedDict


class AgentState(TypedDict):
    question: str            # 本轮顾客问题
    history: list[dict]      # 对话历史 [{"role": "customer", "content": "..."}]
    intent: str | None       # triage 输出: faq | unknown
    chunks: list[dict]       # 知识库检索结果
    answer: str | None       # 最终回答
    refused: bool            # 是否拒答（触发拒答 = 以后要转人工）
    steps: list[str]         # 执行轨迹（agent_runs 表的雏形）