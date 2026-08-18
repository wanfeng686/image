import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class KbDocument(Base):
    """知识库文档：版本化 + 生效期（检索过滤，防旧政策误导 QC/知识 Agent）。"""
    __tablename__ = "kb_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)   # 引用编号 kb-001
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))                     # policy|product|faq|shipping
    status: Mapped[str] = mapped_column(String(16), default="draft")             # draft|published|offline
    current_version_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("kb_document_versions.id", use_alter=True))
    created_by: Mapped[str | None] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KbDocumentVersion(Base):
    __tablename__ = "kb_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("kb_documents.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)   # 生效日期！检索时过滤
    effective_to: Mapped[date | None] = mapped_column(Date)              # NULL=长期有效
    status: Mapped[str] = mapped_column(String(16), default="active")    # pending|active|retired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KbGapRecord(Base):
    """知识缺口（已归因）：refusal 会话 → 归因链 → 待修复。"""
    __tablename__ = "kb_gap_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id"))
    question_digest: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str] = mapped_column(String(20), nullable=False)  # kb_gap|retrieval_miss|routing_error|tool_failure
    attribution_detail: Mapped[dict | None] = mapped_column(JSONB)
    frequency: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(16), default="open")      # open|draft_generated|ignored|fixed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KbDraft(Base):
    """缺口生成的 KB 草稿：人工审核后才可入库（永不自动入库）。"""
    __tablename__ = "kb_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gap_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("kb_gap_records.id"))
    title: Mapped[str | None] = mapped_column(String(128))
    content: Mapped[str | None] = mapped_column(Text)
    source_sessions: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending_review")  # pending_review|adopted|rejected
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("operators.id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
