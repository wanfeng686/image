"""商户门户 API：邮箱注册（验证码）/ 租户信息 / 品牌设置 / 域名白名单 / 密钥轮换 / 数据导入。

注册即得：租户 + owner 操作员 + 默认风控/升级规则 + 双密钥（pk_/sk_）。
登录复用 /api/auth/login（邮箱或用户名均可定位账号）。
注意：/register 与 /email/send-code 公开，其余接口要求商户操作员上下文。
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_operator
from app.core.config import settings
from app.core.db import get_db
from app.core.security import hash_password, issue_token
from app.models import ChatSession, EmailCode, MockOrder, MockProduct, Operator, Tenant, User
from app.services import mailer, tenants as tenant_svc
from app.services.defaults import ensure_default_rules

router = APIRouter(prefix="/api/portal", tags=["portal"])

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
CODE_TTL_MIN = 10
CODE_RESEND_COOLDOWN = 60      # 同一邮箱 60s 内只能发一次
CODE_MAX_ATTEMPTS = 5


def _get_tenant(db: Session, op: Operator) -> Tenant:
    if op.tenant_id is None:
        raise HTTPException(403, "平台账号无租户上下文，请用商户账号登录门户")
    return db.get(Tenant, op.tenant_id)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_code(email: str, code: str) -> str:
    secret = settings.secret_key or settings.llm_api_key or "ss-dev"
    return hashlib.sha256(f"{email}:{code}:{secret}".encode()).hexdigest()


class SendCodeRequest(BaseModel):
    email: str


@router.post("/email/send-code")
def send_code(body: SendCodeRequest, db: Session = Depends(get_db)):
    """向邮箱发 6 位注册验证码（60s 冷却；验证码哈希落库 10 分钟有效）。"""
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 255:
        raise HTTPException(422, "邮箱格式不正确")
    if db.scalar(select(Operator).where(Operator.email == email)):
        raise HTTPException(409, "该邮箱已注册，请直接登录")

    last = db.scalar(select(EmailCode).where(EmailCode.email == email)
                     .order_by(EmailCode.created_at.desc()).limit(1))
    if last is not None and last.created_at is not None:
        age = (_now() - last.created_at.replace(tzinfo=timezone.utc)).total_seconds()
        if age < CODE_RESEND_COOLDOWN:
            raise HTTPException(429, f"发送过于频繁，请 {int(CODE_RESEND_COOLDOWN - age) + 1} 秒后再试")

    code = f"{secrets.randbelow(1000000):06d}"
    db.execute(EmailCode.__table__.delete().where(EmailCode.email == email))   # 旧码全部作废
    db.add(EmailCode(email=email, code_hash=_hash_code(email, code),
                     expires_at=_now() + timedelta(minutes=CODE_TTL_MIN)))
    db.commit()

    ok, err = mailer.send_mail(email, "SmartSupport 注册验证码",
                               f"您的验证码是 {code}，{CODE_TTL_MIN} 分钟内有效。若非本人操作请忽略。")
    dev_code = None
    if not ok and err is None:
        # SMTP 未配置：本地联调回退（mail_dev_mode），生产必须关闭
        if not settings.mail_dev_mode:
            raise HTTPException(503, "邮件服务未配置，请联系平台管理员")
        dev_code = code
        print(f"[mail:dev] 注册验证码 -> {email}: {code}", flush=True)
    elif not ok:
        raise HTTPException(502, f"验证码发送失败：{err}")

    resp = {"sent": True, "expires_in": CODE_TTL_MIN * 60}
    if dev_code is not None:
        resp["dev_code"] = dev_code   # 仅本地 dev 模式返回
    return resp


class RegisterRequest(BaseModel):
    email: str
    code: str
    password: str
    tenant_name: str


def _derive_username(db: Session, email: str) -> str:
    """username 由邮箱前缀派生（仅字母数字），冲突加序号；username 是内部字段不再让用户起。"""
    base = re.sub(r"[^0-9a-zA-Z]", "", email.split("@", 1)[0]).lower()[:48] or "user"
    if len(base) < 3:
        base = f"user{base}"
    for i in range(200):
        cand = base if i == 0 else f"{base}_{i}"
        if not db.scalar(select(Operator).where(Operator.username == cand)):
            return cand
    return f"u{secrets.token_hex(6)}"


def _consume_code(db: Session, email: str, code: str) -> None:
    row = db.scalar(select(EmailCode).where(EmailCode.email == email)
                    .order_by(EmailCode.created_at.desc()).limit(1))
    if row is None or row.used or row.expires_at.replace(tzinfo=timezone.utc) < _now():
        raise HTTPException(400, "验证码已过期，请重新获取")
    if row.attempts >= CODE_MAX_ATTEMPTS:
        raise HTTPException(400, "尝试次数过多，请重新获取验证码")
    if row.code_hash != _hash_code(email, code.strip()):
        row.attempts += 1
        db.commit()
        raise HTTPException(400, "验证码错误")
    row.used = True
    db.flush()


@router.post("/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """邮箱注册 = 验证码校验 + 建租户 + owner 操作员 + 默认规则 + 双密钥（公开接口）。"""
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "邮箱格式不正确")
    if not (2 <= len(body.tenant_name.strip()) <= 64):
        raise HTTPException(422, "商户名称长度 2-64")
    if len(body.password) < 6:
        raise HTTPException(422, "密码至少 6 位")
    if not (body.code or "").strip():
        raise HTTPException(422, "请输入邮箱验证码")
    if db.scalar(select(Operator).where(Operator.email == email)):
        raise HTTPException(409, "该邮箱已注册，请直接登录")
    _consume_code(db, email, body.code)

    username = _derive_username(db, email)
    tenant = Tenant(name=body.tenant_name.strip(),
                    widget_key=tenant_svc.generate_widget_key(),
                    api_secret=tenant_svc.generate_api_secret())
    db.add(tenant)
    db.flush()
    ensure_default_rules(db, tenant)
    op = Operator(tenant_id=tenant.id, username=username, email=email, email_verified=True,
                  display_name=body.tenant_name.strip() + " 管理员",
                  role="owner", password_hash=hash_password(body.password))
    db.add(op)
    db.commit()
    db.refresh(tenant)
    db.refresh(op)

    return {
        "token": issue_token(str(op.id)),
        "tenant": _tenant_dict(db, tenant),
        "operator": {"id": str(op.id), "display_name": op.display_name, "role": op.role,
                     "email": op.email},
    }


def _embed_code(t: Tenant) -> str:
    # {ORIGIN} 占位：门户前端用当前访问的 origin 替换后展示
    return f'<script src="{{ORIGIN}}/embed.js" data-key="{t.widget_key}" async></script>'


def _tenant_dict(db: Session, t: Tenant) -> dict:
    orders = db.scalar(select(func.count()).select_from(MockOrder)
                       .where(MockOrder.tenant_id == t.id))
    products = db.scalar(select(func.count()).select_from(MockProduct)
                         .where(MockProduct.tenant_id == t.id))
    sessions = db.scalar(select(func.count()).select_from(ChatSession)
                         .where(ChatSession.tenant_id == t.id))
    return {
        "id": str(t.id), "name": t.name, "status": t.status, "plan": t.plan,
        "widget_key": t.widget_key, "api_secret": t.api_secret,
        "brand": tenant_svc.brand_dict(t),
        "allowed_origins": t.allowed_origins or [],
        "stats": {"orders": orders, "products": products, "sessions": sessions},
        "embed_code": _embed_code(t),
        "created_at": t.created_at,
    }


@router.get("/me")
def portal_me(db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    return _tenant_dict(db, _get_tenant(db, op))


class BrandRequest(BaseModel):
    title: str | None = None
    welcome: str | None = None
    theme_color: str | None = None


@router.patch("/brand")
def update_brand(body: BrandRequest, db: Session = Depends(get_db),
                 op: Operator = Depends(get_current_operator)):
    t = _get_tenant(db, op)
    brand = dict(t.brand or {})
    if body.title:
        brand["title"] = body.title[:64]
    if body.welcome:
        brand["welcome"] = body.welcome[:200]
    if body.theme_color:
        brand["theme_color"] = body.theme_color[:16]
    t.brand = brand
    db.commit()
    return {"brand": tenant_svc.brand_dict(t)}


class OriginsRequest(BaseModel):
    origins: list[str]


@router.put("/origins")
def update_origins(body: OriginsRequest, db: Session = Depends(get_db),
                   op: Operator = Depends(get_current_operator)):
    if len(body.origins) > 20:
        raise HTTPException(422, "最多 20 个域名")
    cleaned = []
    for o in body.origins:
        o = (o or "").strip().rstrip("/")
        if o and o not in cleaned:
            cleaned.append(o)
    t = _get_tenant(db, op)
    t.allowed_origins = cleaned
    db.commit()
    return {"allowed_origins": cleaned}


class RotateRequest(BaseModel):
    which: str = "both"   # widget | api | both


@router.post("/keys/rotate")
def rotate_keys(body: RotateRequest, db: Session = Depends(get_db),
                op: Operator = Depends(get_current_operator)):
    """轮换密钥：旧密钥立即失效（嵌入代码需更新）。"""
    t = _get_tenant(db, op)
    if body.which in ("widget", "both"):
        t.widget_key = tenant_svc.generate_widget_key()
    if body.which in ("api", "both"):
        t.api_secret = tenant_svc.generate_api_secret()
    db.commit()
    return {"widget_key": t.widget_key, "api_secret": t.api_secret}


# ---------- 数据导入（门户 CSV 上传，与 /api/v1 JSON 推送共用处理内核） ----------

def upsert_products(db: Session, tenant: Tenant, items: list[dict]) -> dict:
    created = updated = 0
    for it in items:
        sku = (it.get("sku") or "").strip()
        if not sku:
            continue
        row = db.scalar(select(MockProduct).where(
            MockProduct.tenant_id == tenant.id, MockProduct.sku == sku))
        if row is None:
            row = MockProduct(tenant_id=tenant.id, sku=sku)
            db.add(row)
            created += 1
        else:
            updated += 1
        row.name = (it.get("name") or row.name or sku)[:128]
        price = it.get("price")
        if price is not None:
            row.price = float(price)
        cat = it.get("category") or row.category
        row.category = cat[:32] if cat else None
    db.flush()
    return {"created": created, "updated": updated}


def _user_for(db: Session, tenant: Tenant, external_id: str) -> User:
    """订单归属的顾客：按租户内 external_id 绑定或新建。"""
    row = db.scalar(select(User).where(
        User.tenant_id == tenant.id, User.external_id == external_id))
    if row is None:
        row = User(tenant_id=tenant.id, external_id=external_id,
                   nickname=f"顾客{external_id[:8]}")
        db.add(row)
        db.flush()
    return row


def upsert_orders(db: Session, tenant: Tenant, items: list[dict]) -> dict:
    created = updated = skipped = 0
    for it in items:
        order_no = (it.get("order_no") or "").strip()
        sku, ext = (it.get("sku") or "").strip(), (it.get("user_external_id") or "").strip()
        if not order_no:
            continue
        prod = db.scalar(select(MockProduct).where(
            MockProduct.tenant_id == tenant.id, MockProduct.sku == sku)) if sku else None
        row = db.scalar(select(MockOrder).where(
            MockOrder.tenant_id == tenant.id, MockOrder.order_no == order_no))
        if row is None:
            # 新建：先取齐 NOT NULL 字段再 add（避免中途 flush 插入半成品）
            if not (sku and ext and prod is not None):
                skipped += 1
                continue
            user = _user_for(db, tenant, ext)
            try:
                amount = float(it.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0.0
            row = MockOrder(tenant_id=tenant.id, order_no=order_no,
                            product_id=prod.id, user_id=user.id, amount=amount)
            db.add(row)
            created += 1
        else:
            updated += 1
            if prod is not None:
                row.product_id = prod.id
            if ext:
                row.user_id = _user_for(db, tenant, ext).id
            if it.get("amount") is not None:
                try:
                    row.amount = float(it["amount"])
                except (TypeError, ValueError):
                    pass
        status = it.get("status")
        if status:
            row.status = status[:16]
        addr = it.get("address_masked")
        if addr:
            row.address_masked = addr[:256]
    db.flush()
    return {"created": created, "updated": updated, "skipped": skipped}


@router.post("/import")
async def import_csv(file: UploadFile, db: Session = Depends(get_db),
                     op: Operator = Depends(get_current_operator)):
    """CSV 批量导入。文件名含 products/orders 决定导入目标。
    products 列：sku,name,price,category
    orders 列：order_no,sku,user_external_id,amount,status,address_masked
    """
    tenant = _get_tenant(db, op)
    fname = (file.filename or "").lower()
    if "product" in fname:
        kind = "products"
    elif "order" in fname:
        kind = "orders"
    else:
        raise HTTPException(422, "文件名需包含 products 或 orders 以区分导入类型")

    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        raise HTTPException(422, "空文件")
    cols = [c.strip().lower() for c in lines[0].split(",")]
    items = []
    for ln in lines[1:]:
        vals = [v.strip() for v in ln.split(",")]
        item = dict(zip(cols, vals))
        for k in ("price", "amount"):
            if item.get(k):
                try:
                    item[k] = float(item[k])
                except ValueError:
                    item[k] = None
        items.append(item)

    result = (upsert_products(db, tenant, items) if kind == "products"
              else upsert_orders(db, tenant, items))
    db.commit()
    return {"type": kind, "rows": len(items), **result}


# ---------- 平台管理（仅平台管理员） ----------

platform_router = APIRouter(prefix="/api/platform", tags=["platform"])


@platform_router.get("/tenants")
def list_tenants(db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    if op.tenant_id is not None or op.role != "admin":
        raise HTTPException(403, "仅平台管理员可用")
    rows = db.execute(
        select(Tenant, func.count(ChatSession.id))
        .outerjoin(ChatSession, ChatSession.tenant_id == Tenant.id)
        .group_by(Tenant.id).order_by(Tenant.created_at)).all()
    return {"items": [{
        "id": str(t.id), "name": t.name, "status": t.status, "plan": t.plan,
        "widget_key": t.widget_key, "sessions": n, "created_at": t.created_at,
    } for t, n in rows], "total": len(rows)}
