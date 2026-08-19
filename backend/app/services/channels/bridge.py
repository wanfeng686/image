"""渠道消息桥：平台入站消息 → 现有 AI 引擎 → 回复文本发回。

职责：
1. 按 (tenant, external_ref=平台:会话ID) 找/建 ChatSession（同一买家对话固定落同一会话）
2. 买家身份按 平台:买家ID 绑定 User（跨平台/跨租户永不串号）
3. 复用 /api/chat 的 _process_turn 内核（升级前置闸 → 状态机 → 落库）
4. agent 消息（含卡片）降级为纯文本，适配平台聊天窗只能发文本的现实
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.chat import _process_turn
from app.models import ChannelConnection, ChatSession, Message, Tenant, User
from app.services.channels.base import InboundMessage, OutboundReply

STATUS_CN = {"paid": "已支付", "shipped": "已发货", "delivered": "已签收",
             "refunding": "退款中", "refunded": "已退款",
             "auto_approved": "已自动退款", "pending_approval": "等待人工审批"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clip(s: str, n: int = 64) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 8] + "_" + s[-7:]


def _ext_user_id(m: InboundMessage) -> str:
    return _clip(f"{m.platform}:{m.buyer_id}")


def _ext_ref(m: InboundMessage) -> str:
    return _clip(f"{m.platform}:{m.conversation_ref}")


def _user_for(db: Session, tenant: Tenant, m: InboundMessage) -> User:
    ext = _ext_user_id(m)
    row = db.scalar(select(User).where(User.tenant_id == tenant.id, User.external_id == ext))
    if row is None:
        row = User(tenant_id=tenant.id, external_id=ext,
                   nickname=(m.buyer_name or f"{m.platform}买家{m.buyer_id[:8]}")[:64])
        db.add(row)
        db.flush()
    return row


def _session_for(db: Session, tenant: Tenant, m: InboundMessage, user: User) -> ChatSession:
    ref = _ext_ref(m)
    row = db.scalar(select(ChatSession).where(
        ChatSession.tenant_id == tenant.id, ChatSession.external_ref == ref))
    if row is None:
        row = ChatSession(tenant_id=tenant.id, user_id=user.id,
                          channel=m.platform[:16], external_ref=ref, config_snapshot={})
        db.add(row)
        db.flush()
    return row


def format_agent_message(msg: Message) -> str:
    """agent 消息 → 渠道纯文本（卡片字段降级为文字行）。"""
    text = (msg.content or "").strip()
    card = msg.card_data or {}
    lines = []
    if card.get("type") == "order":
        lines.append("📦 订单详情")
        if card.get("order_no"):
            lines.append(f"订单号：{card['order_no']}")
        if card.get("product"):
            lines.append(f"商品：{card['product']}")
        if card.get("amount") is not None:
            lines.append(f"金额：¥{float(card['amount']):.2f}")
        if card.get("status"):
            lines.append(f"状态：{STATUS_CN.get(card['status'], card['status'])}")
        if card.get("eta"):
            lines.append(f"预计送达：{card['eta']}")
        if card.get("tracking_no"):
            lines.append(f"物流：{card.get('carrier', '')} {card['tracking_no']}")
    elif card.get("type") == "refund":
        lines.append("💳 退款进度")
        if card.get("order_no"):
            lines.append(f"订单：{card['order_no']}")
        if card.get("amount") is not None:
            lines.append(f"金额：¥{float(card['amount']):.2f}")
        if card.get("status"):
            lines.append(f"进度：{STATUS_CN.get(card['status'], card['status'])}")
    if text and lines:
        return text + "\n\n" + "\n".join(lines)
    return text or ("\n".join(lines) if lines else "")


def process_channel_message(db: Session, conn: ChannelConnection,
                            m: InboundMessage) -> OutboundReply:
    """一条入站渠道消息的完整处理。调用方负责把返回的回复经适配器发回平台。"""
    tenant = db.get(Tenant, conn.tenant_id)
    if tenant is None:
        raise RuntimeError("渠道连接的租户不存在")
    user = _user_for(db, tenant, m)
    session = _session_for(db, tenant, m, user)

    messages = _process_turn(db, session, m.text)
    agent_msg = next((x for x in messages if x.role == "agent"), None)
    reply_text = format_agent_message(agent_msg) if agent_msg is not None else ""

    conn.last_sync_at = _now()
    db.commit()
    return OutboundReply(conversation_ref=m.conversation_ref, text=reply_text,
                         card=agent_msg.card_data if agent_msg is not None else None,
                         session_id=str(session.id))
