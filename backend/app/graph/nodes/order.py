"""订单节点：归属断言查询 + 卡片输出（数据走卡片不走纯文本，减少幻觉面）。"""
from app.services import orders as order_svc
from app.services.runs import Timer, log_run


def order_node(state: dict) -> dict:
    db = state.get("db")
    session = state.get("session_obj")
    user_id = state.get("user_id")
    order_no = state.get("order_no")

    with Timer() as t:
        order = order_svc.get_order(db, user_id, order_no)
        if order is None:
            # 找不到：可能是单号不存在，也可能是别人的单（归属断言下无法区分——这是特性不是缺陷）
            output = {"found": False, "order_no": order_no}
            answer = ("没有找到您的这笔订单，请核对订单号（格式如 SO-0002）。"
                      "您也可以直接说“查我最近的订单”。")
            card = None
        else:
            card = order_svc.order_card(db, order)
            answer = order_svc.order_text(card)
            output = {"found": True, "order_no": order.order_no, "status": order.status}
            # 槽位回写
            if session is not None:
                session.slots = {**(session.slots or {}), "last_order_id": order.order_no}

    log_run(
        db, session.id if session else None, "order", "order",
        input_summary={"order_no": order_no, "user_id": str(user_id)},
        output=output, latency_ms=t.ms, message_id=state.get("message_id"),
    )
    return {
        "answer": answer,
        "card": card,
        "refused": False,
        "steps": state.get("steps", []) + ["order"],
    }
