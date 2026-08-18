"""知识库管理 API（P5 核心）：文档 CRUD + 版本发布 + 缺口队列 + 草稿审核。"""
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_operator
from app.core.db import get_db
from app.models import (
    ChatSession, KbDocument, KbDocumentVersion, KbDraft, KbGapRecord, Message, Operator,
)
from app.services import llm

router = APIRouter(prefix="/api/console/kb", tags=["kb"],
                   dependencies=[Depends(get_current_operator)])

REFUSAL = "抱歉，这个问题我需要转人工处理。"


def _doc_dict(db: Session, doc: KbDocument) -> dict:
    ver = db.get(KbDocumentVersion, doc.current_version_id) if doc.current_version_id else None
    return {"id": str(doc.id), "code": doc.code, "title": doc.title,
            "category": doc.category, "status": doc.status,
            "version": ver.version if ver else None,
            "content": ver.content if ver else None,
            "effective_from": ver.effective_from if ver else None,
            "effective_to": ver.effective_to if ver else None,
            "created_at": doc.created_at}


class DocumentRequest(BaseModel):
    title: str
    category: str | None = None
    content: str
    effective_from: date | None = None   # 默认今天


@router.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.scalars(select(KbDocument).order_by(KbDocument.code)).all()
    return {"items": [_doc_dict(db, d) for d in docs], "total": len(docs)}


@router.post("/documents", status_code=201)
def create_document(body: DocumentRequest, db: Session = Depends(get_db),
                    op: Operator = Depends(get_current_operator)):
    next_code = f"kb-{len(db.scalars(select(KbDocument)).all()) + 1:03d}"
    doc = KbDocument(code=next_code, title=body.title, category=body.category,
                     status="draft", created_by=f"operator:{op.id}")
    db.add(doc)
    db.flush()
    ver = KbDocumentVersion(document_id=doc.id, version=1, content=body.content,
                            effective_from=body.effective_from or date.today(), status="pending")
    db.add(ver)
    db.flush()
    db.commit()
    return _doc_dict(db, doc)


