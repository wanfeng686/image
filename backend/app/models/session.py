import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_ref", name="uq_sessions_tenant_extref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), default="web_widget")
    external_ref: Mapped[str | None] = mapped_column(String(64))   # 渠道会话映射，如 pinduoduo:conv-123
    status: Mapped[str] = mapped_column(String(24), default="active")
    rolling_summary: Mapped[str | None] = mapped_column(Text)
    slots: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_intent: Mapped[dict | None] = mapped_column(JSONB)
    sentiment: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    step_budget: Mapped[int] = mapped_column(SmallInteger, default=30)
    steps_used: Mapped[int] = mapped_column(SmallInteger, default=0)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    escalated_reason: Mapped[str | None] = mapped_column(String(64))
    taken_over_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("operators.id"))
    satisfaction: Mapped[int | None] = mapped_column(SmallInteger)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)