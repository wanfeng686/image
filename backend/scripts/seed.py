"""模拟电商种子数据：运营账号、风险规则、商品/订单/物流、演示用户。

幂等设计：按唯一键查存在即跳过，可反复执行。
用法：python scripts/seed.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import (
    EscalationRule, MockOrder, MockProduct, MockShipment, Operator, RiskRule, User,
)

now = datetime.now(timezone.utc)

OPERATORS = [
    {"username": "admin", "display_name": "管理员", "role": "admin", "password": "admin123"},
    {"username": "approver", "display_name": "审批员A", "role": "operator", "password": "op123456"},
]

RISK_RULES = [
    {"rule_key": "auto_approve_limit", "value": {"amount": 50}},          # 小额自动
    {"rule_key": "queue_approve_limit", "value": {"amount": 500}},        # 中额排队，超过则双签
    {"rule_key": "risk_weights", "value": {"amount": 0.4, "freq": 0.3, "profile": 0.2, "sentiment": 0.1}},
    {"rule_key": "freq_aggregate_window_hours", "value": {"hours": 72}},
    {"rule_key": "approval_timeout_hours", "value": {"hours": 4}},
    {"rule_key": "aggregate_30d_limit", "value": {"amount": 600}},        # 30天累计退款旁路上限
]

ESCALATION_RULES = [
    {"rule_type": "keyword", "name": "法律与曝光风险词", "priority": 10,
     "config": {"keywords": ["投诉", "曝光", "工商", "法律", "律师", "报警", "媒体", "12315"]}},
    {"rule_type": "keyword", "name": "显式转人工请求", "priority": 20,
     "config": {"keywords": ["转人工", "人工客服", "真人"]}},
    {"rule_type": "condition", "name": "VIP用户直达", "priority": 30,
     "config": {"user_tier": "vip"}},
    {"rule_type": "condition", "name": "情绪阈值", "priority": 40,
     "config": {"sentiment_below": 2.0}},
]

PRODUCTS = [
    {"sku": "P-001", "name": "无线耳机X3", "price": 299, "category": "数码"},
    {"sku": "P-002", "name": "保温杯lite", "price": 49, "category": "家居"},
    {"sku": "P-003", "name": "机械键盘K87", "price": 399, "category": "数码"},
    {"sku": "P-004", "name": "智能手环S2", "price": 129, "category": "数码"},
    {"sku": "P-005", "name": "旗舰手机Pro", "price": 4999, "category": "数码"},
    {"sku": "P-006", "name": "儿童积木桶", "price": 89, "category": "玩具"},
]

# 用户：external_id 唯一；演示主用户是"顾客演示"
USERS = [
    {"external_id": "demo", "nickname": "顾客演示", "user_tier": "normal", "risk_flags": {}, "total_refund_30d": 0},
    {"external_id": "wool", "nickname": "羊毛小王", "user_tier": "normal",
     "risk_flags": {"wool_party": True}, "total_refund_30d": 680},
    {"external_id": "vip", "nickname": "VIP大客户", "user_tier": "vip", "risk_flags": {}, "total_refund_30d": 0},
]

# 订单：(external_id, sku, order_no, status, paid偏移天数, 发运状态, eta偏移天数|None)
ORDERS = [
    ("demo", "P-002", "SO-0001", "delivered", -30, "delivered", -26),
    ("demo", "P-001", "SO-0002", "shipped", -3, "in_transit", 1),
    ("demo", "P-005", "SO-0003", "paid", -1, None, None),
    ("wool", "P-002", "SO-1001", "refunded", -20, None, None),
    ("wool", "P-006", "SO-1002", "refunded", -12, None, None),
    ("wool", "P-004", "SO-1003", "refunding", -2, None, None),
    ("vip", "P-003", "SO-2001", "shipped", -5, "in_transit", 2),
]


def seed():
    db = SessionLocal()
    try:
        # 1. 运营账号
        for op in OPERATORS:
            if db.scalar(select(Operator).where(Operator.username == op["username"])) is None:
                db.add(Operator(username=op["username"], display_name=op["display_name"],
                                role=op["role"], password_hash=hash_password(op["password"])))
        # 2. 风险规则
        for r in RISK_RULES:
            if db.scalar(select(RiskRule).where(RiskRule.rule_key == r["rule_key"])) is None:
                db.add(RiskRule(**r))
        # 3. 升级规则
        for r in ESCALATION_RULES:
            if db.scalar(select(EscalationRule).where(EscalationRule.name == r["name"])) is None:
                db.add(EscalationRule(**r))
        # 4. 商品
        for p in PRODUCTS:
            if db.scalar(select(MockProduct).where(MockProduct.sku == p["sku"])) is None:
                db.add(MockProduct(**p))
        db.flush()

        # 5. 用户
        user_ids = {}
        for u in USERS:
            row = db.scalar(select(User).where(User.external_id == u["external_id"]))
            if row is None:
                row = User(**u)
                db.add(row)
                db.flush()
            user_ids[u["external_id"]] = row.id

        # 6. 订单 + 物流
        sku2id = {p.sku: p.id for p in db.scalars(select(MockProduct)).all()}
        for ext, sku, order_no, status, paid_off, ship_status, eta_off in ORDERS:
            if db.scalar(select(MockOrder).where(MockOrder.order_no == order_no)):
                continue
            order = MockOrder(
                order_no=order_no, user_id=user_ids[ext], product_id=sku2id[sku],
                amount=next(p["price"] for p in PRODUCTS if p["sku"] == sku),
                status=status, address_masked="北京市朝阳区***路**号",
                paid_at=now + timedelta(days=paid_off),
            )
            db.add(order)
            db.flush()
            if ship_status:
                db.add(MockShipment(order_id=order.id, carrier="顺丰速运",
                                    tracking_no=f"SF{order_no.replace('-', '')}88",
                                    status=ship_status,
                                    estimated_delivery=(now + timedelta(days=eta_off)).date()))
        db.commit()

        # 汇总
        counts = {
            "operators": len(db.scalars(select(Operator)).all()),
            "risk_rules": len(db.scalars(select(RiskRule)).all()),
            "escalation_rules": len(db.scalars(select(EscalationRule)).all()),
            "products": len(db.scalars(select(MockProduct)).all()),
            "users": len(db.scalars(select(User)).all()),
            "orders": len(db.scalars(select(MockOrder)).all()),
        }
        print("种子完成：", counts)
        demo = db.scalar(select(User).where(User.external_id == "demo"))
        print(f"演示用户 id: {demo.id}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
