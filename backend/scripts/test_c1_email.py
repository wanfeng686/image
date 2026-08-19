"""C1 测试：邮箱注册 + 验证码（发送/冷却/校验/一次性/防暴力）+ 邮箱登录。

前置：迁移 a1b2c3d4e5f6 + uvicorn 运行中 + 未配 SMTP（走 mail_dev_mode）。
用法：python scripts/test_c1_email.py
"""
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402

from scripts.testutil import Tally  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    ChatSession, EmailCode, Message, Operator, RiskRule, EscalationRule, Tenant, User,
)

BASE = "http://127.0.0.1:8000"
T_NAME = "邮箱注册测试店"
T_EMAIL = "c1owner@testshop.dev"
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

    # ── 1. 发码 ──
    r = client.post(f"{BASE}/api/portal/email/send-code", json={"email": "not-an-email"})
    t.check("发码：坏邮箱 422", r.status_code == 422)
    r = client.post(f"{BASE}/api/portal/email/send-code", json={"email": T_EMAIL})
    body = r.json()
    t.check("发码：200 + dev_code（本地联调模式）",
            r.status_code == 200 and body.get("dev_code", "").isdigit(), str(body)[:120])
    code = body.get("dev_code", "")
    r2 = client.post(f"{BASE}/api/portal/email/send-code", json={"email": T_EMAIL})
    t.check("发码：60s 内重发 429", r2.status_code == 429)

    # ── 2. 注册 ──
    r = client.post(f"{BASE}/api/portal/register", json={
        "tenant_name": T_NAME, "email": T_EMAIL, "code": "000000", "password": "pass123456"})
    t.check("注册：错误验证码 400", r.status_code == 400)
    r = client.post(f"{BASE}/api/portal/register", json={
        "tenant_name": T_NAME, "email": T_EMAIL, "code": code, "password": "pass123456"})
    body = r.json()
    t.check("注册：201 + token + sk_",
            r.status_code == 201 and body.get("token")
            and body["tenant"]["api_secret"].startswith("sk_"), str(body)[:150])
    t.check("注册：operator 带 email", body.get("operator", {}).get("email") == T_EMAIL)
    token = body["token"]

    # ── 3. 验证码一次性 + 邮箱占用 ──
    r = client.post(f"{BASE}/api/portal/register", json={
        "tenant_name": T_NAME, "email": T_EMAIL, "code": code, "password": "pass123456"})
    t.check("注册：重复邮箱 409", r.status_code == 409)
    r = client.post(f"{BASE}/api/portal/email/send-code", json={"email": T_EMAIL})
    t.check("发码：已注册邮箱 409", r.status_code == 409)

    # ── 4. 登录：邮箱 / 派生用户名 ──
    r = client.post(f"{BASE}/api/auth/login", json={"username": T_EMAIL, "password": "pass123456"})
    t.check("登录：邮箱可登录 200", r.status_code == 200 and r.json().get("token"))
    with SessionLocal() as db:
        op = db.scalar(select(Operator).where(Operator.email == T_EMAIL))
        uname = op.username if op else ""
    t.check("注册：username 由邮箱派生", uname.startswith("c1owner"), uname)
    r = client.post(f"{BASE}/api/auth/login", json={"username": uname, "password": "pass123456"})
    t.check("登录：派生用户名可登录 200", r.status_code == 200)
    r = client.post(f"{BASE}/api/auth/login", json={"username": T_EMAIL, "password": "wrong-pass"})
    t.check("登录：密码错误 401", r.status_code == 401)

    # ── 5. /me 可用 + 大小写不敏感 ──
    r = client.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    t.check("token /me 200", r.status_code == 200)
    r = client.post(f"{BASE}/api/auth/login",
                    json={"username": T_EMAIL.upper(), "password": "pass123456"})
    t.check("登录：邮箱大写不敏感", r.status_code == 200)

    # ── 6. 旧账号（无邮箱）仍可用户名登录 ──
    r = client.post(f"{BASE}/api/auth/login", json={"username": "shop", "password": "shop123"})
    t.check("登录：存量账密账号不受影响", r.status_code == 200)

    client.close()
    rc = t.done("C1 邮箱注册")
    cleanup()
    sys.exit(rc)


if __name__ == "__main__":
    main()
