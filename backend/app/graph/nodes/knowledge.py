"""知识库节点：检索 + 带引用生成。"""
from app.agent import knowledge as knowledge_agent
from app.services import kb, llm
from app.services.runs import Timer, log_run


def knowledge_node(state: dict) -> dict:
    db = state.get("db")
    session = state.get("session_obj")
    question = state["question"]

    error = None
    with Timer() as t:
        chunks = kb.retrieve(db, question) if db else []
        answer = None
        if chunks:
            try:
                msgs = knowledge_agent.build_messages(question, chunks)
                # 质检打回重写：带上问题清单二次生成（W3 回环）
                if state.get("qc_feedback"):
                    msgs = msgs + [{
                        "role": "user",
                        "content": f"你上一版回答未通过质检，问题：{state['qc_feedback']}。"
                                   f"请严格依据知识片段重写，补全关键数字与限定条件，不要遗漏。",
                    }]
                answer = llm.chat(msgs, agent="knowledge")
            except Exception as exc:  # noqa: BLE001
                error = str(exc)

    refused = knowledge_agent.is_refusal(answer) if answer else True
    log_run(
        db, session.id if session else None, "knowledge", "knowledge",
        input_summary={"question": question[:200], "chunks": [c["id"] for c in chunks]},
        output={"answer": (answer or "")[:300], "refused": refused, "chunks_hit": len(chunks)},
        latency_ms=t.ms, message_id=state.get("message_id"),
        used_llm=bool(chunks) and error is None, error=error,
        status="success" if answer else ("degraded" if error else "rejected"),
    )
    return {
        "answer": answer,
        "refused": refused,
        "chunks": chunks,
        "steps": state.get("steps", []) + ["knowledge"],
    }
