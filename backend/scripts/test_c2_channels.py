"""C2 测试：平台目录 / 渠道连接 CRUD / 凭据加密 / RPA 同意门 / Widget 移除。

前置：迁移 b2c3d4e5f6a7 + uvicorn 运行中。自建自清（租户「渠道测试店」）。
用法：python scripts/test_c2_channels.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from scripts.testutil import Tally, register_tenant  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ChannelConnection, ChatSession, EmailCode, EscalationRule, Message, Operator,
    RiskRule, Tenant, User,
)
from app.services import crypto  # noqa: E402

BASE = "http://127.0.0.1:8000"
T_NAME = "渠道测试店"
T_EMAIL = "c2owner@testshop.dev"
t = Tally()


def cleanup():
    with SessionLocal() as db:
        tn = db.scalar(select(Tenant).where(Tenant.name == T_NAME))
        if tn:
            tid = tn.id
            sids = [s.id for s in db.scalars(
                select(ChatSession).where(ChatSession.tenant_id == tid)).all()]
            for s in sids:
                db.execute(delete(Message).where(Message.session_id == s))
            db.execute(delete(ChatSession).where(ChatSession.tenant_id == tid))
            db.execute(delete(ChannelConnection).where(ChannelConnection.tenant_id == tid))
            db.execute(delete(EscalationRule).where(EscalationRule.tenant_id == tid))
            db.execute(delete(RiskRule).where(RiskRule.tenant_id == tid))
            db.execute(delete(User).where(User.tenant_id == tid))
            db.execute(delete(Operator).where(Operator.tenant_id == tid))
            db.delete(tn)
        db.execute(delete(EmailCode).where(EmailCode.email.like("%@testshop.dev")))
        db.commit()


def main():
    cleanup()
    client = httpx.Client(timeout=60)

    # ── 1. 平台目录 ──
    r = client.get(f"{BASE}/api/channel/platforms")
    items = r.json().get("items", [])
    t.check("目录：200 且 7 个平台", r.status_code == 200 and len(items) == 7, str(len(items)))
    pdd = next((p for p in items if p["code"] == "pinduoduo"), {})
    t.check("目录：拼多多 available + 双 mode + 字段 schema",
            pdd.get("available") is True and sorted(pdd.get("modes", [])) == ["official_api", "rpa"]
            and any(f["key"] == "client_secret" for f in pdd.get("api_fields", []))
            and any(f["key"] == "password" for f in pdd.get("rpa_fields", [])))
    tb = next((p for p in items if p["code"] == "taobao"), {})
    t.check("目录：淘宝占位不可用", tb.get("available") is False)

    # ── 2. 注册商户 ──
    r, body = register_tenant(client, T_NAME, T_EMAIL)
    t.check("注册：201", r.status_code == 201)
    H = {"Authorization": f"Bearer {body['token']}"}
    me = client.get(f"{BASE}/api/portal/me", headers=H).json()
    t.check("门户 /me：不再返回 embed_code", "embed_code" not in me)

    # ── 3. 连接校验 ──
    r = client.post(f"{BASE}/api/channel/connections", headers=H, json={
        "platform": "taobao", "mode": "official_api", "credentials": {"client_id": "x"}})
    t.check("连接：未开放平台 422", r.status_code == 422)
    r = client.post(f"{BASE}/api/channel/connections", headers=H, json={
        "platform": "pinduoduo", "mode": "rpa",
        "credentials": {"username": "13800000000", "password": "p@ss"}, "rpa_consent": False})
    t.check("连接：RPA 未勾同意 403", r.status_code == 403)
    r = client.post(f"{BASE}/api/channel/connections", headers=H, json={
        "platform": "pinduoduo", "mode": "official_api",
        "credentials": {"client_id": "", "client_secret": "s"}})
    t.check("连接：缺必填凭据 422", r.status_code == 422)

    # ── 4. 创建 official_api 连接 ──
    r = client.post(f"{BASE}/api/channel/connections", headers=H, json={
        "platform": "pinduoduo", "mode": "official_api",
        "credentials": {"client_id": "cid-abc123456", "client_secret": "csecret-xyz987654"}})
    conn = r.json()
    t.check("连接：创建 201 + pending", r.status_code == 201 and conn.get("status") == "pending", str(conn)[:150])
    t.check("连接：回传凭据已脱敏",
            str(conn.get("credentials_masked", {}).get("client_id", "")).startswith("ci")
            and str(conn.get("credentials_masked", {}).get("client_id", "")).endswith("56")
            and "*" in conn.get("credentials_masked", {}).get("client_id", "")
            and "csecret-xyz987654" not in str(conn), str(conn.get("credentials_masked")))
    cid = conn["id"]

    with SessionLocal() as db:
        row = db.get(ChannelConnection, cid)
        t.check("加密：密文不含明文凭据",
                "cid-abc123456" not in (row.credentials_cipher or "")
                and "csecret-xyz987654" not in (row.credentials_cipher or ""))
        t.check("加密：unseal 可还原", crypto.unseal(row.credentials_cipher).get("client_id") == "cid-abc123456")

    r = client.post(f"{BASE}/api/channel/connections", headers=H, json={
        "platform": "pinduoduo", "mode": "rpa",
        "credentials": {"username": "13800000000", "password": "p@ss"}, "rpa_consent": True})
    t.check("连接：同平台重复 409", r.status_code == 409)

    # ── 5. 测试连接（假凭据 → 平台拒绝/网络错误 → error + last_error） ──
    r = client.post(f"{BASE}/api/channel/connections/{cid}/test", headers=H)
    tb2 = r.json()
    with SessionLocal() as db:
        row = db.get(ChannelConnection, cid)
        t.check("测试：假凭据回写 error + last_error",
                r.status_code == 200 and tb2.get("ok") is False and row.status == "error"
                and bool(row.last_error), str(tb2)[:150])

    # ── 6. 停用/启用/删除 ──
    r = client.patch(f"{BASE}/api/channel/connections/{cid}", headers=H, json={"enabled": False})
    t.check("连接：停用 → disabled", r.json().get("status") == "disabled")
    r = client.patch(f"{BASE}/api/channel/connections/{cid}", headers=H, json={"enabled": True})
    t.check("连接：启用 → pending", r.json().get("status") == "pending")
    r = client.patch(f"{BASE}/api/channel/connections/{cid}", headers=H,
                     json={"credentials": {"access_token": "at-new-token-1"}})
    t.check("连接：补填凭据（脱敏回显）", r.status_code == 200
            and str(r.json().get("credentials_masked", {}).get("access_token", "")).startswith("at")
            and "at-new-token-1" not in str(r.json()))
    with SessionLocal() as db:
        row = db.get(ChannelConnection, cid)
        t.check("加密：合并更新保留旧字段",
                crypto.unseal(row.credentials_cipher).get("client_id") == "cid-abc123456"
                and crypto.unseal(row.credentials_cipher).get("access_token") == "at-new-token-1")
    r = client.delete(f"{BASE}/api/channel/connections/{cid}", headers=H)
    t.check("连接：删除", r.status_code == 200)
    t.check("连接：删除后列表空",
            client.get(f"{BASE}/api/channel/connections", headers=H).json().get("items") == [])

    # ── 7. RPA 连接（consent 落档） ──
    r = client.post(f"{BASE}/api/channel/connections", headers=H, json={
        "platform": "pinduoduo", "mode": "rpa",
        "credentials": {"username": "13800000000", "password": "p@ssw0rd99"}, "rpa_consent": True})
    conn2 = r.json()
    t.check("RPA：创建 201", r.status_code == 201)
    with SessionLocal() as db:
        row = db.get(ChannelConnection, conn2["id"])
        creds = crypto.unseal(row.credentials_cipher)
        t.check("RPA：账密加密 + consent_at 留存",
                creds.get("password") == "p@ssw0rd99" and bool(creds.get("consent_at"))
                and "p@ssw0rd99" not in row.credentials_cipher)

    # ── 8. Widget 移除 / 演示通道保留 ──
    r = client.post(f"{BASE}/api/widget/sessions", headers={"X-Widget-Key": "pk_demo000000000000"})
    t.check("Widget：/api/widget 已下线（404/405）", r.status_code in (404, 405))
    t.check("Widget：静态资源已删",
            client.get(f"{BASE}/embed.js").status_code == 404
            and client.get(f"{BASE}/widget/").status_code == 404
            and client.get(f"{BASE}/test-merchant.html").status_code == 404)
    r = client.post(f"{BASE}/api/chat/sessions", headers={"X-Widget-Key": "pk_demo000000000000"},
                    json={"user_external_id": "demo"})
    t.check("演示页：X-Widget-Key 建会话仍可用（内部演示通道）", r.status_code == 201)

    client.close()
    rc = t.done("C2 渠道连接")
    cleanup()
    sys.exit(rc)


if __name__ == "__main__":
    main()
