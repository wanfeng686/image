import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MockProduct(Base):
    __tablename__ = "mock_products"
    __table_args__ = (UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    category: Mapped[str | None] = mapped_column(String(32))


class MockOrder(Base):
    """模拟订单：商户推送/导入的订单数据（租户隔离）。"""
    __tablename__ = "mock_orders"
    __table_args__ = (UniqueConstraint("tenant_id", "order_no", name="uq_orders_tenant_order_no"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    order_no: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("mock_products.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="paid")        # paid|shipped|delivered|refunding|refunded
    address_masked: Mapped[str | None] = mapped_column(String(256))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MockShipment(Base):
    __tablename__ = "mock_shipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mock_orders.id"), nullable=False)
    carrier: Mapped[str | None] = mapped_column(String(32))
    tracking_no: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(24))                 # pending|in_transit|delivered|delayed
    estimated_delivery: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())
