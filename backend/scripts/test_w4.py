"""W4 端到端测试：知识库版本化 / 洞察日报 / Eval 黄金集 / 模型设置 / 演示重置。

用法：python scripts/test_w4.py（服务需运行中）
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import Tenant  # noqa: E402
from app.services import kb as kb_svc  # noqa: E402

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


def main():
    client = httpx.Client(timeout=300)
    # SaaS 化：商户操作（KB/洞察/模型设置）用租户账号；Eval/重置用平台 admin
    shop_token = client.post(f"{BASE}/api/auth/login",
                             json={"username": "shop", "password": "shop123"}).json()["token"]
    H = {"Authorization": f"Bearer {shop_token}"}
    admin_token = client.post(f"{BASE}/api/auth/login",
                              json={"username": "admin", "password": "admin123"}).json()["token"]
    HA = {"Authorization": f"Bearer {admin_token}"}
    tid = tenant_id()

    # ── 1. KB：DB 检索 + 版本发布 + 生效期 ──
    with SessionLocal() as db:
        hits = kb_svc.retrieve(db, tid, "退货政策是什么")
        check("KB：检索命中 kb-001", [h["id"] for h in hits][:1] == ["kb-001"], str([h['id'] for h in hits]))

    docs = client.get(f"{BASE}/api/console/kb/documents", headers=H).json()["items"]
    check("KB：文档列表 ≥4 条", len(docs) >= 4, str(len(docs)))
    target = next(d for d in docs if d["code"] == "kb-002")

    r = client.put(f"{BASE}/api/console/kb/documents/{target['id']}", headers=H,
                   json={"title": "运费规则", "category": "policy",
                         "content": "全场订单满59元包邮；偏远地区补运费10元。", })
    check("KB：编辑产生新版本", r.json()["version"] == target["version"] + 1, str(r.json()))
    r = client.post(f"{BASE}/api/console/kb/documents/{target['id']}/publish", headers=H)
    check("KB：发布生效", r.json()["status"] == "published" and r.json()["content"].startswith("全场"))
    with SessionLocal() as db:
        hits = kb_svc.retrieve(db, tid, "包邮吗")
        new_first = hits and "59元" in hits[0]["content"]
        check("KB：检索读到新版本", bool(new_first), str(hits)[:120])

    # 生效期：建一个明天才生效的文档 → 今天检索不到（防旧/未生效政策泄漏）
    r = client.post(f"{BASE}/api/console/kb/documents", headers=H, json={
        "title": "会员日活动", "category": "policy",
        "content": "会员日全场88折优惠活动说明。",
        "effective_from": "2027-01-01"})
    check("KB：未来生效文档创建", r.status_code == 201)
    with SessionLocal() as db:
        hits = kb_svc.retrieve(db, tid, "会员日打折吗")
        check("KB：未到期检索不到", all("88折" not in h["content"] for h in hits), str(hits)[:100])

    # ── 2. 洞察日报 ──
    r = client.post(f"{BASE}/api/console/insights/regenerate", headers=H)
    body = r.json()
    check("洞察：日报生成", r.status_code == 200 and body["status"] == "generated"
          and body["metrics"]["sessions"] >= 0, str(body.get("metrics"))[:100])
    r = client.get(f"{BASE}/api/console/insights", headers=H)
    check("洞察：GET 读同一天", r.json()["status"] == "generated")

    # ── 3. Eval 黄金集（平台 admin）──
    r = client.post(f"{BASE}/api/admin/eval/run", headers=HA, json={})
    body = r.json()
    check("Eval：跑完 8 例", body["total"] == 8, str(body)[:150])
    check(f"Eval：通过率 {body['passed']}/8 ≥ 7", body["passed"] >= 7,
          str([x for x in body["results"] if not x["passed"]]))
    r = client.get(f"{BASE}/api/admin/eval/runs", headers=HA)
    check("Eval：运行历史可查", r.json()["total"] >= 8)

    # ── 4. 模型设置（商户 BYOM）──
    r = client.get(f"{BASE}/api/console/settings/providers", headers=H)
    deepseek = next((p for p in r.json()["items"] if p["name"] == "deepseek"), None)
    check("设置：供应商落库+掩码", deepseek is not None and "****" in deepseek["api_key_masked"])
    r = client.post(f"{BASE}/api/console/settings/providers/{deepseek['id']}/test", headers=H)
    check("设置：连接测试 ok", r.json().get("ok") is True, str(r.json()))
    r = client.put(f"{BASE}/api/console/settings/bindings/triage", headers=H,
                   json={"agent_name": "triage", "provider_id": deepseek["id"],
                         "model_name": "deepseek-chat", "temperature": 0})
    check("设置：绑定 triage", r.status_code == 200)
    r = client.get(f"{BASE}/api/console/settings/bindings", headers=H)
    check("设置：绑定列表回显", any(b["agent_name"] == "triage" for b in r.json()["items"]))

    # ── 5. 演示重置（平台 admin）──
    r = client.post(f"{BASE}/api/admin/demo/reset", headers=HA)
    check("重置：ok", r.json().get("ok") is True)
    r = client.get(f"{BASE}/api/console/sessions", headers=H)
    check("重置：会话清空", r.json()["total"] == 0)

    print(f"\n{'='*40}\nW4 端到端：{PASS} 通过 / {FAIL} 失败")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
