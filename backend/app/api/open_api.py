"""开放 API v1：商户后端对接通道（sk_ 密钥，服务端到服务端）。

能力：
- POST /api/v1/products | /api/v1/orders     商品/订单 JSON 推送（按 sku/order_no upsert）
- POST /api/v1/sessions                       创建 API 会话（可绑商户会员 external_user_id）
- POST /api/v1/sessions/{id}/messages         发消息（非流式，返回完整回复）
- GET  /api/v1/sessions/{id}/messages         拉历史

鉴权：Authorization: Bearer sk_...（sk_ 属服务端密钥，切勿放进浏览器/APP 前端）。
"""
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.chat import _process_turn
from app.api.portal import upsert_orders, upsert_products
from app.core.db import get_db
from app.models import ChatSession, Message, Tenant, User
from app.schemas.message import MessageOut, MessagePage
from app.schemas.session import SessionOut
from app.services import tenants as tenant_svc

router = APIRouter(prefix="/api/v1", tags=["open-api"])


def _tenant_from_sk(db: Session, authorization: str) -> Tenant:
    token = authorization[7:] if authorization.startswith("Bearer ") else authorization
    if not token.startswith("sk_"):
        raise HTTPException(401, {"code": "INVALID_API_SECRET", "message": "需要 sk_ 密钥"})
    return tenant_svc.require_tenant_by_api_secret(db, token)


class ItemsRequest(BaseModel):
    items: list[dict]


@router.post("/products")
def push_products(body: ItemsRequest, db: Session = Depends(get_db),
                  authorization: str = Header(default="")):
    tenant = _tenant_from_sk(db, authorization)
    result = upsert_products(db, tenant, body.items[:1000])
    db.commit()
    return result


@router.post("/orders")
def push_orders(body: ItemsRequest, db: Session = Depends(get_db),
                authorization: str = Header(default="")):
    tenant = _tenant_from_sk(db, authorization)
    result = upsert_orders(db, tenant, body.items[:1000])
    db.commit()
    return result


class ApiSessionRequest(BaseModel):
    user_external_id: str | None = None   # 绑定商户会员（服务端可信渠道才传）


@router.post("/sessions", status_code=201)
def create_api_session(body: ApiSessionRequest, db: Session = Depends(get_db),
                       authorization: str = Header(default="")):
    tenant = _tenant_from_sk(db, authorization)
    user = None
    if body.user_external_id:
        user = db.scalar(select(User).where(
            User.tenant_id == tenant.id, User.external_id == body.user_external_id))
        if user is None:
            user = User(tenant_id=tenant.id, external_id=body.user_external_id,
                        nickname=f"会员{body.user_external_id[:8]}")
            db.add(user)
            db.flush()
    if user is None:
        user = User(tenant_id=tenant.id, nickname=f"API访客{uuid.uuid4().hex[:6]}")
        db.add(user)
        db.flush()
    session = ChatSession(tenant_id=tenant.id, user_id=user.id, channel="api",
                          config_snapshot={})
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session": SessionOut.model_validate(session).model_dump(mode="json"),
            "tenant": {"id": str(tenant.id), "name": tenant.name}}


def _scoped_session(db: Session, tenant: Tenant, session_id: uuid.UUID) -> ChatSession:
    s = db.get(ChatSession, session_id)
    if s is None or s.tenant_id != tenant.id:
        raise HTTPException(404, "session not found")
    return s


class ApiMessageRequest(BaseModel):
    content: str


@router.post("/sessions/{session_id}/messages", response_model=list[MessageOut])
def api_send_message(session_id: uuid.UUID, body: ApiMessageRequest,
                     db: Session = Depends(get_db), authorization: str = Header(default="")):
    """非流式发消息：跑完整编排后一次性返回 [顾客消息, AI回复]。"""
    tenant = _tenant_from_sk(db, authorization)
    session = _scoped_session(db, tenant, session_id)
    return _process_turn(db, session, body.content)


@router.get("/sessions/{session_id}/messages", response_model=MessagePage)
def api_list_messages(session_id: uuid.UUID, db: Session = Depends(get_db),
                      authorization: str = Header(default="")):
    tenant = _tenant_from_sk(db, authorization)
    _scoped_session(db, tenant, session_id)
    msgs = db.scalars(select(Message).where(Message.session_id == session_id)
                      .order_by(Message.created_at.asc())).all()
    return MessagePage(items=msgs, total=len(msgs), page=1, page_size=100)
