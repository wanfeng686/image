"""W2 端到端测试：退款三路 + 归属断言 + 幂等 + 轨迹。

前置：docker compose 起好、scripts/seed.py 跑过、uvicorn 已启动。
用法：python scripts/test_w2.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import AgentRun, ApprovalRequest, ExecutedAction, MockOrder, User  # noqa: E402

BASE = "http://127.0.0.1:8000"
PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    mark = "✅" if cond else "❌"
    print(f"{mark} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    PASS, FAIL = PASS + (1 if cond else 0), FAIL + (1 if not cond else 0)


def uid(ext: str) -> str:
    with SessionLocal() as db:
        return str(db.scalar(select(User).where(User.external_id == ext)).id)


def new_session(client: httpx.Client, user_id: str) -> str:
    r = client.post(f"{BASE}/api/chat/sessions", json={"user_id": user_id})
    r.raise_for_status()
    return r.json()["id"]


def ask(client: httpx.Client, sid: str, q: str) -> dict:
    r = client.post(f"{BASE}/api/chat/sessions/{sid}/messages", json={"content": q}, timeout=120)
    r.raise_for_status()
    return r.json()[1]  # agent 消息


def order_status(order_no: str) -> str:
    with SessionLocal() as db:
        return db.scalar(select(MockOrder).where(MockOrder.order_no == order_no)).status


def main():
    demo, wool = uid("demo"), uid("wool")
    client = httpx.Client(timeout=120)

    # ── 1. FAQ 回归（W1 能力不回退）──
    sid = new_session(client, demo)
    m = ask(client, sid, "退货政策是什么")
    check("FAQ：带引用回答", "[kb-" in (m["content"] or "") and m["agent_source"] == "knowledge",
          str(m)[:120])

    # ── 2. 查单（正常 + 查无 + IDOR）──
    m = ask(client, sid, "查一下订单 SO-0002 的物流")
    card = m["card_data"] or {}
    check("查单：订单卡片", m["content_type"] == "card" and card.get("order_no") == "SO-0002"
          and card.get("product") == "无线耳机X3" and m["agent_source"] == "order", str(card))

    m = ask(client, sid, "查一下订单 SO-9999")
    check("查单：不存在 → 未找到", "没有找到" in (m["content"] or "") and m["card_data"] is None)

    m = ask(client, sid, "帮我查订单 SO-2001")   # 这是 VIP 用户的订单
    check("IDOR：查他人订单被归属断言拦截", "没有找到" in (m["content"] or ""),
          f'content={m["content"]}')

    # ── 3. 退款三路 ──
    # 小额 49（保温杯，已签收）→ 自动执行
    m = ask(client, sid, "SO-0001 我要退款，不想要了")
    card = m["card_data"] or {}
    check("小额退款：自动通过", card.get("status") == "auto_approved" and m["agent_source"] == "resolution",
          str(card))
    check("小额退款：订单状态 refunded", order_status("SO-0001") == "refunded")
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.external_id == "demo"))
        check("小额退款：30 天累计 +49", float(u.total_refund_30d) == 49.0, str(u.total_refund_30d))

    # 中额 299（耳机）→ 1 人审批
    m = ask(client, sid, "SO-0002 太慢了我要退款")
    card = m["card_data"] or {}
    check("中额退款：进审批队列", card.get("status") == "pending_approval" and card.get("risk_level") == "medium"
          and card.get("required_approvals") == 1, str(card))

    # 幂等：同会话同单再申请 → 不新建
    m2 = ask(client, sid, "SO-0002 我再说一遍，退款！")
    with SessionLocal() as db:
        reqs = db.scalars(select(ApprovalRequest).where(ApprovalRequest.session_id == sid)).all()
        n = len([r for r in reqs if r.action_payload.get("order_no") == "SO-0002"])
    check("幂等：重复申请不新建审批", n == 1 and "已在审核" in (m2["content"] or ""), f"count={n}")

    # 大额 4999（手机）→ 双签
    sid3 = new_session(client, demo)
    m = ask(client, sid3, "SO-0003 手机有质量问题，退款")
    card = m["card_data"] or {}
    check("大额退款：双签（required=2）", card.get("risk_level") == "high" and card.get("required_approvals") == 2,
          str(card))

    # ── 4. 拆单旁路（S2）：羊毛党累计已超限，小额也走双签 ──
    sidw = new_session(client, wool)
    m = ask(client, sidw, "退我最近的订单")
    card = m["card_data"] or {}
    check("拆单防御：累计超限小额也 high", card.get("risk_level") == "high" and card.get("required_approvals") == 2,
          str(card))

    # ── 5. 轨迹与落账 ──
    with SessionLocal() as db:
        runs = db.scalars(select(AgentRun).where(AgentRun.session_id == sid3)).all()
        names = [r.agent_name for r in runs]
        check("轨迹：agent_runs 三类节点落账",
              "triage" in names and "resolution" in names and "supervisor" in names, str(names))
        ex = db.scalars(select(ExecutedAction)).all()
        check("资金流水：executed_actions 有记录", len(ex) >= 1)

    # ── 6. rate / escalate ──
    r = client.post(f"{BASE}/api/chat/sessions/{sid3}/rate", json={"rating": 1})
    check("评价接口", r.status_code == 200 and r.json()["satisfaction"] == 1)
    r = client.post(f"{BASE}/api/chat/sessions/{sid3}/escalate")
    check("转人工铁律：直转", r.status_code == 200 and r.json()["status"] == "escalated"
          and r.json()["escalated_reason"] == "user_request")

    print(f"\n{'='*40}\nW2 端到端：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
