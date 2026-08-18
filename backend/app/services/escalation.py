"""升级规则引擎（M7）：硬规则前置，LLM 只兜模糊带（DESIGN §4.3）。

硬规则来自 escalation_rules 表（运营台可改）：keyword / condition 两类。
用户点"转人工"按钮由 /escalate 接口直转，不经过本引擎（最硬的硬规则）。
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EscalationRule, User


def _repeat_tracking(session, question: str) -> tuple[bool, str | None]:
    """同一问题连问 3 次 → 升级。槽位里记 last_question + repeat_count。"""
    slots = dict(session.slots or {})
    last = slots.get("last_question")
    count = slots.get("repeat_count", 0)
    if question and question.strip() == last:
        count += 1
    else:
        count = 1
    slots["last_question"] = question
    slots["repeat_count"] = count
    session.slots = slots
    max_repeat = 3
    return (count >= max_repeat), ("repeat" if count >= max_repeat else None)


def evaluate(db: Session, session, user: User, question: str) -> tuple[bool, str | None]:
    """返回 (是否升级, 原因)。规则按 priority 升序评估，命中即返回。"""
    rules = db.scalars(
        select(EscalationRule).where(EscalationRule.enabled).order_by(EscalationRule.priority)
    ).all()

    # 追问计数独立于表规则（条件型规则可读它的配置，这里统一实现）
    repeated, repeat_reason = _repeat_tracking(session, question)

    for r in rules:
        cfg = r.config or {}
        if r.rule_type == "keyword":
            kws = [k for k in cfg.get("keywords", []) if isinstance(k, str)]
            if any(k in (question or "") for k in kws):
                return True, "keyword"
        elif r.rule_type == "condition":
            if "user_tier" in cfg and user and user.user_tier == cfg["user_tier"]:
                return True, "vip"
            if "sentiment_below" in cfg and session.sentiment is not None \
                    and float(session.sentiment) < float(cfg["sentiment_below"]):
                return True, "sentiment"
            if "max_repeat" in cfg and repeated:
                return True, repeat_reason or "repeat"

    if repeated:  # 表里没配 repeat 规则时也兜底
        return True, repeat_reason
    return False, None


ESCALATION_REPLY = "检测到您的诉求需要人工介入，已为您转接人工客服，请稍候。"
