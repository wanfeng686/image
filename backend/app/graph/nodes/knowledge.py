from app.agent import knowledge as knowledge_agent
from app.graph.state import AgentState
from app.services import llm


def knowledge_node(state: AgentState) -> dict:
    answer = llm.chat(knowledge_agent.build_messages(state["question"], state["chunks"]))
    return {"answer": answer, "refused": knowledge_agent.is_refusal(answer),
            "steps": state.get("steps", []) + ["knowledge"]}