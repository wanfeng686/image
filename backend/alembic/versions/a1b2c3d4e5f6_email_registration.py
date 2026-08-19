"""email registration: operators.email + email_codes

Revision ID: a1b2c3d4e5f6
Revises: b7e9f2a1c3d4
Create Date: 2026-08-19

电商渠道化第一步：注册改为邮箱+验证码。operators 加 email（唯一、可空兼容
存量账密账号）与 email_verified；新表 email_codes 存验证码哈希（10 分钟过期、
attempts 防暴力、used 一次性）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "b7e9f2a1c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operators", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("operators", sa.Column("email_verified", sa.Boolean(),
                                         nullable=False, server_default=sa.text("false")))
    # PG 唯一索引允许多个 NULL：存量无邮箱账号不受影响
    op.create_index("uq_operators_email", "operators", ["email"], unique=True)

    op.create_table(
        "email_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False, server_default="register"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_email_codes_email", "email_codes", ["email"])


def downgrade() -> None:
    op.drop_index("ix_email_codes_email", table_name="email_codes")
    op.drop_table("email_codes")
    op.drop_index("uq_operators_email", table_name="operators")
    op.drop_column("operators", "email_verified")
    op.drop_column("operators", "email")
