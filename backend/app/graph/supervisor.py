from langgraph.graph import END, START, StateGraph

from app.graph.nodes.knowledge import knowledge_node
from app.graph.nodes.order import order_node
from app.graph.nodes.qc import qc_node
from app.graph.nodes.respond import respond_node
from app.graph.nodes.resolution import resolution_node
from app.graph.nodes.triage import triage_node
from app.graph.state import AgentState


def route_after_triage(state: AgentState) -> str:
    """条件边：按主意图分发。退款(资金) > 查单 > FAQ，其余拒答。"""
    intent = state.get("intent")
    if intent == "refund":
        return "resolution"
    if intent == "order_query":
        return "order"
    if intent == "faq":
        return "knowledge"
    return "respond"


def route_after_qc(state: AgentState) -> str:
    """质检回环：不过 → 回知识节点重写（上限在 qc 节点内控）；过 → 响应。"""
    return "respond" if state.get("qc_passed", True) else "knowledge"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("triage", triage_node)
    g.add_node("knowledge", knowledge_node)
    g.add_node("qc", qc_node)
    g.add_node("order", order_node)
    g.add_node("resolution", resolution_node)
    g.add_node("respond", respond_node)

    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", route_after_triage, {
        "knowledge": "knowledge",
        "order": "order",
        "resolution": "resolution",
        "respond": "respond",
    })
    # 知识回答必过质检闸（W3）
    g.add_edge("knowledge", "qc")
    g.add_conditional_edges("qc", route_after_qc, {"knowledge": "knowledge", "respond": "respond"})
    g.add_edge("order", "respond")
    g.add_edge("resolution", "respond")
    g.add_edge("respond", END)
    return g.compile()


supervisor = build_graph()
