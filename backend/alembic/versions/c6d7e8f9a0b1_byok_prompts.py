"""tenants.prompts + model_providers.api_key 加密

Revision ID: c6d7e8f9a0b1
Revises: b2c3d4e5f6a7
Create Date: 2026-08-19

BYOK（商户自带模型）：
- tenants 加 prompts JSONB——租户级提示词模板覆盖（如客服人设 system prompt），
  空对象 = 全部用平台默认模板；
- model_providers.api_key 由明文 String(256) 改 Text 密文（AES-256-GCM，
  与 channel_connections.credentials_cipher 同一套 crypto.seal/unseal），
  存量明文数据在迁移中原地加密。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c6d7e8f9a0b1"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def _seal(plain: str) -> str:
    from app.services import crypto

    return crypto.seal({"api_key": plain})


def _unseal(blob: str) -> str:
    from app.services import crypto

    return crypto.unseal(blob).get("api_key", "")


def upgrade() -> None:
    op.add_column("tenants",
                  sa.Column("prompts", postgresql.JSONB(), nullable=False,
                            server_default=sa.text("'{}'::jsonb")))
    op.alter_column("model_providers", "api_key",
                    existing_type=sa.String(256), type_=sa.Text())

    # 存量明文 key 原地加密（密文长度超过原 256 上限，故先改 Text）
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, api_key FROM model_providers WHERE api_key IS NOT NULL AND api_key != ''"
    )).fetchall()
    for pid, key in rows:
        if _unseal(key):  # 能解开 = 已是密文，幂等跳过
            continue
        conn.execute(sa.text("UPDATE model_providers SET api_key = :v WHERE id = :i"),
                     {"v": _seal(key), "i": pid})


def downgrade() -> None:
    # 反向解密回明文，并还原列类型
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, api_key FROM model_providers WHERE api_key IS NOT NULL AND api_key != ''"
    )).fetchall()
    for pid, key in rows:
        plain = _unseal(key)
        if plain:
            conn.execute(sa.text("UPDATE model_providers SET api_key = :v WHERE id = :i"),
                         {"v": plain[:256], "i": pid})
    op.alter_column("model_providers", "api_key",
                    existing_type=sa.Text(), type_=sa.String(256))
    op.drop_column("tenants", "prompts")
