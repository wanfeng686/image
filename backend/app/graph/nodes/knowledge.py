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
        chunks = kb.retrieve(question)
        answer = None
        if chunks:
            try:
                answer = llm.chat(knowledge_agent.build_messages(question, chunks))
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
