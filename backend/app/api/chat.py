import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent import knowledge as knowledge_agent
from app.core.db import get_db
from app.graph.supervisor import supervisor
from app.models import ChatSession, Message, User
from app.schemas.message import MessageOut, MessagePage
from app.schemas.session import SessionOut
from app.services import kb, llm

router = APIRouter(prefix="/api/chat", tags=["chat"])


class CreateSessionRequest(BaseModel):
    user_id: uuid.UUID | None = None  # 不传就自动建一个新顾客


class SendMessageRequest(BaseModel):
    content: str


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: CreateSessionRequest, db: Session = Depends(get_db)):
    if body.user_id:
        user = db.get(User, body.user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
    else:
        user = User(nickname=f"顾客{uuid.uuid4().hex[:6]}")
        db.add(user)
        db.flush()

    session = ChatSession(user_id=user.id, config_snapshot={})
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
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    # 1. 取最近10条历史（此刻还不含本条），喂给图
    history_rows = (
        db.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.created_at.desc())
        .limit(10)
        .all()
    )[::-1]
    history = [{"role": r.role, "content": r.content} for r in history_rows]

    # 2. 存顾客消息
    customer_msg = Message(session_id=session.id, role="customer", content=body.content)
    db.add(customer_msg)

    # 3. 跑状态机（真实调用 LLM，要等几秒）
    result = supervisor.invoke({"question": body.content, "history": history, "steps": []})

    # 4. 存 AI 回复
    agent_msg = Message(
        session_id=session.id,
        role="agent",
        content=result["answer"],
        agent_source="knowledge" if result["intent"] == "faq" else None,
    )
    db.add(agent_msg)

    # 5. 更新会话：最后消息时间 + 步数累计（预算机制的雏形）
    session.last_message_at = datetime.now(timezone.utc)
    session.steps_used = session.steps_used + len(result["steps"])

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

# ---------- SSE 流式接口（W1 版） ----------

REFUSAL_TEXT = "抱歉，这个问题我需要转人工处理。"


def sse_event(event: str, data: dict) -> str:
    """把一条数据编码成 SSE 协议的一帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/messages/stream")
def stream_message(session_id: uuid.UUID, body: SendMessageRequest, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    def generate():
        agent_id = uuid.uuid4()  # 提前生成：turn_start 和 message_delta 都要引用它

        # 1. 顾客消息入库（和机器回答最后一起 commit）
        customer_msg = Message(session_id=session_id, role="customer",
                               content=body.content, content_type="text", status="sent")
        db.add(customer_msg)
        yield sse_event("turn_start", {"message_id": str(agent_id)})

        # 2. triage：关键词检索（与图的 triage 节点同一套逻辑）
        chunks = kb.retrieve(body.content)

        if chunks:
            yield sse_event("agent_status", {"agent": "knowledge", "status": "working"})
            pieces = []
            for token in llm.chat_stream(knowledge_agent.build_messages(body.content, chunks)):
                pieces.append(token)
                yield sse_event("message_delta", {"message_id": str(agent_id), "delta": token})
            answer = "".join(pieces)
            yield sse_event("agent_status", {"agent": "knowledge", "status": "done"})
            steps = ["triage", "knowledge", "respond"]
        else:
            answer = REFUSAL_TEXT
            yield sse_event("message_delta", {"message_id": str(agent_id), "delta": answer})
            steps = ["triage", "respond"]

        # 3. 收尾落库：机器回答 + 会话统计（口径与同步接口一致）
        agent_msg = Message(id=agent_id, session_id=session_id, role="agent",
                            content=answer, content_type="text", status="sent",
                            agent_source="knowledge" if chunks else None)
        db.add(agent_msg)
        session.last_message_at = datetime.now(timezone.utc)
        session.steps_used = session.steps_used + len(steps)
        db.commit()
        db.refresh(agent_msg)

        yield sse_event("message_completed",
                        {"message": MessageOut.model_validate(agent_msg).model_dump(mode="json")})
        yield sse_event("turn_end", {"message_id": str(agent_id), "steps": steps})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})