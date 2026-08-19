"""Triage 节点：LLM 分诊（意图+情绪+订单号槽位），失败关键词兜底。"""
from app.agent import triage as triage_agent
from app.services import llm
from app.services.runs import Timer, log_run


def triage_node(state: dict) -> dict:
    db = state.get("db")
    session = state.get("session_obj")
    question = state["question"]
    slots = {}
    if session is not None and session.slots:
        slots = dict(session.slots)

    result = None
    error = None
    with Timer() as t:
        try:
            raw = llm.chat(
                triage_agent.build_messages(question, getattr(session, "rolling_summary", "") or "", slots),
                temperature=0.0, agent="triage",
                tenant_id=getattr(session, "tenant_id", None),
            )
            result = triage_agent.parse_llm_output(raw)
        except Exception as exc:  # noqa: BLE001 —— 分诊永不阻塞对话
            error = str(exc)

    if result is None:
        result = triage_agent.keyword_fallback(question)

    intent = triage_agent.pick_primary(result["intents"])
    order_no = result.get("order_no") or slots.get("last_order_id")

    # 槽位回写：记住最近提到的订单号（指代消解的基础）+ 意图快照（运营台图表用）
    if session is not None:
        if order_no:
            session.slots = {**slots, "last_order_id": order_no}
        if result.get("sentiment") is not None:
            session.sentiment = result["sentiment"]
        session.last_intent = {"intents": result["intents"],
                               "sentiment": result["sentiment"],
                               "urgency": result["urgency"]}

    log_run(
        db, session.id if session else None, "triage", "triage",
        input_summary={"current_message": question[:200]},
        output=result, latency_ms=t.ms, message_id=state.get("message_id"),
        used_llm=(error is None), error=error,
        status="success" if error is None else "degraded",
    )
    return {
        "intent": intent,
        "order_no": order_no,
        "sentiment": result["sentiment"],
        "steps": state.get("steps", []) + ["triage"],
    }
