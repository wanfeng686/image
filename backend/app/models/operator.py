import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Operator(Base):
    """运营人员：tenant_id=NULL 为平台管理员（豁免租户过滤），否则为商户操作员。
    username 保持全局唯一（登录无需租户上下文即可定位账号）。
    email：邮箱注册入口（唯一，可空兼容存量账密账号）；登录支持邮箱或用户名。"""

    __tablename__ = "operators"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="operator")     # admin|owner|operator|auditor
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
