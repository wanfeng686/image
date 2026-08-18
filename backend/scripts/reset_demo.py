"""演示数据重置：清掉测试期产生的审批/执行/会话脏数据，还原种子状态。

可反复执行；用于跑端到端测试前清场，或演示前"重置演示数据"。
用法：python scripts/reset_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, update  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AgentRun, ApprovalAction, ApprovalRequest, ChatSession, ExecutedAction,
    Message, MockOrder, SessionNote, User,
)

SEED_ORDER_STATUS = {
    "SO-0001": "delivered", "SO-0002": "shipped", "SO-0003": "paid",
    "SO-1001": "refunded", "SO-1002": "refunded", "SO-1003": "refunding",
    "SO-2001": "shipped",
}
SEED_USER_REFUND = {"demo": 0, "wool": 680, "vip": 0}


def reset():
    db = SessionLocal()
    try:
        db.execute(delete(ExecutedAction))
        db.execute(delete(ApprovalAction))
        db.execute(delete(ApprovalRequest))
        db.execute(delete(AgentRun))
        db.execute(delete(SessionNote))
        db.execute(delete(Message))
        db.execute(delete(ChatSession))

        for order_no, status in SEED_ORDER_STATUS.items():
            db.execute(update(MockOrder).where(MockOrder.order_no == order_no)
                       .values(status=status))
        for ext, total in SEED_USER_REFUND.items():
            db.execute(update(User).where(User.external_id == ext)
                       .values(total_refund_30d=total))
        db.commit()
        print("重置完成：审批/执行/轨迹/消息/会话已清空，订单与用户额度已还原")
    finally:
        db.close()


if __name__ == "__main__":
    reset()
