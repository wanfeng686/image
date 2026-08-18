import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ApprovalRequest(Base):
    """审批请求：中/高风险处置动作进人工队列，幂等键防重放。"""
    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"))
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)   # refund | modify_order | other_write
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)    # {order_no, amount, reason}
    risk_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    risk_breakdown: Mapped[dict | None] = mapped_column(JSONB)             # {amount:32, freq:40, profile:0, sentiment:10}
    risk_level: Mapped[str | None] = mapped_column(String(8))              # low | medium | high
    required_approvals: Mapped[int] = mapped_column(default=1)             # high 级=2（双签）
    granted_approvals: Mapped[int] = mapped_column(default=0)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # {session_id}:{action_type}:{order_no}
    status: Mapped[str] = mapped_column(String(16), default="pending")     # pending|approved|rejected|returned|expired
    timeout_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    session_config_ver: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ApprovalAction(Base):
    """审批操作审计：谁在何时批/拒/驳/催。"""
    __tablename__ = "approval_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("approval_requests.id"), nullable=False)
    operator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("operators.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)        # approve | reject | return | remind
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())


class ExecutedAction(Base):
    """已执行写操作（资金动作流水）：执行层幂等，永不双退款。"""
    __tablename__ = "executed_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("approval_requests.id"))  # 小额自动执行为 NULL
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    executed_by: Mapped[str | None] = mapped_column(String(48))            # auto | operator:{id}
    status: Mapped[str] = mapped_column(String(16), default="executed")    # executed|failed|rolled_back
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
