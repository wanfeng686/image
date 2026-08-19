"""C6：商户自带模型（BYOK）+ 提示词模板——端到端测试。

覆盖：未配置聊天 409 闸门（同步+SSE）/ 首次配置 422 / 配置落库密文 /
五 Agent 绑定 / 聊天恢复 / 人设模板覆盖真实驱 LLM / 超长 422 / 清除 /
探活 / 停用再恢复。
前置：服务器 127.0.0.1:8000、MAIL_DEV_MODE=True、.env 有可用 DeepSeek key。
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AgentModelBinding, AgentRun, ChatSession, EmailCode, EscalationRule,
    KbDocument, KbDocumentVersion, Message, ModelProvider, Operator, RiskRule,
    Tenant, User,
)
from app.services import crypto  # noqa: E402
from scripts.testutil import Tally, register_tenant  # noqa: E402
import datetime  # noqa: E402

BASE = "http://127.0.0.1:8000"
T_NAME = "C6模型测试店"
T_EMAIL = "c6-owner@testshop.dev"

CUSTOM_TEMPLATE = """你是C6测试店的专属客服。严格遵守：
1. 只能依据【知识片段】回答，禁止编造。
2. 回答控制在3句话以内。
3. 每个回答的末尾必须加上标记【C6】。"""


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
            db.execute(delete(EscalationRule).where(EscalationRule.tenant_id == tid))
            db.execute(delete(RiskRule).where(RiskRule.tenant_id == tid))
            db.execute(delete(KbDocumentVersion).where(KbDocumentVersion.document_id.in_(
                select(KbDocument.id).where(KbDocument.tenant_id == tid))))
            db.execute(delete(KbDocument).where(KbDocument.tenant_id == tid))
            db.execute(delete(User).where(User.tenant_id == tid))
            db.execute(delete(AgentModelBinding).where(AgentModelBinding.tenant_id == tid))
            db.execute(delete(ModelProvider).where(ModelProvider.tenant_id == tid))
            db.execute(delete(Operator).where(Operator.tenant_id == tid))
            db.delete(tn)
        db.execute(delete(EmailCode).where(EmailCode.email == T_EMAIL))
        db.commit()


def seed_kb(tenant_id):
    """给测试店种 1 篇 KB（45 天政策），供模板驱动验证。"""
    with SessionLocal() as db:
        doc = KbDocument(tenant_id=tenant_id, code="kb-001", title="退货政策",
                         status="published", created_by="c6test")
        db.add(doc)
        db.flush()
        ver = KbDocumentVersion(document_id=doc.id, version=1,
                                content="本店特别政策：所有商品支持45天无理由退货。",
                                effective_from=datetime.date.today())
        db.add(ver)
        db.flush()
        doc.current_version_id = ver.id
        db.commit()


def main():
    cleanup()
    t = Tally()
    client = httpx.Client(timeout=180)

    # ── 1. 注册（不带 AI）→ 默认态 ──
    r, body = register_tenant(client, T_NAME, T_EMAIL)
    t.check("注册：201", r.status_code == 201)
    H = {"Authorization": f"Bearer {body['token']}"}
    pk = body["tenant"]["widget_key"]

    r = client.get(f"{BASE}/api/portal/ai-config", headers=H)
    d = r.json()
    t.check("默认态：ready=False / provider=None", r.status_code == 200
          and d["ready"] is False and d["provider"] is None, str(d)[:150])
    slot = d["prompts"]["knowledge_system"]
    t.check("默认态：平台模板就位（默认=生效 / 无覆盖）",
          slot["default"].startswith("你是电商平台的客服知识助手") and slot["override"] is None
          and slot["effective"] == slot["default"])

    # ── 2. 未配置 → 聊天被 409 闸门拦（同步 + SSE） ──
    sid = client.post(f"{BASE}/api/chat/sessions", json={},
                      headers={"X-Widget-Key": pk}).json()["id"]
    r = client.post(f"{BASE}/api/chat/sessions/{sid}/messages", json={"content": "退货政策是什么"})
    t.check("闸门：同步聊天 409", r.status_code == 409
          and "AI_MODEL_NOT_CONFIGURED" in str(r.json().get("detail")), str(r.status_code))
    r = client.post(f"{BASE}/api/chat/sessions/{sid}/messages/stream", json={"content": "你好"})
    t.check("闸门：SSE 聊天 409", r.status_code == 409, str(r.status_code))

    # ── 3. 首次配置校验 ──
    r = client.put(f"{BASE}/api/portal/ai-config", headers=H,
                   json={"base_url": settings.llm_base_url, "api_key": settings.llm_api_key})
    t.check("首次配置缺 model → 422", r.status_code == 422, str(r.status_code))

    # ── 4. 完整配置 → 就绪 + 密文落库 ──
    r = client.put(f"{BASE}/api/portal/ai-config", headers=H, json={
        "base_url": settings.llm_base_url, "api_key": settings.llm_api_key,
        "model": settings.llm_model})
    d = r.json()
    t.check("配置：200 + ready=True", r.status_code == 200 and d["ready"] is True, str(d)[:150])
    masked = (d["provider"] or {}).get("api_key_masked", "")
    t.check("配置：key 掩码回显", "*" in masked and settings.llm_api_key not in masked, masked)

    tid = None
    with SessionLocal() as db:
        tn = db.scalar(select(Tenant).where(Tenant.name == T_NAME))
        tid = tn.id
        prov = db.scalar(select(ModelProvider).where(ModelProvider.tenant_id == tid))
        n_bind = len(db.scalars(select(AgentModelBinding).where(
            AgentModelBinding.tenant_id == tid)).all())
        t.check("落库：api_key 密文（≠明文，可解回）",
              prov.api_key != settings.llm_api_key
              and crypto.plain_api_key(prov.api_key) == settings.llm_api_key)
        t.check("落库：五 Agent 全量绑定", n_bind == 5, str(n_bind))

    # ── 5. 聊天恢复（真实 LLM） ──
    seed_kb(tid)
    r = client.post(f"{BASE}/api/chat/sessions/{sid}/messages",
                    json={"content": "退货政策是什么"}, timeout=180)
    m = r.json()[1] if r.status_code == 201 else {}
    t.check("聊天恢复：200 + 命中自家 KB（45天）", r.status_code == 201
          and "45天" in (m.get("content") or ""), str(m.get("content"))[:120])

    # ── 6. 人设模板覆盖真实驱动 LLM ──
    r = client.put(f"{BASE}/api/portal/ai-config", headers=H,
                   json={"knowledge_system": CUSTOM_TEMPLATE})
    d = r.json()
    t.check("模板：保存后 override/effective 生效", r.status_code == 200
          and d["prompts"]["knowledge_system"]["override"] == CUSTOM_TEMPLATE
          and d["prompts"]["knowledge_system"]["effective"] == CUSTOM_TEMPLATE)
    sid2 = client.post(f"{BASE}/api/chat/sessions", json={},
                       headers={"X-Widget-Key": pk}).json()["id"]
    r = client.post(f"{BASE}/api/chat/sessions/{sid2}/messages",
                    json={"content": "退货政策是什么"}, timeout=180)
    m2 = r.json()[1] if r.status_code == 201 else {}
    t.check("模板：LLM 回复带自定义标记【C6】", r.status_code == 201
          and "【C6】" in (m2.get("content") or ""), str(m2.get("content"))[:150])

    # ── 7. 模板校验：超长 422 / 空串清除 ──
    r = client.put(f"{BASE}/api/portal/ai-config", headers=H,
                   json={"knowledge_system": "x" * 4001})
    t.check("模板：超长 422", r.status_code == 422, str(r.status_code))
    r = client.put(f"{BASE}/api/portal/ai-config", headers=H,
                   json={"knowledge_system": ""})
    d = r.json()
    t.check("模板：空串清除回默认", d["prompts"]["knowledge_system"]["override"] is None
          and d["prompts"]["knowledge_system"]["effective"]
          == d["prompts"]["knowledge_system"]["default"])

    # ── 8. 探活 / 停用 / 恢复 ──
    r = client.post(f"{BASE}/api/portal/ai-config/test", headers=H,
                    json={"model": settings.llm_model})
    t.check("探活：ok=True", r.json().get("ok") is True, str(r.json())[:150])
    r = client.put(f"{BASE}/api/portal/ai-config", headers=H, json={"disable": True})
    t.check("停用：ready=False", r.json()["ready"] is False)
    r = client.post(f"{BASE}/api/chat/sessions/{sid}/messages", json={"content": "你好"})
    t.check("停用后：聊天再次 409", r.status_code == 409, str(r.status_code))
    r = client.put(f"{BASE}/api/portal/ai-config", headers=H,
                   json={"model": settings.llm_model})  # 已有供应商+key：只传 model 即恢复
    t.check("恢复：ready=True（key 留空保留）", r.json()["ready"] is True)

    cleanup()
    client.close()
    return t.done("C6 BYOK+提示词模板")


if __name__ == "__main__":
    sys.exit(main())
