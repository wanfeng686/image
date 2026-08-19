"""模型网关-lite（M12）：Agent 级模型绑定路由（SaaS 化 BYOK）。

统一 OpenAI 兼容协议（DESIGN 决策）：一个客户端协议接所有主流模型。
BYOK（C6）：商户必须自带模型供应商（model_providers，api_key AES-GCM 密文），
未配置的租户由 tenant_ready 闸门在对话入口拦截；平台默认客户端仅作为
"有供应商但绑定缺失"时的容错路由，不再是无配置租户的免费兜底。
降级链/限流/成本记账为生产增强项，见 README Roadmap。
"""
import uuid

from openai import OpenAI
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal

_default_client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


def _provider_key(provider) -> str:
    """供应商 api_key：密文解封；历史明文/解密失败按原值容错（不阻断）。"""
    from app.services import crypto

    return crypto.plain_api_key(provider.api_key) or "not-needed"


def _resolve(agent: str | None, tenant_id: uuid.UUID | None = None) -> tuple[OpenAI, str, float | None]:
    """按 (租户, agent) 查绑定表；查不到或库不可用 → 默认供应商（永不因配置缺失挂掉）。"""
    if agent:
        try:
            from app.models import AgentModelBinding, ModelProvider

            with SessionLocal() as db:
                row = db.execute(
                    select(AgentModelBinding, ModelProvider)
                    .join(ModelProvider, AgentModelBinding.provider_id == ModelProvider.id)
                    .where(AgentModelBinding.agent_name == agent,
                           AgentModelBinding.tenant_id == tenant_id,
                           ModelProvider.enabled)
                ).first()
                if row:
                    binding, provider = row
                    client = OpenAI(api_key=_provider_key(provider),
                                    base_url=provider.base_url)
                    temp = float(binding.temperature) if binding.temperature is not None else None
                    return client, binding.model_name, temp
        except Exception:  # noqa: BLE001 —— 配置层失败回退默认
            pass
    return _default_client, settings.llm_model, None


def tenant_ready(db, tenant_id: uuid.UUID | None) -> bool:
    """BYOK 闸门：租户存在启用的模型供应商即视为就绪。

    keyless 供应商（本地 Ollama 等自有端点）也算就绪——流量走商户自己的
    base_url，不构成对平台默认模型的蹭用。无租户上下文（平台内部任务）放行。
    """
    if tenant_id is None:
        return True
    try:
        from app.models import ModelProvider

        row = db.execute(
            select(ModelProvider.id).where(
                ModelProvider.tenant_id == tenant_id,
                ModelProvider.enabled).limit(1)
        ).first()
        return row is not None
    except Exception:  # noqa: BLE001 —— 查库失败宁可放行（不因闸门误杀）
        return True


def chat(messages: list[dict], model: str | None = None,
         temperature: float | None = None, agent: str | None = None,
         tenant_id: uuid.UUID | None = None) -> str:
    """调用 LLM，返回纯文本回复。(tenant_id, agent) 决定走哪个绑定模型。"""
    client, bound_model, bound_temp = _resolve(agent, tenant_id)
    temp = temperature if temperature is not None else (bound_temp if bound_temp is not None else 0.3)
    resp = client.chat.completions.create(
        model=model or bound_model,
        messages=messages,
        temperature=temp,
    )
    return resp.choices[0].message.content


def chat_stream(messages: list[dict], model: str | None = None,
                temperature: float | None = None, agent: str | None = None,
                tenant_id: uuid.UUID | None = None):
    """流式版本：LLM 生成一点就吐一点（生成器，逐块 yield）。"""
    client, bound_model, bound_temp = _resolve(agent, tenant_id)
    temp = temperature if temperature is not None else (bound_temp if bound_temp is not None else 0.3)
    resp = client.chat.completions.create(
        model=model or bound_model,
        messages=messages,
        temperature=temp,
        stream=True,
    )
    for chunk in resp:
        delta = chunk.choices[0].delta.content
        if delta:  # 有些 chunk 只有角色信息没有内容，跳过
            yield delta
