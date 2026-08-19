import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ModelProvider(Base):
    """模型供应商（BYOM）：任意 OpenAI 兼容端点即插即用，租户独立配置。

    W4 简化：api_key 明文存库（演示项目，README 已声明）；生产应 AES-GCM 加密。
    """
    __tablename__ = "model_providers"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_providers_tenant_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)          # deepseek|openai|zhipu|local_ollama
    base_url: Mapped[str] = mapped_column(String(256), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(256))                     # 本地 Ollama 可为空
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_test_status: Mapped[str | None] = mapped_column(String(16))             # ok|failed
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentModelBinding(Base):
    """Agent → 模型绑定（网关路由表）：未配置的 Agent 走 .env 默认供应商。"""
    __tablename__ = "agent_model_bindings"
    __table_args__ = (UniqueConstraint("tenant_id", "agent_name", name="uq_bindings_tenant_agent"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(16), nullable=False)         # triage|knowledge|qc|resolution|insight
    provider_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_providers.id"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    temperature: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), default=0)
    max_tokens: Mapped[int | None] = mapped_column(Integer, default=4096)
    fallback_chain: Mapped[dict | None] = mapped_column(JSONB)  # W4 简化：预留，未实现降级链
