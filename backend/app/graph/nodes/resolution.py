"""处置节点：退款三路（自动/审批/双签），风险评分在代码不在 LLM。

资金类动作全部走 services/approval 的幂等通道，本节点只做编排。
"""
from app.services import approval as approval_svc
from app.services import orders as order_svc
from app.services import risk as risk_svc
from app.services.runs import Timer, log_run


def resolution_node(state: dict) -> dict:
    db = state.get("db")
    session = state.get("session_obj")
    user_id = state.get("user_id")
    order_no = state.get("order_no")
    question = state["question"]

    with Timer() as t:
        order = order_svc.get_order(db, user_id, order_no)

        if order is None:
            output = {"route": "clarify"}
            answer = ("请问您要退哪一单？可以提供订单号（如 SO-0002），"
                      "或直接说“退我最近的订单”。")
            log_run(db, session.id if session else None, "resolution", "resolution",
                    input_summary={"order_no": order_no}, output=output,
                    latency_ms=t.ms, message_id=state.get("message_id"))
            return {"answer": answer, "card": None, "refused": False,
                    "steps": state.get("steps", []) + ["resolution"]}

        # 已退款 → 幂等 UX：直接告知，不再建审批
        if order.status == "refunded":
            output = {"route": "already_refunded", "order_no": order.order_no}
            answer = f"订单 {order.order_no} 已完成退款，请勿重复申请哦。"
            log_run(db, session.id if session else None, "resolution", "resolution",
                    input_summary={"order_no": order_no}, output=output,
                    latency_ms=t.ms, message_id=state.get("message_id"))
            return {"answer": answer, "card": None, "refused": False,
                    "steps": state.get("steps", []) + ["resolution"]}

        from app.models import User  # noqa: PLC0415 —— 局部导入避免与节点层环依赖
        user = db.get(User, user_id)

        score, breakdown, level, required = risk_svc.score_refund(
            db, user, order, state.get("sentiment"),
        )
        timeout_hours = float(risk_svc.load_rules(db)
                              .get("approval_timeout_hours", {}).get("hours", 4))

        if level == "low":
            # 低风险 → 自动执行（幂等：executed_actions 拦重放）
            _, executed = approval_svc.execute_refund(
                db, session.id, order, user, approval_request=None, executed_by="auto",
            )
            card = {"type": "refund", "order_no": order.order_no,
                    "amount": float(order.amount), "status": "auto_approved"}
            if executed:
                answer = risk_svc.refund_text(level, card, score, timeout_hours)
                output = {"route": "auto_executed", "order_no": order.order_no,
                          "risk_score": score, "breakdown": breakdown}
            else:
                answer = f"订单 {order.order_no} 的退款已在处理中，请勿重复申请。"
                output = {"route": "idempotent_skip", "order_no": order.order_no}
        else:
            # 中/高风险 → 进审批队列（幂等：同 key 只建一条）
            req, created = approval_svc.request_refund_approval(
                db, session, order, reason=question, score=score,
                breakdown=breakdown, level=level, required=required,
                message_id=state.get("message_id"),
            )
            card = {"type": "refund", "order_no": order.order_no,
                    "amount": float(order.amount),
                    "status": "pending_approval" if created else req.status,
                    "risk_score": score, "risk_level": level,
                    "required_approvals": req.required_approvals,
                    "approval_id": str(req.id),
                    "timeout_at": req.timeout_at.isoformat()}
            answer = (risk_svc.refund_text(level, card, score, timeout_hours)
                      if created else
                      f"订单 {order.order_no} 的退款申请已在审核队列中，请耐心等待。")
            output = {"route": f"approval_{level}", "created": created,
                      "order_no": order.order_no, "risk_score": score,
                      "breakdown": breakdown, "approval_id": str(req.id)}

    log_run(db, session.id if session else None, "resolution", "resolution",
            input_summary={"order_no": order_no, "question": question[:200]},
            output=output, latency_ms=t.ms, message_id=state.get("message_id"))
    return {
        "answer": answer,
        "card": card,
        "refused": False,
        "session_status": "waiting_approval" if level != "low" else None,
        "steps": state.get("steps", []) + ["resolution"],
    }
