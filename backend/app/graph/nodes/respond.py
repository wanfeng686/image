from app.graph.state import AgentState


def respond_node(state: AgentState) -> dict:
    if state.get("answer"):
        return {"steps": state.get("steps", []) + ["respond"]}
    return {"answer": "抱歉，这个问题我需要转人工处理。", "refused": True,
            "steps": state.get("steps", []) + ["respond"]}