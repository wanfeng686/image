"""运营台 API：概览 / 会话（含轨迹时间线）/ 审批队列（含执行）。

响应按 API.md 契约手工组装 dict（复合查询多，Pydantic 出口模板收益低）。
鉴权：全部走 get_current_operator（Bearer token）。
SaaS 化：租户隔离——商户操作员只看自己租户的数据；平台管理员
（tenant_id=NULL）豁免过滤可看全部。越权访问其他租户资源一律 404
（与"不存在"同响应，不泄露资源存在性）。
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_operator
from app.core.db import get_db
from app.models import (
    AgentRun, ApprovalAction, ApprovalRequest, ChatSession, ExecutedAction,
    Message, MockOrder, Operator, SessionNote, User,
)
from app.services import approval as approval_svc

router = APIRouter(prefix="/api/console", tags=["console"],
                   dependencies=[Depends(get_current_operator)])


def _now():
    return datetime.now(timezone.utc)


def _tfilter(op: Operator, model):
    """租户过滤条件：平台管理员（tenant_id=NULL）返回 None = 不过滤。"""
    return None if op.tenant_id is None else model.tenant_id == op.tenant_id


def _session_tfilter(op: Operator):
    """经 sessions 表关联的表的租户过滤（approvals / agent_runs 等）。"""
    return None if op.tenant_id is None else ChatSession.tenant_id == op.tenant_id


def _check_session_scope(op: Operator, s: ChatSession) -> None:
    if op.tenant_id is not None and s.tenant_id != op.tenant_id:
        raise HTTPException(404, "session not found")


def _expire_timeouts(db: Session) -> int:
    """惰性超时扫描（W4 换 worker 定时任务）：过期 pending → expired + 订单回滚。"""
    rows = db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.status == "pending", ApprovalRequest.timeout_at < _now())).all()
    for req in rows:
        req.status = "expired"
        approval_svc.revert_refund_request(db, req)
    if rows:
        db.commit()
    return len(rows)


def _notify(db: Session, session_id, text: str) -> None:
    """审批结果以 agent 消息通知顾客会话。"""
    db.add(Message(session_id=session_id, role="agent", content=text, status="sent"))


def _approval_dict(req: ApprovalRequest, db: Session) -> dict:
    first_customer = db.scalar(
        select(Message).where(Message.session_id == req.session_id, Message.role == "customer")
        .order_by(Message.created_at))
    return {
        "id": str(req.id), "session_id": str(req.session_id),
        "action_type": req.action_type, "action_payload": req.action_payload,
        "risk_score": float(req.risk_score), "risk_breakdown": req.risk_breakdown,
        "risk_level": req.risk_level,
        "required_approvals": req.required_approvals, "granted_approvals": req.granted_approvals,
        "status": req.status, "timeout_at": req.timeout_at,
        "session_summary": (first_customer.content or "")[:60] if first_customer else "",
        "created_at": req.created_at,
    }


# ─────────────────────────── P2 概览 ───────────────────────────

@router.get("/dashboard/overview")
def dashboard_overview(range: str = "today", db: Session = Depends(get_db),
                       op: Operator = Depends(get_current_operator)):
    _expire_timeouts(db)
    since = {"today": timedelta(days=1), "7d": timedelta(days=7), "30d": timedelta(days=30)}[range]
    cutoff = _now() - since
    tf = _tfilter(op, ChatSession)

    total = db.scalar(select(func.count()).select_from(ChatSession)
                      .where(tf, ChatSession.created_at >= cutoff))
    escalated = db.scalar(select(func.count()).select_from(ChatSession)
                          .where(tf, ChatSession.created_at >= cutoff,
                                 ChatSession.status == "escalated"))
    pending = db.scalar(select(func.count()).select_from(ApprovalRequest)
                        .join(ChatSession, ApprovalRequest.session_id == ChatSession.id)
                        .where(_session_tfilter(op), ApprovalRequest.status == "pending"))
    llm_calls = db.scalar(
        select(func.count()).select_from(AgentRun)
        .join(ChatSession, AgentRun.session_id == ChatSession.id)
        .where(_session_tfilter(op),
               AgentRun.created_at >= cutoff, AgentRun.provider_name.isnot(None)))

    # 趋势：近 7 天每日会话量（注意：参数名 range 遮蔽了内置 range，这里用元组字面量）
    trend = []
    for i in (6, 5, 4, 3, 2, 1, 0):
        day = (_now() - timedelta(days=i)).date()
        n = db.scalar(select(func.count()).select_from(ChatSession)
                      .where(tf, func.date(ChatSession.created_at) == day))
        trend.append({"date": str(day), "sessions": n})

    # 意图分布（triage 快照聚合；行数小，Python 侧聚合最稳）
    from collections import Counter

    counter = Counter()
    for li in db.scalars(select(ChatSession.last_intent)
                         .where(tf, ChatSession.last_intent.isnot(None))).all():
        intents_list = (li or {}).get("intents") or ["unknown"]
        counter[intents_list[0]] += 1
    intents = [{"intent": k, "count": v} for k, v in counter.items()]

    # Agent 调用统计
    agent_rows = db.execute(
        select(AgentRun.agent_name, func.count())
        .join(ChatSession, AgentRun.session_id == ChatSession.id)
        .where(_session_tfilter(op))
        .group_by(AgentRun.agent_name)).all()

    return {
        "kpis": {
            "sessions": total,
            "escalation_rate": round(escalated / total, 3) if total else 0.0,
            "pending_approvals": pending,
            "llm_calls": llm_calls,
        },
        "charts": {
            "trend": trend,
            "intents": intents,
            "agent_calls": [{"agent": r[0], "count": r[1]} for r in agent_rows],
        },
    }


# ─────────────────────────── P3 会话 ───────────────────────────

@router.get("/sessions")
def list_sessions(status: str | None = None, q: str | None = None,
                  page: int = 1, page_size: int = 20, db: Session = Depends(get_db),
                  op: Operator = Depends(get_current_operator)):
    query = select(ChatSession).order_by(ChatSession.last_message_at.desc().nullslast())
    if (tf := _tfilter(op, ChatSession)) is not None:
        query = query.where(tf)
    if status:
        query = query.where(ChatSession.status == status)
    if q:
        query = query.join(User, ChatSession.user_id == User.id).where(User.nickname.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    sessions = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()

    items = []
    for s in sessions:
        user = db.get(User, s.user_id)
        msg_count = db.scalar(select(func.count()).select_from(Message)
                              .where(Message.session_id == s.id))
        has_pending = db.scalar(select(func.count()).select_from(ApprovalRequest)
                                .where(ApprovalRequest.session_id == s.id,
                                       ApprovalRequest.status == "pending")) > 0
        nickname = user.nickname if user else "?"
        items.append({
            "id": str(s.id),
            "user": {"nickname": nickname[:1] + "**" if len(nickname) > 1 else nickname,
                     "user_tier": user.user_tier if user else "normal"},
            "status": s.status, "last_intent": s.last_intent,
            "satisfaction": s.satisfaction, "message_count": msg_count,
            "has_pending_approval": has_pending,
            "last_message_at": s.last_message_at, "created_at": s.created_at,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/sessions/{session_id}")
def session_detail(session_id: uuid.UUID, db: Session = Depends(get_db),
                   op: Operator = Depends(get_current_operator)):
    s = db.get(ChatSession, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    _check_session_scope(op, s)
    messages = db.scalars(select(Message).where(Message.session_id == session_id)
                          .order_by(Message.created_at)).all()
    runs = db.scalars(select(AgentRun).where(AgentRun.session_id == session_id)
                      .order_by(AgentRun.created_at)).all()
    pendings = db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.session_id == session_id, ApprovalRequest.status == "pending")).all()
    notes = db.scalars(select(SessionNote).where(SessionNote.session_id == session_id)
                       .order_by(SessionNote.created_at)).all()
    op_names = {str(o.id): o.display_name for o in db.scalars(
        select(Operator).where((Operator.tenant_id == s.tenant_id)
                               | Operator.tenant_id.is_(None)))}
    return {
        "session": {"id": str(s.id), "status": s.status,
                    "rolling_summary": s.rolling_summary, "slots": s.slots,
                    "sentiment": float(s.sentiment) if s.sentiment is not None else None,
                    "escalated_reason": s.escalated_reason,
                    "taken_over_by": op_names.get(str(s.taken_over_by)) if s.taken_over_by else None,
                    "satisfaction": s.satisfaction, "steps_used": s.steps_used},
        "messages": [{"id": str(m.id), "role": m.role, "content": m.content,
                      "content_type": m.content_type, "card_data": m.card_data,
                      "agent_source": m.agent_source, "created_at": m.created_at}
                     for m in messages],
        "agent_runs": [{"id": str(r.id), "agent_name": r.agent_name, "graph_node": r.graph_node,
                        "provider_name": r.provider_name, "model_name": r.model_name,
                        "status": r.status, "attempt": r.attempt, "latency_ms": r.latency_ms,
                        "input": r.input, "output": r.output, "created_at": r.created_at}
                       for r in runs],
        "pending_approvals": [{"id": str(p.id), "risk_level": p.risk_level,
                               "summary": f"退款 ¥{p.action_payload.get('amount', 0):.2f}",
                               "status": p.status} for p in pendings],
        "notes": [{"id": str(n.id), "operator": op_names.get(str(n.operator_id), "?"),
                   "content": n.content, "created_at": n.created_at} for n in notes],
    }


@router.post("/sessions/{session_id}/takeover")
def takeover(session_id: uuid.UUID, db: Session = Depends(get_db),
             op: Operator = Depends(get_current_operator)):
    s = db.get(ChatSession, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    _check_session_scope(op, s)
    s.status = "escalated"
    s.escalated_reason = "takeover"
    s.taken_over_by = op.id
    db.commit()
    return {"session": {"id": str(s.id), "status": s.status,
                        "taken_over_by": {"id": str(op.id), "display_name": op.display_name}}}


class NoteRequest(BaseModel):
    content: str


@router.post("/sessions/{session_id}/notes", status_code=201)
def add_note(session_id: uuid.UUID, body: NoteRequest, db: Session = Depends(get_db),
             op: Operator = Depends(get_current_operator)):
    s = db.get(ChatSession, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    _check_session_scope(op, s)
    note = SessionNote(session_id=session_id, operator_id=op.id, content=body.content)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"id": str(note.id), "operator": op.display_name,
            "content": note.content, "created_at": note.created_at}


@router.get("/sessions/{session_id}/export")
def export_trace(session_id: uuid.UUID, db: Session = Depends(get_db),
                 op: Operator = Depends(get_current_operator)):
    import json as _json

    from fastapi.encoders import jsonable_encoder

    detail = session_detail(session_id, db, op)
    return Response(
        content=_json.dumps(jsonable_encoder(detail), ensure_ascii=False, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=trace-{session_id}.json"},
    )


# ─────────────────────────── P4 审批 ───────────────────────────

def _get_scoped_approval(db: Session, op: Operator, approval_id: uuid.UUID) -> ApprovalRequest:
    req = db.get(ApprovalRequest, approval_id)
    if req is None:
        raise HTTPException(404, "approval not found")
    if op.tenant_id is not None:
        sess = db.get(ChatSession, req.session_id)
        if sess is None or sess.tenant_id != op.tenant_id:
            raise HTTPException(404, "approval not found")
    return req


@router.get("/approvals")
def list_approvals(status: str = "pending", page: int = 1, page_size: int = 20,
                   db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    _expire_timeouts(db)
    query = select(ApprovalRequest).join(
        ChatSession, ApprovalRequest.session_id == ChatSession.id)
    if (tf := _session_tfilter(op)) is not None:
        query = query.where(tf)
    query = query.order_by(ApprovalRequest.created_at.desc())
    if status != "all":
        query = query.where(ApprovalRequest.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_approval_dict(r, db) for r in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/approvals/{approval_id}")
def approval_detail(approval_id: uuid.UUID, db: Session = Depends(get_db),
                    op: Operator = Depends(get_current_operator)):
    req = _get_scoped_approval(db, op, approval_id)
    data = _approval_dict(req, db)
    msgs = db.scalars(select(Message).where(Message.session_id == req.session_id)
                      .order_by(Message.created_at).limit(10)).all()
    actions = db.scalars(select(ApprovalAction)
                         .where(ApprovalAction.approval_request_id == req.id)
                         .order_by(ApprovalAction.created_at)).all()
    op_names = {str(o.id): o.display_name for o in db.scalars(select(Operator))}
    data["conversation_digest"] = [{"role": m.role, "content": (m.content or "")[:80]} for m in msgs]
    data["actions"] = [{"operator": op_names.get(str(a.operator_id), "?"),
                        "action": a.action, "note": a.note, "created_at": a.created_at}
                       for a in actions]
    return data


def _do_approve(db: Session, req: ApprovalRequest, op: Operator, note: str | None) -> dict:
    if req.status != "pending":
        raise HTTPException(409, {"code": "ALREADY_RESOLVED", "message": f"该审批已是 {req.status}"})
    db.add(ApprovalAction(approval_request_id=req.id, operator_id=op.id,
                          action="approve", note=note))
    req.granted_approvals += 1
    executed = None
    if req.granted_approvals >= req.required_approvals:
        req.status = "approved"
        # 真正执行资金动作（幂等：executed_actions 拦重放）
        session = db.get(ChatSession, req.session_id)
        order = db.scalar(select(MockOrder).where(
            MockOrder.order_no == req.action_payload.get("order_no"),
            MockOrder.tenant_id == session.tenant_id))
        user = db.get(User, session.user_id)
        executed, _ = approval_svc.execute_refund(
            db, req.session_id, order, user, approval_request=req,
            executed_by=f"operator:{op.id}")
        if session:
            session.status = "active"
            amount = req.action_payload.get("amount", 0)
            extra = "" if req.required_approvals == 1 else "（双人审批通过）"
            _notify(db, req.session_id,
                    f"好消息！您的退款申请已通过审批{extra}，¥{amount:.2f} 将在 1-7 个工作日原路退回。")
    db.commit()
    db.refresh(req)
    return {"approval": {"id": str(req.id), "status": req.status,
                         "granted_approvals": req.granted_approvals},
            "executed_action": ({"id": str(executed.id), "status": executed.status,
                                 "result": executed.result} if executed else None)}


class ActionRequest(BaseModel):
    note: str | None = None


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: uuid.UUID, body: ActionRequest | None = None,
            db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    req = _get_scoped_approval(db, op, approval_id)
    return _do_approve(db, req, op, (body.note if body else None))


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: uuid.UUID, body: ActionRequest,
           db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    if not body.note:
        raise HTTPException(422, "拒绝必须填写理由")
    req = _get_scoped_approval(db, op, approval_id)
    if req.status != "pending":
        raise HTTPException(409, {"code": "ALREADY_RESOLVED", "message": f"该审批已是 {req.status}"})
    db.add(ApprovalAction(approval_request_id=req.id, operator_id=op.id,
                          action="reject", note=body.note))
    req.status = "rejected"
    approval_svc.revert_refund_request(db, req)
    session = db.get(ChatSession, req.session_id)
    if session and session.status == "waiting_approval":
        session.status = "active"
    _notify(db, req.session_id, f"很抱歉，您的退款申请未通过审核。原因：{body.note[:60]}。如有疑问可转人工客服。")
    db.commit()
    return {"approval": {"id": str(req.id), "status": req.status}}


@router.post("/approvals/{approval_id}/return")
def returned(approval_id: uuid.UUID, body: ActionRequest,
             db: Session = Depends(get_db), op: Operator = Depends(get_current_operator)):
    req = _get_scoped_approval(db, op, approval_id)
    if req.status != "pending":
        raise HTTPException(409, {"code": "ALREADY_RESOLVED", "message": f"该审批已是 {req.status}"})
    db.add(ApprovalAction(approval_request_id=req.id, operator_id=op.id,
                          action="return", note=body.note))
    req.status = "returned"
    session = db.get(ChatSession, req.session_id)
    if session and session.status == "waiting_approval":
        session.status = "active"
    _notify(db, req.session_id, f"关于您的退款申请，客服需要补充信息：{(body.note or '')[:60]}")
    db.commit()
    return {"approval": {"id": str(req.id), "status": req.status},
            "session": {"status": session.status if session else None}}


@router.post("/approvals/{approval_id}/remind")
def remind(approval_id: uuid.UUID, db: Session = Depends(get_db),
           op: Operator = Depends(get_current_operator)):
    req = _get_scoped_approval(db, op, approval_id)
    # 催办目标：优先同租户管理员，回退平台管理员
    target = db.scalar(select(Operator).where(
        Operator.role == "admin", Operator.tenant_id == op.tenant_id))
    if target is None:
        target = db.scalar(select(Operator).where(
            Operator.role == "admin", Operator.tenant_id.is_(None)))
    if target is None:
        target = op
    db.add(ApprovalAction(approval_request_id=req.id, operator_id=op.id, action="remind"))
    db.commit()
    return {"ok": True, "reminded_operator": {"id": str(target.id), "display_name": target.display_name}}


class BatchRequest(BaseModel):
    ids: list[uuid.UUID]
    note: str | None = None


@router.post("/approvals/batch-approve")
def batch_approve(body: BatchRequest, db: Session = Depends(get_db),
                  op: Operator = Depends(get_current_operator)):
    succeeded, failed = [], []
    for aid in body.ids:
        try:
            req = _get_scoped_approval(db, op, aid)
            _do_approve(db, req, op, body.note)
            succeeded.append(str(aid))
        except HTTPException:
            failed.append({"id": str(aid), "code": "ALREADY_RESOLVED"})
    return {"succeeded": succeeded, "failed": failed}
