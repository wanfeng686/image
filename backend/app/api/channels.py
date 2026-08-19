"""渠道连接 API：平台目录 / 连接 CRUD / 连接测试（商户操作员鉴权）。

- 平台目录来自 services/channels/catalog.py（本轮仅拼多多 available）
- 凭据 AES-GCM 加密落库，接口只回传脱敏形态
- RPA 模式必须携带 rpa_consent=true（前端有风险知情勾选）
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_operator
from app.core.db import get_db
from app.models import ChannelConnection, Operator, Tenant
from app.services import crypto
from app.services.channels import catalog, testing

router = APIRouter(prefix="/api/channel", tags=["channel"])


def _get_tenant(db: Session, op: Operator) -> Tenant:
    if op.tenant_id is None:
        raise HTTPException(403, "平台账号无租户上下文，请用商户账号登录门户")
    return db.get(Tenant, op.tenant_id)


def _conn_dict(c: ChannelConnection) -> dict:
    creds = crypto.unseal(c.credentials_cipher)
    return {
        "id": str(c.id), "platform": c.platform,
        "platform_name": (catalog.get_platform(c.platform) or {}).get("name", c.platform),
        "mode": c.mode, "status": c.status, "shop_name": c.shop_name,
        "last_sync_at": c.last_sync_at, "last_error": c.last_error,
        "created_at": c.created_at,
        "credentials_masked": {k: crypto.mask(v) for k, v in creds.items()
                               if isinstance(v, str)},
    }


@router.get("/platforms")
def list_platforms():
    return {"items": catalog.public_catalog()}


class ConnectionRequest(BaseModel):
    platform: str
    mode: str                                   # official_api | rpa
    credentials: dict
    rpa_consent: bool = False
    shop_name: str | None = None


@router.post("/connections", status_code=201)
def create_connection(body: ConnectionRequest, db: Session = Depends(get_db),
                      op: Operator = Depends(get_current_operator)):
    tenant = _get_tenant(db, op)
    p = catalog.get_platform(body.platform)
    if p is None:
        raise HTTPException(422, "未知平台")
    if not p.get("available"):
        raise HTTPException(422, f"{p['name']} 即将支持，敬请期待")
    if body.mode not in p.get("modes", []):
        raise HTTPException(422, "该平台不支持此接入方式")
    if body.mode == "rpa" and not body.rpa_consent:
        raise HTTPException(403, "RPA 托管模式需先勾选风险知情同意")

    fields = catalog.fields_for(body.platform, body.mode)
    creds = {}
    for f in fields:
        v = (body.credentials.get(f["key"]) or "").strip() if isinstance(
            body.credentials.get(f["key"]), str) else body.credentials.get(f["key"])
        if f.get("required") and not v:
            raise HTTPException(422, f"请填写{f['label']}")
        if v:
            creds[f["key"]] = v
    if body.mode == "rpa":
        creds["consent_at"] = datetime.now(timezone.utc).isoformat()   # 留存同意时间

    if db.scalar(select(ChannelConnection).where(
            ChannelConnection.tenant_id == tenant.id,
            ChannelConnection.platform == body.platform)):
        raise HTTPException(409, "该平台已存在连接，可编辑或删除后重建")

    conn = ChannelConnection(tenant_id=tenant.id, platform=body.platform, mode=body.mode,
                             credentials_cipher=crypto.seal(creds),
                             shop_name=(body.shop_name or tenant.name)[:128],
                             status="pending")
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return _conn_dict(conn)


@router.get("/connections")
def list_connections(db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    tenant = _get_tenant(db, op)
    rows = db.scalars(select(ChannelConnection)
                      .where(ChannelConnection.tenant_id == tenant.id)
                      .order_by(ChannelConnection.created_at)).all()
    return {"items": [_conn_dict(c) for c in rows]}


class ConnectionPatch(BaseModel):
    enabled: bool | None = None
    credentials: dict | None = None
    shop_name: str | None = None


def _scoped_conn(db: Session, tenant: Tenant, conn_id: str) -> ChannelConnection:
    conn = db.get(ChannelConnection, _to_uuid(conn_id))
    if conn is None or conn.tenant_id != tenant.id:
        raise HTTPException(404, "连接不存在")
    return conn


def _to_uuid(s: str):
    import uuid as _u
    try:
        return _u.UUID(s)
    except ValueError:
        raise HTTPException(404, "连接不存在")


@router.patch("/connections/{conn_id}")
def update_connection(conn_id: str, body: ConnectionPatch, db: Session = Depends(get_db),
                      op: Operator = Depends(get_current_operator)):
    tenant = _get_tenant(db, op)
    conn = _scoped_conn(db, tenant, conn_id)
    if body.credentials is not None:
        creds = crypto.unseal(conn.credentials_cipher)
        for k, v in body.credentials.items():
            if isinstance(v, str) and v.strip():
                creds[k] = v.strip()
        conn.credentials_cipher = crypto.seal(creds)
    if body.shop_name:
        conn.shop_name = body.shop_name[:128]
    if body.enabled is not None:
        conn.status = "pending" if body.enabled else "disabled"
    db.commit()
    db.refresh(conn)
    return _conn_dict(conn)


@router.delete("/connections/{conn_id}")
def delete_connection(conn_id: str, db: Session = Depends(get_db),
                      op: Operator = Depends(get_current_operator)):
    tenant = _get_tenant(db, op)
    conn = _scoped_conn(db, tenant, conn_id)
    db.delete(conn)
    db.commit()
    return {"deleted": True}


@router.post("/connections/{conn_id}/test")
def test_connection(conn_id: str, db: Session = Depends(get_db),
                    op: Operator = Depends(get_current_operator)):
    tenant = _get_tenant(db, op)
    conn = _scoped_conn(db, tenant, conn_id)
    result = testing.test_connection(db, conn)
    db.commit()
    return result
