import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id", name="uq_users_tenant_external"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(64))          # 租户内渠道用户ID
    nickname: Mapped[str | None] = mapped_column(String(64))
    phone_masked: Mapped[str | None] = mapped_column(String(32))
    user_tier: Mapped[str] = mapped_column(String(16), default="normal")
    risk_flags: Mapped[dict] = mapped_column(JSONB, default=dict)
    total_refund_30d: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
