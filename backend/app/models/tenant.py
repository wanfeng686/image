import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Tenant(Base):
    """租户（商户）：SaaS 化的顶层隔离单位。

    - widget_key(pk_)：商户网站浏览器用，创建访客会话（Origin 白名单校验）
    - api_secret(sk_)：商户后端用，/api/v1 数据推送（demo 明文可轮换，生产应 hash）
    - brand：Widget 品牌化配置（标题/欢迎语/主题色）
    """
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active")        # active|suspended
    plan: Mapped[str] = mapped_column(String(16), default="free")            # free|pro（预留，未实现计费）
    widget_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    api_secret: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    brand: Mapped[dict] = mapped_column(JSONB, default=dict)                 # {title, welcome, theme_color, avatar}
    allowed_origins: Mapped[list] = mapped_column(JSONB, default=list)       # Widget 嵌入域名白名单
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
