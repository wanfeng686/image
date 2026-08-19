"""演示数据管理：重置动态数据（审批/执行/轨迹/消息/会话），保留静态种子。

scripts/reset_demo.py 是它的命令行壳；/api/admin/demo/reset 是 HTTP 壳。
SaaS 化：订单状态/退款额度恢复只作用于演示商城租户；动态数据（会话等）
全平台清空——本地演示环境的清理工具，正式部署不应开放此接口。
"""
from sqlalchemy import delete, select, update

from app.core.db import SessionLocal
from app.models import (
    AgentRun, ApprovalAction, ApprovalRequest, ChatSession, ExecutedAction,
    InsightFinding, InsightReport, KbDraft, KbGapRecord, Message, MockOrder,
    SessionNote, Tenant, User,
)

SEED_ORDER_STATUS = {
    "SO-0001": "delivered", "SO-0002": "shipped", "SO-0003": "paid",
    "SO-1001": "refunded", "SO-1002": "refunded", "SO-1003": "refunding",
    "SO-2001": "shipped",
}
SEED_USER_REFUND = {"demo": 0, "wool": 680, "vip": 0}
DEMO_WIDGET_KEY = "pk_demo000000000000"


def reset_demo() -> dict:
    db = SessionLocal()
    try:
        demo = db.scalar(select(Tenant).where(Tenant.widget_key == DEMO_WIDGET_KEY))

        db.execute(delete(ExecutedAction))
        db.execute(delete(ApprovalAction))
        db.execute(delete(ApprovalRequest))
        db.execute(delete(AgentRun))
        db.execute(delete(SessionNote))
        db.execute(delete(InsightFinding))
        db.execute(delete(InsightReport))
        db.execute(delete(KbDraft))
        db.execute(delete(KbGapRecord))
        db.execute(delete(Message))
        db.execute(delete(ChatSession))

        if demo is not None:
            for order_no, status in SEED_ORDER_STATUS.items():
                db.execute(update(MockOrder).where(
                    MockOrder.order_no == order_no, MockOrder.tenant_id == demo.id)
                    .values(status=status))
            for ext, total in SEED_USER_REFUND.items():
                db.execute(update(User).where(
                    User.external_id == ext, User.tenant_id == demo.id)
                    .values(total_refund_30d=total))
        db.commit()
        return {"ok": True, "message": "动态数据已清空，订单/额度/知识库种子保留"}
    finally:
        db.close()
