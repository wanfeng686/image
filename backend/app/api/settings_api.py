"""模型设置 API（P7-lite）：供应商 CRUD + 连接测试 + Agent 绑定。
SaaS 化：BYOK 租户隔离——各商户配自己的模型供应商（api_key AES-GCM 密文）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_operator
from app.core.db import get_db
from app.models import AgentModelBinding, ModelProvider, Operator
from app.services import crypto

router = APIRouter(prefix="/api/console/settings", tags=["settings"],
                   dependencies=[Depends(get_current_operator)])


def _mask_key(p: ModelProvider) -> str | None:
    """解密后脱敏（对密文做掩码没有意义）。"""
    plain = crypto.plain_api_key(p.api_key)
    return crypto.mask(plain) if plain else None


def _tf(op: Operator):
    return None if op.tenant_id is None else ModelProvider.tenant_id == op.tenant_id


def _get_scoped_provider(db: Session, op: Operator, provider_id: int) -> ModelProvider:
    p = db.get(ModelProvider, provider_id)
    if p is None:
        raise HTTPException(404, "provider not found")
    if op.tenant_id is not None and p.tenant_id != op.tenant_id:
        raise HTTPException(404, "provider not found")
    return p


class ProviderRequest(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None


class BindingRequest(BaseModel):
    agent_name: str
    provider_id: int
    model_name: str
    temperature: float | None = None


@router.get("/providers")
def list_providers(db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    query = select(ModelProvider)
    if (tf := _tf(op)) is not None:
        query = query.where(tf)
    rows = db.scalars(query).all()
    return {"items": [{"id": p.id, "name": p.name, "base_url": p.base_url,
                       "api_key_masked": _mask_key(p), "enabled": p.enabled,
                       "last_test_status": p.last_test_status}
                      for p in rows], "total": len(rows)}


@router.post("/providers", status_code=201)
def create_provider(body: ProviderRequest, db: Session = Depends(get_db),
                    op: Operator = Depends(get_current_operator)):
    if op.tenant_id is None:
        raise HTTPException(403, "平台账号无租户上下文，请用商户账号配置模型")
    if db.scalar(select(ModelProvider).where(
            ModelProvider.tenant_id == op.tenant_id, ModelProvider.name == body.name)):
        raise HTTPException(409, "供应商已存在")
    p = ModelProvider(tenant_id=op.tenant_id, name=body.name,
                      base_url=body.base_url,
                      api_key=crypto.seal_api_key(body.api_key) if body.api_key else None)
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"id": p.id, "name": p.name}


@router.put("/providers/{provider_id}")
def update_provider(provider_id: int, body: ProviderRequest, db: Session = Depends(get_db),
                    op: Operator = Depends(get_current_operator)):
    p = _get_scoped_provider(db, op, provider_id)
    p.base_url = body.base_url
    if body.api_key:  # 不传 key = 保留原值（掩码回显场景）
        p.api_key = crypto.seal_api_key(body.api_key)
    db.commit()
    return {"id": p.id, "name": p.name}


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db),
                    op: Operator = Depends(get_current_operator)):
    p = _get_scoped_provider(db, op, provider_id)
    if db.scalar(select(AgentModelBinding).where(AgentModelBinding.provider_id == provider_id)):
        raise HTTPException(409, "仍有 Agent 绑定该供应商")
    db.delete(p)
    db.commit()
    return {"ok": True}


class TestRequest(BaseModel):
    model: str | None = None  # 不传 = 该供应商任一绑定模型，兜底 deepseek-chat


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int, body: TestRequest | None = None,
                  db: Session = Depends(get_db),
                  op: Operator = Depends(get_current_operator)):
    """连接测试：一次 1-token 级调用。model 优先级：请求体 > 绑定 > deepseek-chat。"""
    from openai import OpenAI

    p = _get_scoped_provider(db, op, provider_id)
    model = (body.model if body and body.model else None) or db.scalar(
        select(AgentModelBinding.model_name).where(
            AgentModelBinding.provider_id == p.id).limit(1)) or "deepseek-chat"
    try:
        client = OpenAI(api_key=crypto.plain_api_key(p.api_key) or "not-needed",
                        base_url=p.base_url, timeout=15)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "hi"}], max_tokens=1)
        p.last_test_status = "ok"
        db.commit()
        return {"ok": True, "model": model, "sample": (resp.choices[0].message.content or "")[:20]}
    except Exception as exc:  # noqa: BLE001
        p.last_test_status = "failed"
        db.commit()
        return {"ok": False, "model": model, "error": str(exc)[:150]}


@router.get("/bindings")
def list_bindings(db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    query = select(AgentModelBinding, ModelProvider).join(
        ModelProvider, AgentModelBinding.provider_id == ModelProvider.id)
    if op.tenant_id is not None:
        query = query.where(AgentModelBinding.tenant_id == op.tenant_id)
    rows = db.execute(query).all()
    return {"items": [{"agent_name": b.agent_name, "provider": p.name,
                       "model_name": b.model_name,
                       "temperature": float(b.temperature) if b.temperature is not None else None}
                      for b, p in rows]}


@router.put("/bindings/{agent_name}")
def upsert_binding(agent_name: str, body: BindingRequest, db: Session = Depends(get_db),
                   op: Operator = Depends(get_current_operator)):
    if op.tenant_id is None:
        raise HTTPException(403, "平台账号无租户上下文，请用商户账号配置绑定")
    p = db.get(ModelProvider, body.provider_id)
    if p is None or p.tenant_id != op.tenant_id:
        raise HTTPException(404, "provider not found")
    row = db.scalar(select(AgentModelBinding).where(
        AgentModelBinding.tenant_id == op.tenant_id,
        AgentModelBinding.agent_name == agent_name))
    if row is None:
        row = AgentModelBinding(tenant_id=op.tenant_id, agent_name=agent_name)
        db.add(row)
    row.provider_id = body.provider_id
    row.model_name = body.model_name
    row.temperature = body.temperature if body.temperature is not None else 0
    db.commit()
    return {"agent_name": agent_name, "provider_id": body.provider_id, "model_name": body.model_name}
