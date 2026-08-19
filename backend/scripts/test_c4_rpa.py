"""C4 测试：RPA Worker 端到端闭环（headless）。

链路：内置模拟拼多多后台（/simulator/）机器人买家发问 → Playwright worker
读取 → 渠道桥跑 AI 引擎 → 回复填回模拟后台 → 状态 pending→connected。

前置：uvicorn 运行中 + playwright chromium 已安装。自建自清（租户「RPA测试店」）。
用法：python scripts/test_c4_rpa.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from scripts.testutil import Tally, register_tenant  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AgentRun, ChannelConnection, ChatSession, EmailCode, EscalationRule, Message,
    MockOrder, MockProduct, Operator, RiskRule, Tenant, User,
)
from scripts.channel_worker import PROFILE_ROOT, run_cycle  # noqa: E402

BASE = "http://127.0.0.1:8000"
T_NAME = "RPA测试店"
T_EMAIL = "c4owner@testshop.dev"
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


def rmdir(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


def main():
    cleanup()
    client = httpx.Client(timeout=180)

    # ── 1. 商户 + 数据 + RPA 连接 ──
    r, body = register_tenant(client, T_NAME, T_EMAIL)
    t.check("注册：201", r.status_code == 201)
    H = {"Authorization": f"Bearer {body['token']}"}
    SK = {"Authorization": f"Bearer {body['tenant']['api_secret']}"}
    client.post(f"{BASE}/api/v1/products", headers=SK, json={"items": [
        {"sku": "R4-001", "name": "便携榨汁杯", "price": 89}]})
    r = client.post(f"{BASE}/api/v1/orders", headers=SK, json={"items": [
        {"order_no": "S-7701", "sku": "R4-001", "user_external_id": "pinduoduo:buyer-901",
         "amount": 89, "status": "shipped"}]})
    t.check("订单数据就绪", r.status_code == 200, r.text[:100])

    # 机器人买家固定 buyer-901 / conv-9001（模拟后台脚本内置）；
    # 上面推订单时 user_external_id=pinduoduo:buyer-901 已自动建好买家

    r = client.post(f"{BASE}/api/channel/connections", headers=H, json={
        "platform": "pinduoduo", "mode": "rpa",
        "credentials": {"username": "13900009011", "password": "RpaTest@2026"},
        "rpa_consent": True})
    t.check("RPA 连接：创建 201", r.status_code == 201, r.text[:120])
    cid = r.json()["id"]
    rmdir(PROFILE_ROOT / cid)

    # ── 2. Worker 周期：登录（pending→connected），等机器人发问，再跑一轮应答 ──
    adapters = {}
    with sync_playwright() as pw:
        acts1 = run_cycle(pw, adapters, headless=True)
        with SessionLocal() as db:
            conn = db.get(ChannelConnection, cid)
            t.check("worker：登录成功 pending→connected", conn.status == "connected",
                    f"status={conn.status} err={conn.last_error}")
        t.check("worker：首轮无消息（机器人未发问）", acts1 == [], str(acts1)[:100])

        time.sleep(3.0)   # 机器人买家在登录后 ~1.8s 发第一条
        acts2 = [a for a in run_cycle(pw, adapters, headless=True) if a["conn"] == cid]
        t.check("worker：处理了买家消息", len(acts2) == 1
                and "S-7701" in acts2[0]["inbound"], str(acts2)[:200])
        t.check("worker：AI 回复含订单信息",
                any(k in (acts2[0]["reply"] if acts2 else "")
                    for k in ("便携榨汁杯", "¥89", "已发货", "订单")),
                str(acts2)[:300])

        # ── 3. DB 侧验证：会话/消息/回执 ──
        with SessionLocal() as db:
            conn = db.get(ChannelConnection, cid)
            sess = db.scalar(select(ChatSession).where(
                ChatSession.tenant_id == conn.tenant_id,
                ChatSession.external_ref == "pinduoduo:conv-9001"))
            t.check("DB：渠道会话已建立", sess is not None)
            agent_msgs = db.scalars(select(Message).where(
                Message.session_id == sess.id, Message.role == "agent")).all() if sess else []
            t.check("DB：AI 回复已落库", len(agent_msgs) >= 1)
            t.check("DB：last_sync_at 已更新", conn.last_sync_at is not None)

        # ── 4. 模拟后台侧验证：商家消息出现在页面 DOM ──
        page = adapters[cid].page
        sent = page.eval_on_selector_all(
            '.msg[data-sender="merchant"] .msg-text', "els => els.map(e => e.textContent)")
        t.check("页面：回复已发到模拟后台", any("订单" in (s or "") or "榨汁杯" in (s or "")
                                             for s in sent), str(sent)[:200])

        # ── 5. 收尾：删除连接 → worker 下周期自动关浏览器 ──
        client.delete(f"{BASE}/api/channel/connections/{cid}", headers=H)
        acts3 = run_cycle(pw, adapters, headless=True)
        t.check("worker：连接删除后浏览器已回收", cid not in adapters)

    rmdir(PROFILE_ROOT / cid)
    client.close()
    rc = t.done("C4 RPA 闭环")
    cleanup()
    sys.exit(rc)


if __name__ == "__main__":
    main()
