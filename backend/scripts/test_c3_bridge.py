"""C3 测试：渠道桥（入站消息 → 引擎 → 回复文本）+ 会话映射 + 卡片降级。

前置：uvicorn 运行中。自建自清（租户「渠道桥测试店」）。
真实走一轮 LLM（查订单出卡），第二轮用升级关键词走前置闸（不耗 LLM）。
用法：python scripts/test_c3_bridge.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from scripts.testutil import Tally, register_tenant  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AgentRun, ChannelConnection, ChatSession, EmailCode, EscalationRule, Message,
    MockOrder, MockProduct, Operator, RiskRule, Tenant, User,
)
from app.services.channels.bridge import (  # noqa: E402
    format_agent_message, process_channel_message,
)
from app.services.channels.base import InboundMessage  # noqa: E402

BASE = "http://127.0.0.1:8000"
T_NAME = "渠道桥测试店"
T_EMAIL = "c3owner@testshop.dev"
t = Tally()


def cleanup():
    with SessionLocal() as db:
        tn = db.scalar(select(Tenant).where(Tenant.name == T_NAME))
        if tn:
            tid = tn.id
            sids = [s.id for s in db.scalars(
                select(ChatSession).where(ChatSession.tenant_id == tid)).all()]
            for s in sids:
                db.execute(delete(AgentRun).where(AgentRun.session_id == s))
                db.execute(delete(Message).where(Message.session_id == s))
            db.execute(delete(ChatSession).where(ChatSession.tenant_id == tid))
            db.execute(delete(ChannelConnection).where(ChannelConnection.tenant_id == tid))
            db.execute(delete(EscalationRule).where(EscalationRule.tenant_id == tid))
            db.execute(delete(RiskRule).where(RiskRule.tenant_id == tid))
            db.execute(delete(MockOrder).where(MockOrder.tenant_id == tid))
            db.execute(delete(MockProduct).where(MockProduct.tenant_id == tid))
            db.execute(delete(User).where(User.tenant_id == tid))
            db.execute(delete(Operator).where(Operator.tenant_id == tid))
            db.delete(tn)
        db.execute(delete(EmailCode).where(EmailCode.email.like("%@testshop.dev")))
        db.commit()


def main():
    cleanup()
    client = httpx.Client(timeout=180)

    # ── 1. 注册 + 连接 + 推数据（sk_） ──
    r, body = register_tenant(client, T_NAME, T_EMAIL)
    t.check("注册：201", r.status_code == 201)
    H = {"Authorization": f"Bearer {body['token']}"}
    SK = {"Authorization": f"Bearer {body['tenant']['api_secret']}"}
    r = client.post(f"{BASE}/api/channel/connections", headers=H, json={
        "platform": "pinduoduo", "mode": "official_api",
        "credentials": {"client_id": "cid", "client_secret": "csecret"}})
    t.check("连接：创建 201", r.status_code == 201)
    cid = r.json()["id"]
    client.post(f"{BASE}/api/v1/products", headers=SK, json={"items": [
        {"sku": "C3-001", "name": "测试蓝牙耳机", "price": 199}]})
    client.post(f"{BASE}/api/v1/orders", headers=SK, json={"items": [
        {"order_no": "C3-9001", "sku": "C3-001", "user_external_id": "pinduoduo:buyer-77",
         "amount": 199, "status": "shipped"}]})

    with SessionLocal() as db:
        conn = db.get(ChannelConnection, cid)
        tenant = db.get(Tenant, conn.tenant_id)

        # ── 2. 第一条入站消息：查订单（真实 LLM，出卡片） ──
        m1 = InboundMessage(platform="pinduoduo", conversation_ref="conv-9001",
                            buyer_id="buyer-77", buyer_name="小七",
                            text="查一下订单 C3-9001", ts=1)
        reply1 = process_channel_message(db, conn, m1)
        t.check("桥：回复非空且含订单信息",
                bool(reply1.text) and ("订单" in reply1.text or "C3-9001" in reply1.text),
                reply1.text[:120])
        t.check("桥：卡片降级为文本行",
                reply1.card is not None and ("测试蓝牙耳机" in reply1.text or "¥199" in reply1.text
                                             or "已发货" in reply1.text), reply1.text[:150])
        sess = db.scalar(select(ChatSession).where(
            ChatSession.tenant_id == tenant.id,
            ChatSession.external_ref == "pinduoduo:conv-9001"))
        t.check("桥：会话按 external_ref 建立且 channel=pinduoduo",
                sess is not None and sess.channel == "pinduoduo",
                sess.channel if sess else "无会话")
        usr = db.scalar(select(User).where(
            User.tenant_id == tenant.id, User.external_id == "pinduoduo:buyer-77"))
        t.check("桥：买家按 平台:ID 绑定 User", usr is not None)
        t.check("桥：消息落库（顾客+客服）",
                db.scalar(select(Message).where(
                    Message.session_id == sess.id, Message.role == "customer")) is not None
                and db.scalar(select(Message).where(
                    Message.session_id == sess.id, Message.role == "agent")) is not None)

        # ── 3. 第二条消息：同会话复用 + 升级关键词走前置闸（不耗 LLM） ──
        m2 = InboundMessage(platform="pinduoduo", conversation_ref="conv-9001",
                            buyer_id="buyer-77", text="我要转人工", ts=2)
        reply2 = process_channel_message(db, conn, m2)
        sess2 = db.scalar(select(ChatSession).where(
            ChatSession.tenant_id == tenant.id,
            ChatSession.external_ref == "pinduoduo:conv-9001"))
        t.check("桥：同 external_ref 复用会话", reply2.session_id == reply1.session_id
                and sess2.id == sess.id)
        t.check("桥：升级前置闸生效", "人工" in reply2.text, reply2.text[:80])

        # ── 4. 跨租户不串号：演示商城查不到该 external_ref ──
        demo = db.scalar(select(Tenant).where(
            Tenant.widget_key == "pk_demo000000000000"))
        t.check("桥：external_ref 租户隔离",
                db.scalar(select(ChatSession).where(
                    ChatSession.tenant_id == demo.id,
                    ChatSession.external_ref == "pinduoduo:conv-9001")) is None)
        t.check("桥：last_sync_at 回写", conn.last_sync_at is not None)

    # ── 5. format_agent_message 纯函数（退款卡降级） ──
    fake = SimpleNamespace(role="agent",
                           content="已为您提交退款申请。",
                           card_data={"type": "refund", "order_no": "C3-9001",
                                      "amount": 199, "status": "pending_approval"})
    txt = format_agent_message(fake)
    t.check("格式化：退款卡 → 文本行", "退款进度" in txt and "C3-9001" in txt
            and "等待人工审批" in txt, txt)
    fake2 = SimpleNamespace(role="agent", content="纯文本回复", card_data=None)
    t.check("格式化：无卡片原样返回", format_agent_message(fake2) == "纯文本回复")

    client.close()
    rc = t.done("C3 渠道桥")
    cleanup()
    sys.exit(rc)


if __name__ == "__main__":
    main()
