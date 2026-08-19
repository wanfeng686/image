"""租户服务：密钥解析 / 生成。

密钥体系（电商渠道化后）：
- pk_（widget_key）：平台自带演示页创建访客会话（/api/chat，X-Widget-Key）
- sk_（api_secret）：商户后端 → /api/v1 数据推送与 API 会话
- Bearer token：商户操作员/平台管理员 → 门户与运营台（见 api/auth.py）
- 渠道连接凭据：AES-GCM 加密存 channel_connections（见 services/crypto.py）
"""
import secrets

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant


def get_by_widget_key(db: Session, key: str | None) -> Tenant | None:
    if not key:
        return None
    return db.scalar(select(Tenant).where(Tenant.widget_key == key, Tenant.status == "active"))


def get_by_api_secret(db: Session, secret: str | None) -> Tenant | None:
    if not secret:
        return None
    return db.scalar(select(Tenant).where(Tenant.api_secret == secret, Tenant.status == "active"))


def require_tenant_by_widget_key(db: Session, key: str | None) -> Tenant:
    tenant = get_by_widget_key(db, key)
    if tenant is None:
        raise HTTPException(status_code=401, detail={"code": "INVALID_WIDGET_KEY",
                                                     "message": "Widget 密钥无效"})
    return tenant


def require_tenant_by_api_secret(db: Session, secret: str | None) -> Tenant:
    tenant = get_by_api_secret(db, secret)
    if tenant is None:
        raise HTTPException(status_code=401, detail={"code": "INVALID_API_SECRET",
                                                     "message": "API 密钥无效"})
    return tenant


def generate_widget_key() -> str:
    return "pk_" + secrets.token_hex(16)


def generate_api_secret() -> str:
    return "sk_" + secrets.token_hex(20)


def brand_dict(tenant: Tenant) -> dict:
    """Widget 品牌配置（带兜底默认值）。"""
    b = dict(tenant.brand or {})
    return {
        "title": b.get("title") or f"{tenant.name}智能客服",
        "welcome": b.get("welcome") or "您好，请问有什么可以帮您？",
        "theme_color": b.get("theme_color") or "#4F46E5",
    }
