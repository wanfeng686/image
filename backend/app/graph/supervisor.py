from langgraph.graph import END, START, StateGraph

from app.graph.nodes.knowledge import knowledge_node
from app.graph.nodes.respond import respond_node
from app.graph.nodes.triage import triage_node
from app.graph.state import AgentState


def route_after_triage(state: AgentState) -> str:
    """条件边：命中知识走 knowledge，否则直接 respond 拒答。"""
    return "knowledge" if state["intent"] == "faq" else "respond"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("triage", triage_node)
    g.add_node("knowledge", knowledge_node)
    g.add_node("respond", respond_node)

    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_after_triage,
                            {"knowledge": "knowledge", "respond": "respond"})
    g.add_edge("knowledge", "respond")
    g.add_edge("respond", END)
    return g.compile()


supervisor = build_graph()