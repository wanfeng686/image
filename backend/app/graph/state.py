from typing import Any, TypedDict


class AgentState(TypedDict):
    # ── 业务状态 ──
    question: str                 # 本轮顾客问题
    history: list[dict]           # 对话历史 [{"role": "customer", "content": "..."}]
    intent: str | None            # triage 输出: faq | order_query | refund | unknown
    chunks: list[dict]            # 知识库检索结果
    answer: str | None            # 最终回答
    refused: bool                 # 是否拒答（触发拒答 = 转人工）
    steps: list[str]              # 执行轨迹（同步更新 agent_runs）

    # ── W2 扩展 ──
    card: dict | None             # 结构化卡片（订单卡/退款卡）
    order_no: str | None          # 槽位：订单号
    sentiment: float | None       # triage 情绪分（1~5）
    session_status: str | None    # 节点要求变更的会话状态（waiting_approval 等）

    # ── 编排期注入（非业务状态：DB 会话、用户身份等运行时依赖）──
    db: Any                       # SQLAlchemy Session（由端点注入，节点共用一个事务）
    session_obj: Any              # ChatSession ORM 对象
    user_id: Any                  # 归属断言用
    message_id: Any               # 本轮顾客消息 id（agent_runs 关联）
