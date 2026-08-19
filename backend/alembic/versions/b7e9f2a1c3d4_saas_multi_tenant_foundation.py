"""saas multi-tenant foundation: tenants table + tenant_id columns + composite uniques

Revision ID: b7e9f2a1c3d4
Revises: 4aedf8ec1816
Create Date: 2026-08-19

SaaS 化第一步：新增 tenants 表，业务表加 tenant_id（存量数据全部归入种子
「演示商城」租户），全局唯一约束重建为租户内唯一。operators.tenant_id 可空
（NULL = 平台管理员），operators.username 保持全局唯一（登录定位账号）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "b7e9f2a1c3d4"
down_revision = "4aedf8ec1816"
branch_labels = None
depends_on = None

# 种子租户固定 ID：迁移回填与 scripts/seed.py 共用同一常量
DEMO_TENANT_ID = "7d5a3f2e-1b4c-4e6a-9f8d-3a2b1c0d9e8f"

# 加 tenant_id 且收紧 NOT NULL 的业务表
TENANT_TABLES = [
    "users", "sessions", "kb_documents", "mock_products", "mock_orders",
    "mock_shipments", "risk_rules", "escalation_rules", "model_providers",
    "agent_model_bindings", "insight_reports",
]

# (旧约束, 新约束, 表, 列)
UNIQUE_REBUILDS = [
    ("users_external_id_key", "uq_users_tenant_external", "users", "external_id"),
    ("mock_products_sku_key", "uq_products_tenant_sku", "mock_products", "sku"),
    ("mock_orders_order_no_key", "uq_orders_tenant_order_no", "mock_orders", "order_no"),
    ("risk_rules_rule_key_key", "uq_riskrules_tenant_key", "risk_rules", "rule_key"),
    ("insight_reports_report_date_key", "uq_insights_tenant_date", "insight_reports", "report_date"),
    ("kb_documents_code_key", "uq_kbdocs_tenant_code", "kb_documents", "code"),
    ("model_providers_name_key", "uq_providers_tenant_name", "model_providers", "name"),
    ("agent_model_bindings_agent_name_key", "uq_bindings_tenant_agent", "agent_model_bindings", "agent_name"),
]


def upgrade() -> None:
    # 1) tenants 表
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("plan", sa.String(16), nullable=False, server_default="free"),
        sa.Column("widget_key", sa.String(64), nullable=False),
        sa.Column("api_secret", sa.String(64), nullable=False),
        sa.Column("brand", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("allowed_origins", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_tenants_widget_key", "tenants", ["widget_key"])
    op.create_unique_constraint("uq_tenants_api_secret", "tenants", ["api_secret"])

    # 2) 种子租户（存量数据归属）
    op.execute(
        f"""INSERT INTO tenants (id, name, widget_key, api_secret, brand)
            VALUES ('{DEMO_TENANT_ID}', '演示商城', 'pk_demo000000000000', 'sk_demo000000000000',
                    '{{"title": "演示商城智能客服", "welcome": "您好～我是演示商城的智能客服，请问有什么可以帮您？", "theme_color": "#4F46E5"}}')"""
    )

    # 3) 业务表加 tenant_id + 回填 + 外键
    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.execute(f"UPDATE {table} SET tenant_id = '{DEMO_TENANT_ID}' WHERE tenant_id IS NULL")
        op.create_foreign_key(f"fk_{table}_tenant", table, "tenants", ["tenant_id"], ["id"])

    # operators：可空（平台管理员 NULL，现有 admin/approver 保持平台级）
    op.add_column("operators", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_operators_tenant", "operators", "tenants", ["tenant_id"], ["id"])

    # 4) 业务表收紧 NOT NULL
    for table in TENANT_TABLES:
        op.alter_column(table, "tenant_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    # 5) 唯一约束重建：全局唯一 → 租户内唯一
    for old_name, new_name, table, col in UNIQUE_REBUILDS:
        op.drop_constraint(old_name, table, type_="unique")
        op.create_unique_constraint(new_name, table, ["tenant_id", col])


def downgrade() -> None:
    # 注意：降级会把演示租户之外的数据变成孤儿，仅开发环境使用
    for old_name, new_name, table, col in UNIQUE_REBUILDS:
        op.drop_constraint(new_name, table, type_="unique")
        op.create_unique_constraint(old_name, table, [col])

    op.drop_constraint("fk_operators_tenant", "operators", type_="foreignkey")
    op.drop_column("operators", "tenant_id")

    for table in TENANT_TABLES:
        op.drop_constraint(f"fk_{table}_tenant", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")

    op.execute(f"DELETE FROM tenants WHERE id = '{DEMO_TENANT_ID}'")
    op.drop_constraint("uq_tenants_api_secret", "tenants", type_="unique")
    op.drop_constraint("uq_tenants_widget_key", "tenants", type_="unique")
    op.drop_table("tenants")
