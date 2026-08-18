"""W1 简化 Triage：用检索命中冒充意图判断。
W2 将替换为 LLM 分诊（会话摘要 + 槽位），节点接口不变。"""

from app.graph.state import AgentState
from app.services import kb


def triage_node(state: AgentState) -> dict:
    chunks = kb.retrieve(state["question"])
    intent = "faq" if chunks else "unknown"
    return {"intent": intent, "chunks": chunks,
            "steps": state.get("steps", []) + ["triage"]}