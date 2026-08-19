"""连接测试：C2 阶段做凭据完整性校验；C3 起拼多多 official_api 走真实签名调用。

test_connection 返回 dict 并按结果回写连接状态：
- official_api：字段齐全 → 真实调用（C3 注入），成功 status=connected，失败 status=error + last_error
- rpa：字段齐全即 pending（登录成功与否由 C4 的 worker 置 connected/error）
"""
from sqlalchemy.orm import Session

from app.models import ChannelConnection
from app.services import crypto
from app.services.channels import catalog


def test_connection(db: Session, conn: ChannelConnection) -> dict:
    p = catalog.get_platform(conn.platform) or {}
    fields = catalog.fields_for(conn.platform, conn.mode)
    creds = crypto.unseal(conn.credentials_cipher)
    missing = [f["label"] for f in fields if f.get("required") and not creds.get(f["key"])]
    if missing:
        conn.status = "error"
        conn.last_error = "缺少必填凭据：" + "、".join(missing)
        return {"ok": False, "detail": conn.last_error}

    if conn.mode == "official_api" and conn.platform == "pinduoduo":
        # C3：真实签名调用（pdd.mall.info.get 等），此处延迟导入避免循环依赖
        from app.services.channels.official.pinduoduo import test_credentials
        result = test_credentials(creds)
        if result.get("ok"):
            conn.status = "connected"
            conn.last_error = None
            if result.get("shop_name"):
                conn.shop_name = result["shop_name"][:128]
        else:
            conn.status = "error"
            conn.last_error = result.get("detail", "测试失败")
        return result

    # RPA / 其余平台：字段校验通过即视为待接入（worker/适配器上线后回写状态）
    conn.last_error = None
    return {"ok": True, "detail": "凭据校验通过",
            "note": f"{p.get('name', conn.platform)} {conn.mode} 待适配器联调" if not p.get('available') else None}
