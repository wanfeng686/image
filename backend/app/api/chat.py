import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import knowledge as knowledge_agent
from app.agent import qc as qc_agent
from app.core.db import get_db
from app.graph.nodes.order import order_node
from app.graph.nodes.resolution import resolution_node
from app.graph.nodes.triage import triage_node
from app.graph.supervisor import supervisor
from app.models import ChatSession, Message, User
from app.schemas.message import MessageOut, MessagePage
from app.schemas.session import SessionOut
from app.services import escalation as escalation_svc
from app.services import kb, llm, tenants as tenant_svc
from app.services.runs import Timer, log_run

router = APIRouter(prefix="/api/chat", tags=["chat"])

REFUSAL_TEXT = "抱歉，这个问题我需要转人工处理。"


class CreateSessionRequest(BaseModel):
    user_id: uuid.UUID | None = None        # 指定已有用户
    user_external_id: str | None = None     # 按渠道 ID 绑定（无则自动建），演示页用


class SendMessageRequest(BaseModel):
    content: str


class RateRequest(BaseModel):
    rating: int  # 1=👍  -1=👎


def sse_event(event: str, data: dict) -> str:
    """把一条数据编码成 SSE 协议的一帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_history(db: Session, session_id) -> list[dict]:
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(10)
        .all()
    )[::-1]
    return [{"role": r.role, "content": r.content} for r in rows if r.content]


def _base_state(db, session, question: str, history: list[dict], message_id) -> dict:
    """编排期注入：节点共用同一个 DB 事务 + 会话对象与用户身份。"""
    return {
        "question": question, "history": history, "steps": [],
        "intent": None, "chunks": [], "answer": None, "refused": False,
        "card": None, "order_no": None, "sentiment": None, "session_status": None,
        "db": db, "session_obj": session, "user_id": session.user_id,
        "message_id": message_id,
    }


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: CreateSessionRequest, db: Session = Depends(get_db),
                   x_widget_key: str | None = Header(default=None)):
    """SaaS 化：会话必须归属某个租户，凭 X-Widget-Key 定位（与 /api/widget/sessions 同一套鉴权）。
    user_external_id 在租户内绑定/创建（跨租户永不串号）。"""
    tenant = tenant_svc.require_tenant_by_widget_key(db, x_widget_key)
    if body.user_id:
        user = db.scalar(select(User).where(
            User.id == body.user_id, User.tenant_id == tenant.id))
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
    elif body.user_external_id:
        user = db.scalar(select(User).where(
            User.tenant_id == tenant.id, User.external_id == body.user_external_id))
        if user is None:
            user = User(tenant_id=tenant.id, external_id=body.user_external_id,
                        nickname=f"顾客{uuid.uuid4().hex[:6]}")
            db.add(user)
            db.flush()
    else:
        user = User(tenant_id=tenant.id, nickname=f"顾客{uuid.uuid4().hex[:6]}")
        db.add(user)
        db.flush()

    session = ChatSession(tenant_id=tenant.id, user_id=user.id, config_snapshot={})
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.post("/sessions/{session_id}/messages", response_model=list[MessageOut], status_code=201)
def send_message(session_id: uuid.UUID, body: SendMessageRequest, db: Session = Depends(get_db)):
    """同步接口：整图跑完一次性返回（后台任务/脚本友好）。"""
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    history = _build_history(db, session_id)
    customer_msg = Message(session_id=session_id, role="customer", content=body.content)
    db.add(customer_msg)
    db.flush()

    # 升级硬规则前置闸（W3）：命中直接转人工，不进状态机
    user = db.get(User, session.user_id)
    hit, reason = escalation_svc.evaluate(db, session, user, body.content)
    if hit:
        session.status = "escalated"
        session.escalated_reason = reason
        agent_msg = Message(session_id=session_id, role="agent",
                            content=escalation_svc.ESCALATION_REPLY)
        db.add(agent_msg)
        session.last_message_at = datetime.now(timezone.utc)
        session.steps_used = (session.steps_used or 0) + 1
        log_run(db, session.id, "supervisor", "escalation",
                input_summary={"question": body.content[:200]},
                output={"escalated": True, "reason": reason}, message_id=customer_msg.id)
        db.commit()
        db.refresh(customer_msg)
        db.refresh(agent_msg)
        return [customer_msg, agent_msg]

    result = supervisor.invoke(_base_state(db, session, body.content, history, customer_msg.id))

    intent = result.get("intent")
    card = result.get("card")
    agent_msg = Message(
        session_id=session_id, role="agent",
        content=result.get("answer"),
        content_type="card" if card else "text",
        card_data=card,
        agent_source={"faq": "knowledge", "order_query": "order", "refund": "resolution"}.get(intent),
    )
    db.add(agent_msg)

    session.last_message_at = datetime.now(timezone.utc)
    session.steps_used = (session.steps_used or 0) + len(result.get("steps", []))
    if result.get("session_status"):
        session.status = result["session_status"]
    if result.get("refused"):
        session.escalated_reason = "refusal"

    db.commit()
    db.refresh(customer_msg)
    db.refresh(agent_msg)
    return [customer_msg, agent_msg]


@router.get("/sessions/{session_id}/messages", response_model=MessagePage)
def list_messages(session_id: uuid.UUID, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    msgs = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return MessagePage(items=msgs, total=len(msgs), page=1, page_size=20)


@router.post("/sessions/{session_id}/rate", response_model=SessionOut)
def rate_session(session_id: uuid.UUID, body: RateRequest, db: Session = Depends(get_db)):
    if body.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating 必须是 1 或 -1")
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    session.satisfaction = body.rating
    db.commit()
    db.refresh(session)
    return session


@router.post("/sessions/{session_id}/escalate", response_model=SessionOut)
def escalate_session(session_id: uuid.UUID, db: Session = Depends(get_db)):
    """铁律（DESIGN §4.3）：用户点"转人工"永远直接转，绝不允许机器人拦一道。"""
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    session.status = "escalated"
    session.escalated_reason = "user_request"
    db.commit()
    db.refresh(session)
    return session


# ---------- SSE 流式接口（W2 版：三路由 + 卡片 + 审批事件） ----------

@router.post("/sessions/{session_id}/messages/stream")
def stream_message(session_id: uuid.UUID, body: SendMessageRequest, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    def generate():
        agent_id = uuid.uuid4()

        # 历史快照先于本条消息落库（不含当前问题，避免重复）
        history = _build_history(db, session_id)
        customer_msg = Message(session_id=session_id, role="customer",
                               content=body.content, content_type="text", status="sent")
        db.add(customer_msg)
        db.flush()
        yield sse_event("turn_start", {"message_id": str(agent_id)})

        # 升级硬规则前置闸（W3）：命中直接转人工
        user = db.get(User, session.user_id)
        hit, reason = escalation_svc.evaluate(db, session, user, body.content)
        if hit:
            session.status = "escalated"
            session.escalated_reason = reason
            answer, card, agent_source = escalation_svc.ESCALATION_REPLY, None, None
            log_run(db, session.id, "supervisor", "escalation",
                    input_summary={"question": body.content[:200]},
                    output={"escalated": True, "reason": reason}, message_id=customer_msg.id)
            yield sse_event("message_delta", {"message_id": str(agent_id), "delta": answer})
            yield sse_event("escalated", {"reason": reason})
            yield sse_event("session_status", {"status": "escalated"})
            steps = ["escalation"]
            agent_msg = Message(
                id=agent_id, session_id=session_id, role="agent",
                content=answer, content_type="text", status="sent",
            )
            db.add(agent_msg)
            session.last_message_at = datetime.now(timezone.utc)
            session.steps_used = (session.steps_used or 0) + len(steps)
            db.commit()
            db.refresh(agent_msg)
            yield sse_event("message_completed",
                            {"message": MessageOut.model_validate(agent_msg).model_dump(mode="json")})
            yield sse_event("turn_end", {"message_id": str(agent_id), "steps": steps})
            return

        # 1) 分诊（LLM，失败自动关键词兜底）
        state = _base_state(db, session, body.content, history, customer_msg.id)
        state = {**state, **triage_node(state)}
        intent = state["intent"]
        agent_source, card, session_status = None, None, None

        # 2) 按意图路由
        if intent == "faq":
            yield sse_event("agent_status", {"agent": "knowledge", "status": "working"})
            answer = None
            with Timer() as t:
                chunks = kb.retrieve(db, session.tenant_id, body.content)
                if chunks:
                    pieces = []
                    try:
                        for token in llm.chat_stream(knowledge_agent.build_messages(body.content, chunks),
                                                      agent="knowledge", tenant_id=session.tenant_id):
                            pieces.append(token)
                            yield sse_event("message_delta", {"message_id": str(agent_id), "delta": token})
                        answer = "".join(pieces)
                    except Exception as exc:  # noqa: BLE001 —— 流挂了走拒答，不裸抛
                        log_run(db, session.id, "knowledge", "knowledge",
                                input_summary={"question": body.content[:200]},
                                output=None, status="failed", error=str(exc),
                                message_id=customer_msg.id, used_llm=True)
            if answer and not knowledge_agent.is_refusal(answer):
                # 流式路径的质检闸：确定性预检（引用存在+数字覆盖）。
                # 不过 → 撤回已流出的答案改拒答（打给用户的内容以 message_completed 定格为准）。
                det_ok, det_problems = qc_agent.deterministic_check(answer, chunks)
                log_run(db, session.id, "qc", "qc",
                        input_summary={"answer": answer[:200]},
                        output={"pass": det_ok, "problems": det_problems, "stream_path": True},
                        message_id=customer_msg.id,
                        status="success" if det_ok else "rejected")
                if det_ok:
                    agent_source = "knowledge"
                    log_run(db, session.id, "knowledge", "knowledge",
                            input_summary={"question": body.content[:200], "chunks": [c["id"] for c in chunks]},
                            output={"answer": answer[:300]}, latency_ms=t.ms,
                            message_id=customer_msg.id, used_llm=True)
                    log_run(db, session.id, "supervisor", "respond",
                            input_summary=None, output={"delivered": True},
                            message_id=customer_msg.id)
                else:
                    answer = REFUSAL_TEXT
                    log_run(db, session.id, "supervisor", "respond",
                            input_summary=None, output={"refused": True, "qc_rejected": True},
                            message_id=customer_msg.id)
            else:
                answer = REFUSAL_TEXT
                log_run(db, session.id, "supervisor", "respond",
                        input_summary=None, output={"refused": True},
                        message_id=customer_msg.id)
            yield sse_event("agent_status", {"agent": "knowledge", "status": "done"})
            steps = ["triage", "knowledge", "respond"]

        elif intent in ("order_query", "refund"):
            node, node_name = (order_node, "order") if intent == "order_query" else (resolution_node, "resolution")
            yield sse_event("agent_status", {"agent": node_name, "status": "working"})
            out = node(state)
            answer, card = out.get("answer"), out.get("card")
            session_status = out.get("session_status")
            agent_source = node_name
            yield sse_event("message_delta", {"message_id": str(agent_id), "delta": answer})
            yield sse_event("agent_status", {"agent": node_name, "status": "done"})
            log_run(db, session.id, "supervisor", "respond",
                    input_summary=None, output={"delivered": True, "card": bool(card)},
                    message_id=customer_msg.id)
            steps = ["triage", node_name, "respond"]

        else:
            answer = REFUSAL_TEXT
            log_run(db, session.id, "supervisor", "respond",
                    input_summary=None, output={"refused": True},
                    message_id=customer_msg.id)
            yield sse_event("message_delta", {"message_id": str(agent_id), "delta": answer})
            steps = ["triage", "respond"]

        # 3) 落库：机器消息（可能带卡片）+ 会话统计
        agent_msg = Message(
            id=agent_id, session_id=session_id, role="agent",
            content=answer, content_type="card" if card else "text",
            card_data=card, agent_source=agent_source, status="sent",
        )
        db.add(agent_msg)
        session.last_message_at = datetime.now(timezone.utc)
        session.steps_used = (session.steps_used or 0) + len(steps)
        if session_status:
            session.status = session_status
        db.commit()
        db.refresh(agent_msg)

        # 4) 协议事件：卡片 → 审批横幅 → 会话状态 → 完成 → 收尾
        if card:
            yield sse_event("card", {"message_id": str(agent_id), "card_data": card})
        if card and card.get("type") == "refund" and card.get("status") in ("pending_approval", "pending"):
            yield sse_event("approval_pending", {
                "approval_id": card.get("approval_id"),
                "summary": f"退款 ¥{card.get('amount', 0):.2f} 待审批",
                "timeout_at": card.get("timeout_at"),
            })
            yield sse_event("session_status", {"status": "waiting_approval"})
        yield sse_event("message_completed",
                        {"message": MessageOut.model_validate(agent_msg).model_dump(mode="json")})
        yield sse_event("turn_end", {"message_id": str(agent_id), "steps": steps})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
