"""邮箱验证码：注册流程一次性验证码（哈希落库，10 分钟过期，防暴力尝试）。"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EmailCode(Base):
    __tablename__ = "email_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)   # sha256(code + secret)
    purpose: Mapped[str] = mapped_column(String(16), default="register")
    attempts: Mapped[int] = mapped_column(default=0)                      # 校验失败次数（≥5 作废）
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
