"""安全工具：密码哈希（PBKDF2）+ 运营台令牌（HMAC 签名）。

不引第三方依赖，用标准库实现——演示项目够用且可审计。
生产建议换 passlib/bcrypt + pyjwt。
"""
import base64
import hashlib
import hmac
import os
import secrets
import time

from app.core.config import settings

_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    """格式：pbkdf2_sha256$迭代次数$盐$哈希（hex）。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters)).hex()
        return hmac.compare_digest(calc, digest)  # 恒定时间比较，防时序侧信道
    except (ValueError, AttributeError):
        return False


# ---------- 运营台令牌（HMAC 签名的轻量 token，载荷明文可见但不可伪造） ----------

def _secret() -> bytes:
    # 复用 LLM key 做签名密钥来源之一（演示项目；生产应独立 SECRET_KEY）
    return (settings.llm_api_key or "dev-secret").encode()


def issue_token(operator_id: str, ttl_seconds: int = 12 * 3600) -> str:
    payload = f"{operator_id}:{int(time.time()) + ttl_seconds}"
    b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), b64.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{b64}.{sig}"


def verify_token(token: str) -> str | None:
    """校验签名与过期时间，返回 operator_id；无效返回 None。"""
    try:
        b64, sig = token.split(".")
        expect = hmac.new(_secret(), b64.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expect):
            return None
        pad = "=" * (-len(b64) % 4)
        operator_id, expires = base64.urlsafe_b64decode(b64 + pad).decode().split(":")
        if int(expires) < time.time():
            return None
        return operator_id
    except Exception:
        return None
