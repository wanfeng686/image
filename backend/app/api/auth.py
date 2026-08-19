"""运营台认证：登录发 HMAC 令牌，/me 回显当前运营人员。"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import issue_token, verify_password, verify_token
from app.models import Operator

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


def get_current_operator(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Operator:
    """控制台接口的统一鉴权依赖：Authorization: Bearer <token>。"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "AUTH_FAILED", "message": "未登录"})
    op_id = verify_token(authorization[7:])
    if op_id is None:
        raise HTTPException(status_code=401, detail={"code": "AUTH_FAILED", "message": "令牌无效或已过期"})
    op = db.get(Operator, uuid.UUID(op_id))
    if op is None:
        raise HTTPException(status_code=401, detail={"code": "AUTH_FAILED", "message": "账号不存在"})
    return op


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    ident = body.username.strip()
    op = db.scalar(select(Operator).where(
        (Operator.username == ident) | (func.lower(Operator.email) == ident.lower())))
    if op is None or not verify_password(body.password, op.password_hash):
        raise HTTPException(status_code=401, detail={"code": "AUTH_FAILED", "message": "邮箱/用户名或密码错误"})
    op.is_online = True
    db.commit()
    return {
        "token": issue_token(str(op.id)),
        "operator": {"id": str(op.id), "display_name": op.display_name, "role": op.role,
                     "tenant_id": str(op.tenant_id) if op.tenant_id else None},
    }


@router.get("/me")
def me(op: Operator = Depends(get_current_operator)):
    return {"id": str(op.id), "display_name": op.display_name,
            "role": op.role, "is_online": op.is_online,
            "tenant_id": str(op.tenant_id) if op.tenant_id else None}
