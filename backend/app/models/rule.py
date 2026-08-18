import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RiskRule(Base):
    """风险规则（key-value）：阈值/权重集中管理，运营台可改。"""
    __tablename__ = "risk_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_key: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("operators.id"))


class EscalationRule(Base):
    """升级硬规则：keyword / condition 两类，priority 越小越先评估。"""
    __tablename__ = "escalation_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)     # keyword | condition
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)            # {"keywords":[...]} / {"max_repeat":3}
    priority: Mapped[int] = mapped_column(SmallInteger, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
