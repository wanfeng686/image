"""W3 端到端测试：质检回环 / 升级硬规则 / 运营台全流程。

前置：seed + test_w2 已跑（依赖其产生的待审批单）。
用法：python scripts/test_w3.py
"""
import sys
from datetime import timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import AgentRun, ApprovalRequest, ChatSession, Message, MockOrder, Tenant, User  # noqa: E402

BASE = "http://127.0.0.1:8000"
WIDGET_KEY = "pk_demo000000000000"   # 演示商城租户
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    print(("✅" if cond else "❌") + f" {name}" + (f"  [{detail}]" if detail and not cond else ""))
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (1 if not cond else 0)


def tenant_id():
    with SessionLocal() as db:
        return str(db.scalar(select(Tenant).where(Tenant.widget_key == WIDGET_KEY)).id)


def uid(ext):
    with SessionLocal() as db:
        return str(db.scalar(select(User).where(
            User.external_id == ext, User.tenant_id == tenant_id())).id)


def new_session(client, user_id):
    r = client.post(f"{BASE}/api/chat/sessions", json={"user_id": user_id},
                    headers={"X-Widget-Key": WIDGET_KEY})
    r.raise_for_status()
    return r.json()["id"]


def ask(client, sid, q):
    r = client.post(f"{BASE}/api/chat/sessions/{sid}/messages", json={"content": q}, timeout=120)
    r.raise_for_status()
    return r.json()[1]


def runs_of(sid):
    with SessionLocal() as db:
        return [r.agent_name for r in db.scalars(
            select(AgentRun).where(AgentRun.session_id == sid)).all()]


