"""S1 租户隔离测试：多租户数据/鉴权/检索/越权全面校验。

前置：docker compose + 迁移 + seed + uvicorn 运行中。
用法：python scripts/test_s1_isolation.py
做法：DB 直建一个"测试商户B"租户（含 KB/订单/操作员），从 API 验证隔离，
结束时清理 B 的全部数据。
"""
import sys
import uuid as uuidlib
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    AgentRun, ChatSession, KbDocument, KbDocumentVersion, Message, MockOrder,
    MockProduct, MockShipment, Operator, Tenant, User,
)

BASE = "http://127.0.0.1:8000"
DEMO_KEY = "pk_demo000000000000"
B_KEY = "pk_test_b_tenant_0001"
B_SECRET = "sk_test_b_tenant_0001"
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    print(("✅" if cond else "❌") + f" {name}" + (f"  [{detail}]" if detail and not cond else ""))
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (1 if not cond else 0)


def setup_tenant_b():
    """直建测试租户 B：1 个 KB 文档 + 1 个商品/订单 + 1 个操作员。"""
    with SessionLocal() as db:
        # 幂等清理旧残留
        cleanup_tenant_b()
        t = Tenant(name="测试商户B", widget_key=B_KEY, api_secret=B_SECRET,
                   allowed_origins=["http://merchant-b.local"])
        db.add(t)
        db.flush()
        doc = KbDocument(tenant_id=t.id, code="kb-001", title="B店退货政策",
                         status="published", created_by="test")
        db.add(doc)
        db.flush()
        ver = KbDocumentVersion(document_id=doc.id, version=1,
                                content="B店特别政策：所有商品30天无理由退货。",
                                effective_from=__import__("datetime").date.today())
        db.add(ver)
        db.flush()
        doc.current_version_id = ver.id
        prod = MockProduct(tenant_id=t.id, sku="B-001", name="B店特产礼盒", price=199)
        db.add(prod)
        db.flush()
        user = User(tenant_id=t.id, external_id="b-customer", nickname="B店顾客")
        db.add(user)
        db.flush()
        order = MockOrder(tenant_id=t.id, order_no="B-9001", user_id=user.id,
                          product_id=prod.id, amount=199, status="paid")
        db.add(order)
        db.add(Operator(tenant_id=t.id, username="bowner", display_name="B店店主",
                        role="owner", password_hash=hash_password("bpass123")))
        db.commit()
        return str(t.id)


def cleanup_tenant_b():
    with SessionLocal() as db:
        t = db.scalar(select(Tenant).where(Tenant.widget_key == B_KEY))
        if t is None:
            return
        tid = t.id
        sids = [s.id for s in db.scalars(
            select(ChatSession).where(ChatSession.tenant_id == tid)).all()]
        if sids:
            db.execute(delete(AgentRun).where(AgentRun.session_id.in_(sids)))
            db.execute(delete(Message).where(Message.session_id.in_(sids)))
            db.execute(delete(ChatSession).where(ChatSession.id.in_(sids)))
        db.execute(delete(KbDocumentVersion).where(KbDocumentVersion.document_id.in_(
            select(KbDocument.id).where(KbDocument.tenant_id == tid))))
        db.execute(delete(KbDocument).where(KbDocument.tenant_id == tid))
        db.execute(delete(MockShipment).where(MockShipment.tenant_id == tid))
        db.execute(delete(MockOrder).where(MockOrder.tenant_id == tid))
        db.execute(delete(MockProduct).where(MockProduct.tenant_id == tid))
        db.execute(delete(User).where(User.tenant_id == tid))
        db.execute(delete(Operator).where(Operator.tenant_id == tid))
        db.delete(t)
        db.commit()


def login(client, username, password):
    return client.post(f"{BASE}/api/auth/login",
                       json={"username": username, "password": password}).json()["token"]


def ask(client, sid, q):
    r = client.post(f"{BASE}/api/chat/sessions/{sid}/messages",
                    json={"content": q}, timeout=120)
    r.raise_for_status()
    return r.json()[1]


