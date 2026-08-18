import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AgentRun(Base):
    """Agent 执行记录：轨迹时间线的唯一数据源（W2 起所有节点落账）。"""
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("idx_runs_session", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"))
    agent_name: Mapped[str] = mapped_column(String(16), nullable=False)  # triage|knowledge|order|resolution|qc|insight
    graph_node: Mapped[str | None] = mapped_column(String(32))
    prompt_version_id: Mapped[int | None] = mapped_column()  # W4 接 agent_prompts 表，先留位不加外键
    provider_name: Mapped[str | None] = mapped_column(String(32))
    model_name: Mapped[str | None] = mapped_column(String(64))
    input: Mapped[dict | None] = mapped_column(JSONB)   # 脱敏后的输入摘要
    output: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="success")  # success|failed|rejected|degraded
    error: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(default=1)
    latency_ms: Mapped[int | None] = mapped_column()
    prompt_tokens: Mapped[int | None] = mapped_column()
    completion_tokens: Mapped[int | None] = mapped_column()
    cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
