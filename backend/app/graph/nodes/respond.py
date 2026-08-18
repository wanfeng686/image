"""响应节点：兜底拒答 + 轨迹收尾。"""
from app.services.runs import log_run

REFUSAL_TEXT = "抱歉，这个问题我需要转人工处理。"


def respond_node(state: dict) -> dict:
    db = state.get("db")
    session = state.get("session_obj")
    if state.get("answer"):
        log_run(db, session.id if session else None, "supervisor", "respond",
                input_summary=None,
                output={"delivered": True, "card": bool(state.get("card"))},
                message_id=state.get("message_id"))
        return {"steps": state.get("steps", []) + ["respond"]}
    log_run(db, session.id if session else None, "supervisor", "respond",
            input_summary=None, output={"delivered": False, "refused": True},
            message_id=state.get("message_id"))
    return {"answer": REFUSAL_TEXT, "refused": True,
            "steps": state.get("steps", []) + ["respond"]}