def main():
    setup_tenant_b()
    client = httpx.Client(timeout=120)
    try:
        # ── 1. 密钥体系 ──
        r = client.post(f"{BASE}/api/widget/sessions", json={},
                        headers={"X-Widget-Key": "pk_wrong"})
        check("密钥：错误 pk_ → 401", r.status_code == 401, str(r.status_code))

        # Origin 白名单：B 配了白名单，错误来源 403，正确来源放行
        r = client.post(f"{BASE}/api/widget/sessions", json={},
                        headers={"X-Widget-Key": B_KEY, "Origin": "http://evil.example"})
        check("Origin：非白名单来源 403", r.status_code == 403, str(r.status_code))
        r = client.post(f"{BASE}/api/widget/sessions", json={},
                        headers={"X-Widget-Key": B_KEY, "Origin": "http://merchant-b.local"})
        check("Origin：白名单来源放行", r.status_code == 201)

        # ── 2. 数据隔离：检索/订单 ──
        # B 店顾客问退货政策 → 只命中 B 店的 30 天政策，不是演示商城的 7 天
        r = client.post(f"{BASE}/api/widget/sessions", json={"user_external_id": "b-customer"},
                        headers={"X-Widget-Key": B_KEY, "Origin": "http://merchant-b.local"})
        sid_b = r.json()["session"]["id"]
        m = ask(client, sid_b, "退货政策是什么")
        check("KB 隔离：B 店读到自己的政策", "30天" in (m["content"] or "")
              and "7天" not in (m["content"] or ""), str(m["content"])[:100])

        # B 店顾客查演示商城的订单号 → 不存在（跨租户不可见）
        m = ask(client, sid_b, "查一下订单 SO-0002")
        check("订单隔离：B 店查不到演示商城订单", "没有找到" in (m["content"] or ""))
        # B 店顾客查自己的订单 → 正常
        m = ask(client, sid_b, "查一下订单 B-9001")
        check("订单隔离：B 店查到自己的订单",
              (m["card_data"] or {}).get("product") == "B店特产礼盒", str(m["card_data"]))

        # 演示商城顾客查 B 店订单 → 不存在
        r = client.post(f"{BASE}/api/chat/sessions", json={},
                        headers={"X-Widget-Key": DEMO_KEY})
        sid_demo = r.json()["id"]
        m = ask(client, sid_demo, "查一下订单 B-9001")
        check("订单隔离：演示商城查不到 B 店订单", "没有找到" in (m["content"] or ""))

        # ── 3. 运营台越权 ──
        hb = {"Authorization": f"Bearer {login(client, 'bowner', 'bpass123')}"}
        hshop = {"Authorization": f"Bearer {login(client, 'shop', 'shop123')}"}
        hadmin = {"Authorization": f"Bearer {login(client, 'admin', 'admin123')}"}

        r = client.get(f"{BASE}/api/console/sessions", headers=hb)
        ids_b = {i["id"] for i in r.json()["items"]}
        check("运营台：B 店只看到自己会话", r.json()["total"] >= 1 and sid_demo not in ids_b
              and sid_b in ids_b, f"total={r.json()['total']}")

        r = client.get(f"{BASE}/api/console/sessions/{sid_demo}", headers=hb)
        check("运营台：B 店访问演示会话 404", r.status_code == 404)
        r = client.get(f"{BASE}/api/console/sessions/{sid_b}", headers=hshop)
        check("运营台：演示店访问 B 会话 404", r.status_code == 404)
        r = client.get(f"{BASE}/api/console/sessions/{sid_b}", headers=hadmin)
        check("运营台：平台 admin 跨租户可见", r.status_code == 200)

        # KB 管理隔离
        r = client.get(f"{BASE}/api/console/kb/documents", headers=hb)
        titles_b = [d["title"] for d in r.json()["items"]]
        check("KB 管理：B 店只看到自己的文档",
              r.json()["total"] >= 1 and titles_b == ["B店退货政策"], str(titles_b))
    finally:
        cleanup_tenant_b()

    print(f"\n{'='*40}\nS1 租户隔离：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
