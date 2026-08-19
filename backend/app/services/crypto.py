"""敏感凭据加密：AES-256-GCM（密钥由 SECRET_KEY 派生）。

存储格式 base64(nonce(12) + ciphertext + tag)。SECRET_KEY 未设置时回退
llm_api_key 派生（本地开发），生产必须显式设置 SECRET_KEY（docs/DEPLOY.md）。
"""
import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


def _key() -> bytes:
    material = settings.secret_key or (settings.llm_api_key + "::ss-fallback") or "ss-dev"
    return hashlib.sha256(material.encode()).digest()


def seal(data: dict) -> str:
    """dict → AES-GCM 加密字符串。"""
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, json.dumps(data, ensure_ascii=False).encode(), None)
    return base64.b64encode(nonce + ct).decode()


def unseal(blob: str | None) -> dict:
    """加密字符串 → dict；解不开（密钥轮换/损坏）按空凭据处理。"""
    if not blob:
        return {}
    try:
        raw = base64.b64decode(blob)
        return json.loads(AESGCM(_key()).decrypt(raw[:12], raw[12:], None))
    except Exception:  # noqa: BLE001
        return {}


def mask(value: str | None) -> str:
    """凭据脱敏展示：只留前 2 后 2。"""
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]
