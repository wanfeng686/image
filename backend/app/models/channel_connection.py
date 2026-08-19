"""渠道连接：商户店铺在电商平台的接入配置（官方 API / RPA 双模）。

credentials_cipher = AES-GCM 加密后的 JSON（client_secret / 店铺密码等敏感凭据，
密钥来自 SECRET_KEY，见 services/crypto.py）。查询接口永不回传明文凭据。
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChannelConnection(Base):
    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", name="uq_channel_tenant_platform"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"),
                                                 nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)        # pinduoduo|taobao|...
    mode: Mapped[str] = mapped_column(String(16), nullable=False)            # official_api|rpa
    status: Mapped[str] = mapped_column(String(16), default="pending")       # pending|connected|error|disabled
    credentials_cipher: Mapped[str] = mapped_column(Text)                    # AES-GCM(JSON)
    shop_name: Mapped[str | None] = mapped_column(String(128))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  onupdate=func.now())
