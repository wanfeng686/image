"""channel connections + sessions.external_ref

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-19

电商渠道化：新表 channel_connections（租户×平台唯一，凭据 AES-GCM 密文）；
chat_sessions 加 external_ref（渠道会话外部映射，如 pinduoduo 买家会话 ID），
(tenant_id, external_ref) 唯一——同一买家在同平台的对话固定落在同一会话。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("credentials_cipher", sa.Text(), nullable=False),
        sa.Column("shop_name", sa.String(128), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_channel_tenant_platform", "channel_connections",
                                ["tenant_id", "platform"])
    op.create_index("ix_channel_connections_tenant", "channel_connections", ["tenant_id"])

    op.add_column("sessions",
                  sa.Column("external_ref", sa.String(64), nullable=True))
    # 存量会话 external_ref 为 NULL 不受影响；新渠道会话按 "平台:会话ID" 写入
    op.create_unique_constraint("uq_sessions_tenant_extref", "sessions",
                                ["tenant_id", "external_ref"])


def downgrade() -> None:
    op.drop_constraint("uq_sessions_tenant_extref", "sessions", type_="unique")
    op.drop_column("sessions", "external_ref")
    op.drop_index("ix_channel_connections_tenant", table_name="channel_connections")
    op.drop_constraint("uq_channel_tenant_platform", "channel_connections", type_="unique")
    op.drop_table("channel_connections")
