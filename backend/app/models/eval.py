from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EvalCase(Base):
    """Eval 黄金集用例：多轮脚本 + 期望断言。"""
    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario: Mapped[str] = mapped_column(String(32), nullable=False)     # faq|refund|refusal|escalation|idor_attack|injection_attack
    name: Mapped[str | None] = mapped_column(String(128))
    user_script: Mapped[dict] = mapped_column(JSONB, nullable=False)      # {"user_external_id": "demo", "messages": [...]}
    expectations: Mapped[dict] = mapped_column(JSONB, nullable=False)     # {expect_intent, must_refuse, should_escalate, expect_order_no}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("eval_cases.id"), nullable=False)
    preset: Mapped[str | None] = mapped_column(String(16))                # economy|balanced|performance
    trajectory: Mapped[dict | None] = mapped_column(JSONB)
    scores: Mapped[dict | None] = mapped_column(JSONB)                    # {resolved, intent_correct, refused_correct, escalated_correct}
    passed: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
