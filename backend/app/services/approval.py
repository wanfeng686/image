"""审批服务：审批请求创建 + 退款执行，幂等键三处落位（DESIGN 决策 #3）。

- approval_requests.idempotency_key  UNIQUE → 同会话同单同动作只建一条
- executed_actions.idempotency_key   UNIQUE → 执行层再防一道重放（审批重放/网络重试永不双退款）
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApprovalRequest, ExecutedAction, MockOrder, User
from app.services.risk import load_rules


def _now() -> datetime:
    return datetime.now(timezone.utc)


def idem_key(session_id, action_type: str, order_no: str) -> str:
    return f"{session_id}:{action_type}:{order_no}"


def request_refund_approval(
    db: Session, session, order: MockOrder, reason: str,
    score: float, breakdown: dict, level: str, required: int,
    message_id: uuid.UUID | None = None,
) -> tuple[ApprovalRequest, bool]:
    """创建审批请求。幂等：同 key 已存在直接返回 (既有记录, False)。"""
    key = idem_key(session.id, "refund", order.order_no)
    existing = db.scalar(select(ApprovalRequest).where(ApprovalRequest.idempotency_key == key))
    if existing is not None:
        return existing, False

    rules = load_rules(db)
    timeout_hours = float(rules.get("approval_timeout_hours", {}).get("hours", 4))
    prev_status = order.status  # 记住驳回/超时要回滚的状态

    req = ApprovalRequest(
        session_id=session.id,
        message_id=message_id,
        action_type="refund",
        action_payload={
            "order_no": order.order_no,
            "amount": float(order.amount),
            "reason": (reason or "")[:200],
            "prev_status": prev_status,
        },
        risk_score=Decimal(str(score)),
        risk_breakdown=breakdown,
        risk_level=level,
        required_approvals=required,
        granted_approvals=0,
        idempotency_key=key,
        status="pending",
        timeout_at=_now() + timedelta(hours=timeout_hours),
    )
    db.add(req)
    db.flush()

    # 订单与会话状态推进
    if order.status not in ("refunding", "refunded"):
        order.status = "refunding"
    session.status = "waiting_approval"
    session.escalated_reason = None
    return req, True


def execute_refund(
    db: Session, session_id, order: MockOrder, user: User,
    approval_request: ApprovalRequest | None = None, executed_by: str = "auto",
) -> tuple[ExecutedAction | None, bool]:
    """执行退款（改订单状态 + 累计 30 天退款额 + 落资金流水）。

    幂等：executed_actions 同 key 已存在则不重复执行，返回 (None, False)。
    注意：金额累计只在真正执行时加一次。
    """
    key = f"exec:{idem_key(session_id, 'refund', order.order_no)}"
    if db.scalar(select(ExecutedAction).where(ExecutedAction.idempotency_key == key)):
        return None, False

    amount = float(order.amount)
    order.status = "refunded"
    user.total_refund_30d = Decimal(str(float(user.total_refund_30d or 0) + amount))

    row = ExecutedAction(
        approval_request_id=approval_request.id if approval_request else None,
        session_id=session_id,
        action_type="refund",
        payload={"order_no": order.order_no, "amount": amount},
        idempotency_key=key,
        executed_by=executed_by,
        status="executed",
        result={"order_no": order.order_no, "refund_amount": amount},
    )
    db.add(row)
    db.flush()
    return row, True


def revert_refund_request(db: Session, req: ApprovalRequest) -> None:
    """驳回/超时回滚：订单状态还原到申请前（prev_status），不动资金账。"""
    order_no = req.action_payload.get("order_no")
    order = db.scalar(select(MockOrder).where(MockOrder.order_no == order_no))
    if order and order.status == "refunding":
        order.status = req.action_payload.get("prev_status") or "paid"
