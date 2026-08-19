"""Widget 接入 API：商户网站的顾客会话入口（pk_ 密钥鉴权 + Origin 白名单）。

这是 SaaS 化的租户进站口：iframe Widget 页与旧演示页都从这里创建会话。
后续消息收发复用 /api/chat/*（session UUID 即能力凭证，与既有设计一致）。

Origin 校验说明：iframe 与平台同源，浏览器 Origin 头是平台域名，
所以 iframe 页会把商户页面 origin 以 X-Widget-Origin 声明传入
（loader 的 o 参数）。这是声明式校验（防顺手嵌入），非密码学验证，
强域名归属验证（DNS TXT 等）在 Roadmap。
"""
import uuid

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import ChatSession, User
from app.schemas.session import SessionOut
from app.services import tenants as tenant_svc

router = APIRouter(prefix="/api/widget", tags=["widget"])


class WidgetSessionRequest(BaseModel):
    user_external_id: str | None = None   # 可选：商户会员 ID（访客模式不传）


class WidgetSessionOut(BaseModel):
    session: SessionOut
    brand: dict


@router.post("/sessions", response_model=WidgetSessionOut, status_code=201)
def create_widget_session(
    body: WidgetSessionRequest,
    db: Session = Depends(get_db),
    x_widget_key: str | None = Header(default=None),
    origin: str | None = Header(default=None),
    x_widget_origin: str | None = Header(default=None),
):
    tenant = tenant_svc.require_tenant_by_widget_key(db, x_widget_key)
    tenant_svc.check_widget_origin(tenant, x_widget_origin or origin)

    user = None
    if body.user_external_id:
        user = db.scalar(select(User).where(
            User.tenant_id == tenant.id, User.external_id == body.user_external_id))
        if user is None:
            user = User(tenant_id=tenant.id, external_id=body.user_external_id,
                        nickname=f"顾客{uuid.uuid4().hex[:6]}")
            db.add(user)
            db.flush()
    if user is None:
        user = User(tenant_id=tenant.id, nickname=f"访客{uuid.uuid4().hex[:6]}")
        db.add(user)
        db.flush()

    session = ChatSession(tenant_id=tenant.id, user_id=user.id, config_snapshot={})
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session": SessionOut.model_validate(session).model_dump(mode="json"),
            "brand": tenant_svc.brand_dict(tenant)}


@router.get("/boot")
def widget_boot(db: Session = Depends(get_db),
                key: str | None = None, origin: str | None = Header(default=None),
                x_widget_origin: str | None = Header(default=None)):
    """Widget 加载时取品牌配置（不建会话；会话由 POST /sessions 创建）。"""
    tenant = tenant_svc.require_tenant_by_widget_key(db, key)
    tenant_svc.check_widget_origin(tenant, x_widget_origin or origin)
    return {"tenant": {"id": str(tenant.id), "name": tenant.name},
            "brand": tenant_svc.brand_dict(tenant)}
