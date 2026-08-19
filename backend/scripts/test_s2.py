"""S2 测试：商户注册 / 双密钥 / 开放 API 推单与会话 / 门户管理 / CSV 导入。

前置：迁移 + seed + uvicorn 运行中。自建自清（租户 C）。
用法：python scripts/test_s2.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.testutil import register_tenant  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AgentRun, ApprovalAction, ApprovalRequest, ChatSession, EmailCode, ExecutedAction,
    KbDocument, KbDocumentVersion, Message, MockOrder, MockProduct, MockShipment,
    Operator, RiskRule, EscalationRule, SessionNote, Tenant, User,
)

BASE = "http://127.0.0.1:8000"
PASS, FAIL = 0, 0
C_NAME = "测试商户C"


def check(name, cond, detail=""):
    global PASS, FAIL
    print(("✅" if cond else "❌") + f" {name}" + (f"  [{detail}]" if detail and not cond else ""))
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (1 if not cond else 0)


def cleanup():
    """清掉测试租户（C）与冒烟残留（SmokeShop）。"""
    with SessionLocal() as db:
        for name in (C_NAME, "SmokeShop"):
            t = db.scalar(select(Tenant).where(Tenant.name == name))
            if t is None:
                continue
            tid = t.id
            sids = [s.id for s in db.scalars(
                select(ChatSession).where(ChatSession.tenant_id == tid)).all()]
            if sids:
                db.execute(delete(ExecutedAction).where(ExecutedAction.session_id.in_(sids)))
                db.execute(delete(ApprovalRequest).where(ApprovalRequest.session_id.in_(sids)))
                db.execute(delete(AgentRun).where(AgentRun.session_id.in_(sids)))
                db.execute(delete(SessionNote).where(SessionNote.session_id.in_(sids)))
                db.execute(delete(Message).where(Message.session_id.in_(sids)))
                db.execute(delete(ChatSession).where(ChatSession.id.in_(sids)))
            db.execute(delete(EscalationRule).where(EscalationRule.tenant_id == tid))
            db.execute(delete(RiskRule).where(RiskRule.tenant_id == tid))
            db.execute(delete(KbDocumentVersion).where(KbDocumentVersion.document_id.in_(
                select(KbDocument.id).where(KbDocument.tenant_id == tid))))
            db.execute(delete(KbDocument).where(KbDocument.tenant_id == tid))
            db.execute(delete(MockShipment).where(MockShipment.tenant_id == tid))
            db.execute(delete(MockOrder).where(MockOrder.tenant_id == tid))
            db.execute(delete(MockProduct).where(MockProduct.tenant_id == tid))
            db.execute(delete(User).where(User.tenant_id == tid))
            db.execute(delete(Operator).where(Operator.tenant_id == tid))
            db.delete(t)
        db.execute(delete(EmailCode).where(EmailCode.email.like("%@testshop.dev")))
        db.commit()


def main():
    cleanup()
    client = httpx.Client(timeout=180)

    # ── 1. 注册（邮箱+验证码） ──
    r, body = register_tenant(client, C_NAME, "c-owner@testshop.dev")
    check("注册：201 + 双密钥", r.status_code == 201
          and body["tenant"]["widget_key"].startswith("pk_")
          and body["tenant"]["api_secret"].startswith("sk_"), str(body)[:150])
    check("注册：返回 token 可用",
          client.get(f"{BASE}/api/auth/me",
                     headers={"Authorization": f"Bearer {body['token']}"}).status_code == 200)
    token = body["token"]
    H = {"Authorization": f"Bearer {token}"}
    SK = {"Authorization": f"Bearer {body['tenant']['api_secret']}"}
    pk = body["tenant"]["widget_key"]

    r = client.post(f"{BASE}/api/portal/email/send-code", json={"email": "c-owner@testshop.dev"})
    check("注册：已注册邮箱再发码 409", r.status_code == 409)
    r = client.post(f"{BASE}/api/portal/register", json={
        "tenant_name": "短", "email": "bad@testshop.dev", "code": "000000", "password": "123"})
    check("注册：弱参数 422", r.status_code == 422)

    # ── 2. 开放 API：推数据 ──
    r = client.post(f"{BASE}/api/v1/products", headers=SK, json={"items": [
        {"sku": "C-001", "name": "C店咖啡豆", "price": 128, "category": "食品"},
        {"sku": "C-002", "name": "C店马克杯", "price": 39},
    ]})
    check("sk_ 推商品：2 建", r.json() == {"created": 2, "updated": 0}, str(r.json()))
    r = client.post(f"{BASE}/api/v1/products", headers=SK, json={"items": [
        {"sku": "C-001", "name": "C店咖啡豆Pro", "price": 158}]})
    check("sk_ 推商品：upsert 更新", r.json() == {"created": 0, "updated": 1}, str(r.json()))

    r = client.post(f"{BASE}/api/v1/orders", headers=SK, json={"items": [
        {"order_no": "C-8001", "sku": "C-001", "user_external_id": "member-42",
         "amount": 158, "status": "paid"},
        {"order_no": "C-8002", "sku": "C-002", "user_external_id": "member-42",
         "amount": 39, "status": "shipped"},
    ]})
    check("sk_ 推订单：2 建", r.json().get("created") == 2, str(r.json()))

    r = client.post(f"{BASE}/api/v1/products", json={"items": []},
                    headers={"Authorization": "Bearer sk_wrong"})
    check("sk_ 错误密钥 401", r.status_code == 401)

    # ── 3. API 会话（商户后端视角）──
    r = client.post(f"{BASE}/api/v1/sessions", headers=SK,
                    json={"user_external_id": "member-42"})
    sid_api = r.json()["session"]["id"]
    check("API 会话：创建+绑会员", r.status_code == 201)
    r = client.post(f"{BASE}/api/v1/sessions/{sid_api}/messages", headers=SK,
                    json={"content": "查一下订单 C-8001"})
    m = r.json()[1]
    check("API 会话：查到推送的订单",
          (m.get("card_data") or {}).get("product") == "C店咖啡豆Pro",
          str(m.get("card_data")))
    r = client.get(f"{BASE}/api/v1/sessions/{sid_api}/messages", headers=SK)
    check("API 会话：拉历史", r.json()["total"] >= 2)

    # 越权：演示商城的 sk 访问 C 的会话 → 404
    r_demo = client.post(f"{BASE}/api/v1/sessions",
                         headers={"Authorization": "Bearer sk_demo000000000000"}, json={})
    check("sk 越权：演示 sk 建 C 查不到的会话（各自独立）", r_demo.status_code == 201)
    r = client.get(f"{BASE}/api/v1/sessions/{sid_api}/messages",
                   headers={"Authorization": "Bearer sk_demo000000000000"})
    check("sk 越权：跨租户会话 404", r.status_code == 404)

    # ── 4. 内部演示通道（pk_ 走 /api/chat/sessions）也能查到推来的数据 ──
    r = client.post(f"{BASE}/api/chat/sessions", json={"user_external_id": "member-42"},
                    headers={"X-Widget-Key": pk})
    check("pk_ 会话：会员识别", r.status_code == 201)
    sid_w = r.json()["id"]
    r = client.post(f"{BASE}/api/chat/sessions/{sid_w}/messages",
                    json={"content": "查一下订单 C-8002"}, timeout=120)
    m = r.json()[1]
    check("pk_ 会话：订单隔离正确", (m.get("card_data") or {}).get("product") == "C店马克杯",
          str(m.get("card_data")))

    # ── 5. 门户管理 ──
    r = client.get(f"{BASE}/api/portal/me", headers=H)
    check("门户 me：统计正确", r.json()["stats"]["orders"] == 2
          and r.json()["stats"]["products"] == 2, str(r.json().get("stats")))
    check("门户 me：已无 embed_code", "embed_code" not in r.json())
    r = client.patch(f"{BASE}/api/portal/brand", headers=H,
                     json={"title": "C店小助手", "theme_color": "#FF6B00"})
    check("品牌设置", r.json()["brand"]["title"] == "C店小助手")

    old_sk = body["tenant"]["api_secret"]
    r = client.post(f"{BASE}/api/portal/keys/rotate", headers=H, json={"which": "api"})
    new_sk = r.json()["api_secret"]
    check("密钥轮换：sk 变了", new_sk != old_sk and new_sk.startswith("sk_"))
    r = client.post(f"{BASE}/api/v1/products", headers={"Authorization": f"Bearer {old_sk}"},
                    json={"items": []})
    check("旧 sk 失效", r.status_code == 401)

    # ── 6. CSV 导入（门户 multipart）──
    csv_products = "sku,name,price,category\nC-003,C店挂耳包,69,食品\n"
    r = client.post(f"{BASE}/api/portal/import", headers=H,
                    files={"file": ("products_c.csv", csv_products.encode("utf-8"),
                                    "text/csv")})
    check("CSV 导入商品", r.status_code == 200 and r.json()["created"] == 1, str(r.json()))
    csv_orders = ("order_no,sku,user_external_id,amount,status\n"
                  "C-8003,C-003,member-42,69,delivered\n")
    r = client.post(f"{BASE}/api/portal/import", headers=H,
                    files={"file": ("orders_c.csv", csv_orders.encode("utf-8"),
                                    "text/csv")})
    check("CSV 导入订单", r.status_code == 200 and r.json()["created"] == 1, str(r.json()))
    r = client.get(f"{BASE}/api/portal/me", headers=H)
    check("导入后统计：3 单 3 品", r.json()["stats"]["orders"] == 3
          and r.json()["stats"]["products"] == 3, str(r.json()["stats"]))

    # ── 7. 平台管理 ──
    admin_token = client.post(f"{BASE}/api/auth/login",
                              json={"username": "admin", "password": "admin123"}).json()["token"]
    r = client.get(f"{BASE}/api/platform/tenants",
                   headers={"Authorization": f"Bearer {admin_token}"})
    names = [t["name"] for t in r.json()["items"]]
    check("平台：租户列表含 C 与演示商城", C_NAME in names and "演示商城" in names, str(names))
    r = client.get(f"{BASE}/api/platform/tenants", headers=H)
    check("平台：商户账号 403", r.status_code == 403)

    cleanup()
    print(f"\n{'='*40}\nS2 门户与开放 API：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
