"""S3 测试：可嵌入 Widget 链路（静态资源 / boot 品牌 / X-Widget-Origin / SSE 流）。

用法：python scripts/test_s3.py（服务运行中）
"""
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.testutil import register_tenant  # noqa: E402

BASE = "http://127.0.0.1:8000"
DEMO_KEY = "pk_demo000000000000"
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    print(("✅" if cond else "❌") + f" {name}" + (f"  [{detail}]" if detail and not cond else ""))
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (1 if not cond else 0)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    frames = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        event, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data += line[6:]
        frames.append((event, json.loads(data) if data else {}))
    return frames


def main():
    client = httpx.Client(timeout=180)

    # ── 1. 静态资源 ──
    r = client.get(f"{BASE}/embed.js")
    check("embed.js 可加载", r.status_code == 200 and "data-key" in r.text
          and "ssw-launcher" in r.text)
    r = client.get(f"{BASE}/widget/", params={"key": DEMO_KEY, "embed": "1"})
    check("Widget 聊天页可加载", r.status_code == 200 and "X-Widget-Origin" in r.text)
    r = client.get(f"{BASE}/test-merchant.html")
    check("模拟商户页可加载", r.status_code == 200 and "embed.js" in r.text)
    r = client.get(f"{BASE}/")
    check("落地页可加载", r.status_code == 200 and "portal.html" in r.text)
    r = client.get(f"{BASE}/demo.html")
    check("演示聊天页可加载", r.status_code == 200 and "pk_demo000000000000" in r.text)

    # ── 2. boot 品牌返回 ──
    r = client.get(f"{BASE}/api/widget/boot", params={"key": DEMO_KEY})
    b = r.json()
    check("boot：返回品牌", r.status_code == 200 and b["brand"]["title"]
          and b["brand"]["theme_color"].startswith("#"))
    r = client.get(f"{BASE}/api/widget/boot", params={"key": "pk_nope"})
    check("boot：坏密钥 401", r.status_code == 401)

    # ── 3. X-Widget-Origin 声明（iframe 场景：浏览器 Origin 是平台，声明头才是商户页）──
    # 用注册租户配置白名单验证
    from sqlalchemy import delete, select
    from app.core.db import SessionLocal
    from app.models import (AgentRun, ChatSession, EscalationRule, Message,
                            Operator, RiskRule, Tenant, User)

    def purge_tenant(name_or_key, by="name"):
        with SessionLocal() as db:
            t = db.scalar(select(Tenant).where(
                Tenant.name == name_or_key if by == "name" else Tenant.widget_key == name_or_key))
            if t is None:
                return
            tid = t.id
            sids = [s.id for s in db.scalars(
                select(ChatSession).where(ChatSession.tenant_id == tid)).all()]
            if sids:
                db.execute(delete(AgentRun).where(AgentRun.session_id.in_(sids)))
                db.execute(delete(Message).where(Message.session_id.in_(sids)))
                db.execute(delete(ChatSession).where(ChatSession.id.in_(sids)))
            db.execute(delete(EscalationRule).where(EscalationRule.tenant_id == tid))
            db.execute(delete(RiskRule).where(RiskRule.tenant_id == tid))
            db.execute(delete(User).where(User.tenant_id == tid))
            db.execute(delete(Operator).where(Operator.tenant_id == tid))
            db.delete(t)
            db.commit()

    purge_tenant("Widget白名单测试")

    _, reg = register_tenant(client, "Widget白名单测试", "wdgt@testshop.dev", "pass123")
    H = {"Authorization": f"Bearer {reg['token']}"}
    pk = reg["tenant"]["widget_key"]
    client.put(f"{BASE}/api/portal/origins", headers=H,
               json={"origins": ["https://merchant.example"]})

    r = client.post(f"{BASE}/api/widget/sessions", json={},
                    headers={"X-Widget-Key": pk, "X-Widget-Origin": "https://merchant.example",
                             "Origin": BASE})   # 浏览器 Origin 是平台域名
    check("iframe 场景：声明头命中白名单放行（浏览器 Origin 无关）", r.status_code == 201)
    r = client.post(f"{BASE}/api/widget/sessions", json={},
                    headers={"X-Widget-Key": pk, "X-Widget-Origin": "https://evil.example"})
    check("iframe 场景：声明头不在白名单 403", r.status_code == 403)

    # ── 4. Widget 会话全链路（演示商城：FAQ 流式 + 引用 + QC）──
    r = client.post(f"{BASE}/api/widget/sessions", json={},
                    headers={"X-Widget-Key": DEMO_KEY, "X-Widget-Origin": "http://any.local"})
    sid = r.json()["session"]["id"]
    brand = r.json()["brand"]
    check("Widget 会话：品牌随会话返回", brand["title"].startswith("演示商城"))

    r = client.post(f"{BASE}/api/chat/sessions/{sid}/messages/stream",
                    json={"content": "退货政策是什么"}, timeout=120)
    frames = parse_sse(r.text)
    events = [e for e, _ in frames]
    deltas = "".join(p.get("delta", "") for e, p in frames if e == "message_delta")
    check("SSE：协议事件齐全", all(e in events for e in
          ("turn_start", "message_delta", "message_completed", "turn_end")), str(events))
    check("SSE：FAQ 流式回答带引用", "[kb-" in deltas, deltas[:100])
    completed = [p for e, p in frames if e == "message_completed"]
    check("SSE：message_completed 定格", completed and completed[0]["message"]["content"] == deltas)

    # 清理白名单测试租户（连同其会话/用户/规则）
    purge_tenant(pk, by="key")

    print(f"\n{'='*40}\nS3 Widget 链路：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
