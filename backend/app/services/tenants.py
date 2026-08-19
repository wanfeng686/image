"""租户服务：密钥解析 / 生成 / Origin 白名单校验。

三层密钥体系（SaaS 化）：
- pk_（widget_key）：商户网站的浏览器 → 创建访客会话
- sk_（api_secret）：商户后端 → /api/v1 数据推送与 API 会话
- Bearer token：商户操作员/平台管理员 → 门户与运营台（见 api/auth.py）
"""
import secrets
import uuid

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


def check_widget_origin(tenant: Tenant, origin: str | None) -> None:
    """Widget 嵌入域白名单：非空白名单时 Origin 必须命中；空 = 宽松模式（本地演示）。"""
    allowed = tenant.allowed_origins or []
    if not allowed:
        return  # 宽松模式：未配置白名单的租户放行（生产建议强制配置）
    if origin and origin.rstrip("/") in [o.rstrip("/") for o in allowed if isinstance(o, str)]:
        return
    raise HTTPException(status_code=403, detail={"code": "ORIGIN_NOT_ALLOWED",
                                                 "message": f"来源 {origin or '(空)'} 未在白名单"})


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