def main():
    demo, wool, vip = uid("demo"), uid("wool"), uid("vip")
    client = httpx.Client(timeout=120)

    # ── 1. 质检：FAQ 链路带 QC 节点落账 ──
    sid = new_session(client, demo)
    m = ask(client, sid, "退货政策是什么")
    names = runs_of(sid)
    check("QC：faq 链路经过 qc 节点", "qc" in names and "[kb-" in (m["content"] or ""), str(names))

    # ── 2. 升级硬规则 ──
    sid2 = new_session(client, demo)
    m = ask(client, sid2, "我要去12315投诉你们！")
    with SessionLocal() as db:
        s = db.get(ChatSession, __import__("uuid").UUID(sid2))
        check("升级：曝光关键词直转", s.status == "escalated" and s.escalated_reason == "keyword",
              f"{s.status}/{s.escalated_reason}")

    sid3 = new_session(client, vip)
    m = ask(client, sid3, "你好呀")
    with SessionLocal() as db:
        s = db.get(ChatSession, __import__("uuid").UUID(sid3))
        check("升级：VIP 直达", s.status == "escalated" and s.escalated_reason == "vip")

    sid4 = new_session(client, demo)
    for _ in range(3):
        ask(client, sid4, "你们客服电话是多少")
    with SessionLocal() as db:
        s = db.get(ChatSession, __import__("uuid").UUID(sid4))
        check("升级：同一问题连问3次", s.status == "escalated" and s.escalated_reason == "repeat",
              f"{s.escalated_reason}")

    # ── 3. 运营台认证 ──
    r = client.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "wrong"})
    check("登录：错密码 401", r.status_code == 401)
    r = client.get(f"{BASE}/api/console/approvals")
    check("鉴权：无 token 401", r.status_code == 401)
    r = client.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = r.json()["token"]
    check("登录：admin OK", r.status_code == 200 and token)
    H = {"Authorization": f"Bearer {token}"}
    r = client.get(f"{BASE}/api/auth/me", headers=H)
    check("ME：回显管理员", r.json()["display_name"] == "管理员")

    # ── 4. 概览与会话 ──
    r = client.get(f"{BASE}/api/console/dashboard/overview?range=7d", headers=H)
    k = r.json()["kpis"]
    check("概览：KPI 齐全", r.status_code == 200 and "sessions" in k and "pending_approvals" in k, str(k))
    r = client.get(f"{BASE}/api/console/sessions?status=escalated", headers=H)
    check("会话列表：升级筛选>0", r.status_code == 200 and r.json()["total"] >= 3)
    esc_sid = r.json()["items"][0]["id"]
    r = client.get(f"{BASE}/api/console/sessions/{sid}", headers=H)
    detail = r.json()
    check("会话详情：轨迹含 input/output", any(run["input"] for run in detail["agent_runs"])
          and len(detail["messages"]) >= 2)
    r = client.post(f"{BASE}/api/console/sessions/{esc_sid}/takeover", headers=H)
    check("接管：taken_over_by 回显", r.json()["session"]["taken_over_by"]["display_name"] is not None)
    r = client.post(f"{BASE}/api/console/sessions/{esc_sid}/notes", headers=H,
                    json={"content": "情绪激动，已安抚"})
    check("备注：201 落库", r.status_code == 201 and r.json()["content"].startswith("情绪"))
    r = client.get(f"{BASE}/api/console/sessions/{sid}/export", headers=H)
    check("导出：JSON 附件", r.status_code == 200 and "agent_runs" in r.text)

    # ── 5. 审批全流程 ──
    r = client.get(f"{BASE}/api/console/approvals?status=pending", headers=H)
    items = r.json()["items"]
    check("审批队列：有待审单", len(items) >= 3, f"n={len(items)}")
    by_order = {i["action_payload"].get("order_no"): i for i in items}

    # 5a. 中额单笔审批 → 立即执行
    req2 = by_order.get("SO-0002")
    r = client.post(f"{BASE}/api/console/approvals/{req2['id']}/approve", headers=H,
                    json={"note": "已核实物流延迟"})
    body = r.json()
    check("审批：单签通过并执行", body["approval"]["status"] == "approved"
          and body["executed_action"]["status"] == "executed", str(body)[:150])
    with SessionLocal() as db:
        o = db.scalar(select(MockOrder).where(MockOrder.order_no == "SO-0002"))
        notified = db.scalars(select(Message).where(Message.session_id == req2["session_id"])).all()
        check("审批后：订单 refunded + 会话收到通知", o.status == "refunded"
              and any("已通过审批" in (m.content or "") for m in notified))

    # 5b. 大额双签 → 两次批准才执行
    req3 = by_order.get("SO-0003")
    r = client.post(f"{BASE}/api/console/approvals/{req3['id']}/remind", headers=H)
    check("催办：ok", r.json().get("ok") is True)
    r = client.post(f"{BASE}/api/console/approvals/{req3['id']}/approve", headers=H, json={})
    b1 = r.json()
    r = client.post(f"{BASE}/api/console/approvals/{req3['id']}/approve", headers=H, json={})
    check("双签：第二次才执行（首次 granted=1）", b1["approval"]["granted_approvals"] == 1
          and b1["executed_action"] is None and r.json()["executed_action"] is not None, str(b1)[:120])

    # 5c. 驳回 → 订单回滚 + 通知
    reqw = by_order.get("SO-1003")
    r = client.post(f"{BASE}/api/console/approvals/{reqw['id']}/reject", headers=H,
                    json={"note": "不符合退款政策"})
    check("驳回：状态 rejected", r.json()["approval"]["status"] == "rejected")
    with SessionLocal() as db:
        notified = db.scalars(select(Message).where(Message.session_id == reqw["session_id"])).all()
        check("驳回：会话收到拒绝通知", any("未通过审核" in (m.content or "") for m in notified))

    # 5d. 幂等：已决单再批 → 409
    r = client.post(f"{BASE}/api/console/approvals/{req2['id']}/approve", headers=H, json={})
    check("幂等：已决单再批 409", r.status_code == 409)

    # 5e. 批量批准 + 超时惰性过期
    sidw = new_session(client, wool)
    ask(client, sidw, "SO-1003 退款，快点")
    r = client.get(f"{BASE}/api/console/approvals?status=pending", headers=H)
    pend = [i for i in r.json()["items"] if i["action_payload"].get("order_no") == "SO-1003"]
    with SessionLocal() as db:
        row = db.get(ApprovalRequest, __import__("uuid").UUID(pend[0]["id"]))
        row.timeout_at -= timedelta(hours=5)   # 手动拨快时钟
        db.commit()
    r = client.get(f"{BASE}/api/console/approvals?status=pending", headers=H)
    gone = all(i["id"] != pend[0]["id"] for i in r.json()["items"])
    r2 = client.get(f"{BASE}/api/console/approvals?status=expired", headers=H)
    check("超时：惰性过期生效", gone and any(i["id"] == pend[0]["id"] for i in r2.json()["items"]))

    print(f"\n{'='*40}\nW3 端到端：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