@router.put("/documents/{doc_id}")
def update_document(doc_id: uuid.UUID, body: DocumentRequest,
                    db: Session = Depends(get_db)):
    """编辑 = 追加新版本草稿（版本只增不改，历史可回溯）。"""
    doc = db.get(KbDocument, doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    latest = db.scalar(select(func.max(KbDocumentVersion.version))
                       .where(KbDocumentVersion.document_id == doc.id)) or 0
    ver = KbDocumentVersion(document_id=doc.id, version=latest + 1, content=body.content,
                            effective_from=body.effective_from or date.today(), status="pending")
    db.add(ver)
    doc.title, doc.category = body.title, body.category or doc.category
    doc.status = "draft"
    db.flush()
    db.commit()
    # current_version_id 仍指旧版（发布才转正），响应里显式回显新草稿版本
    return {**_doc_dict(db, doc), "version": ver.version, "content": ver.content,
            "effective_from": ver.effective_from}


@router.post("/documents/{doc_id}/publish")
def publish_document(doc_id: uuid.UUID, db: Session = Depends(get_db)):
    """发布最新 pending 版本：旧的 active → retired，检索立即生效（对存量会话）。"""
    doc = db.get(KbDocument, doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    ver = db.scalar(select(KbDocumentVersion)
                    .where(KbDocumentVersion.document_id == doc.id,
                           KbDocumentVersion.status == "pending")
                    .order_by(KbDocumentVersion.version.desc()))
    if ver is None:
        raise HTTPException(409, "没有待发布的新版本")
    for old in db.scalars(select(KbDocumentVersion)
                          .where(KbDocumentVersion.document_id == doc.id,
                                 KbDocumentVersion.status == "active")).all():
        old.status = "retired"
    ver.status = "active"
    doc.status = "published"
    doc.current_version_id = ver.id
    db.commit()
    return _doc_dict(db, doc)


@router.post("/documents/{doc_id}/offline")
def offline_document(doc_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.get(KbDocument, doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    doc.status = "offline"
    db.commit()
    return _doc_dict(db, doc)


# ---------- 缺口队列 + 草稿（运营自改进闭环） ----------

@router.get("/gaps")
def list_gaps(db: Session = Depends(get_db)):
    """归因版缺口队列：拒答会话聚合（W4 归因链简化版：先全记 kb_gap，频率排序）。"""
    refusal_sessions = db.scalars(
        select(Message.session_id).where(Message.role == "agent", Message.content == REFUSAL)
    ).all()
    gaps = []
    for sid in refusal_sessions:
        question = db.scalar(select(Message)
                             .where(Message.session_id == sid, Message.role == "customer")
                             .order_by(Message.created_at.desc()))
        if not question or not question.content:
            continue
        digest = question.content[:60]
        row = db.scalar(select(KbGapRecord).where(KbGapRecord.question_digest == digest))
        if row is None:
            row = KbGapRecord(session_id=sid, question_digest=digest,
                              attribution="kb_gap", attribution_detail={})
            db.add(row)
            db.flush()
        gaps.append({"id": str(row.id), "question_digest": digest,
                     "attribution": row.attribution, "frequency": row.frequency,
                     "status": row.status})
    db.commit()
    gaps.sort(key=lambda g: g["frequency"], reverse=True)
    return {"items": gaps, "total": len(gaps)}


@router.post("/gaps/{gap_id}/generate-draft", status_code=201)
def generate_draft(gap_id: uuid.UUID, db: Session = Depends(get_db)):
    """LLM 按缺口生成 KB 草稿——永不自动入库，等人工审核。"""
    gap = db.get(KbGapRecord, gap_id)
    if gap is None:
        raise HTTPException(404, "gap not found")
    raw = llm.chat([
        {"role": "user",
         "content": f"顾客问了「{gap.question_digest}」但知识库答不了。"
                    f"请以客服知识条目格式（标题一行+正文两三句，含具体数字条件）写一份草稿。"
                    f"若该问题本就不该由客服回答（闲聊/超纲），回复：不适用"},
    ], agent="insight")
    if "不适用" in raw:
        raise HTTPException(422, "该问题不适合生成知识条目")
    draft = KbDraft(gap_record_id=gap.id,
                    title=gap.question_digest[:40],
                    content=raw.strip()[:2000],
                    source_sessions={"session_ids": [str(gap.session_id)] if gap.session_id else []})
    db.add(draft)
    gap.status = "draft_generated"
    db.commit()
    db.refresh(draft)
    return {"id": str(draft.id), "title": draft.title, "content": draft.content,
            "status": draft.status}


@router.get("/drafts")
def list_drafts(db: Session = Depends(get_db)):
    drafts = db.scalars(select(KbDraft).order_by(KbDraft.created_at.desc())).all()
    return {"items": [{"id": str(d.id), "title": d.title, "content": d.content,
                       "status": d.status, "created_at": d.created_at} for d in drafts],
            "total": len(drafts)}


@router.post("/drafts/{draft_id}/adopt", status_code=201)
def adopt_draft(draft_id: uuid.UUID, db: Session = Depends(get_db),
                op: Operator = Depends(get_current_operator)):
    """采纳草稿 → 建文档并直接发布（人工动作，闭环完成）。"""
    draft = db.get(KbDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "draft not found")
    if draft.status != "pending_review":
        raise HTTPException(409, f"草稿状态为 {draft.status}")
    next_code = f"kb-{len(db.scalars(select(KbDocument)).all()) + 1:03d}"
    title = (draft.title or "未命名条目").split("\n")[0][:60]
    content = draft.content or ""
    doc = KbDocument(code=next_code, title=title, category="faq", status="published",
                     created_by=f"operator:{op.id}")
    db.add(doc)
    db.flush()
    ver = KbDocumentVersion(document_id=doc.id, version=1, content=content,
                            effective_from=date.today())
    db.add(ver)
    db.flush()
    doc.current_version_id = ver.id
    draft.status, draft.reviewed_by, draft.reviewed_at = "adopted", op.id, datetime.now(timezone.utc)
    if draft.gap_record_id:
        gap = db.get(KbGapRecord, draft.gap_record_id)
        if gap:
            gap.status = "fixed"
    db.commit()
    return {"id": str(doc.id), "code": doc.code, "title": doc.title, "status": doc.status}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: uuid.UUID, db: Session = Depends(get_db),
                 op: Operator = Depends(get_current_operator)):
    draft = db.get(KbDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "draft not found")
    draft.status, draft.reviewed_by, draft.reviewed_at = "rejected", op.id, datetime.now(timezone.utc)
    if draft.gap_record_id:
        gap = db.get(KbGapRecord, draft.gap_record_id)
        if gap:
            gap.status = "ignored"
    db.commit()
    return {"id": str(draft.id), "status": draft.status}
