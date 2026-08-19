"""洞察服务：统计快照 + LLM 生成发现（日报 = 仪表盘的报告版，DESIGN §9.4）。
SaaS 化：租户隔离，每商户自己的日报。"""
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentRun, ChatSession, InsightFinding, InsightReport, Message
from app.services import llm

SUMMARY_PROMPT = """你是客服运营分析师。根据下面的当日统计，输出 JSON（不要其他文字）：
{"summary": "三句话以内的日报摘要",
 "findings": [{"severity": "warning", "title": "...", "detail": "..."}]}

发现必须基于统计里的真实数字，最多 3 条，没有值得报告的就给空数组。
统计：{stats}"""


def collect_stats(db: Session, day: date, tenant_id: uuid.UUID) -> dict:
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    scope = ChatSession.tenant_id == tenant_id

    sessions = db.scalar(select(func.count()).select_from(ChatSession)
                         .where(scope, ChatSession.created_at >= day_start, ChatSession.created_at < day_end))
    escalated = db.scalar(select(func.count()).select_from(ChatSession)
                          .where(scope, ChatSession.created_at >= day_start, ChatSession.created_at < day_end,
                                 ChatSession.status == "escalated"))
    # 拒答统计 + 拒答问题聚合（缺口管道的原料）：messages 经 session 关联到租户
    refusal_rows = db.execute(
        select(Message.session_id, func.count())
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(scope,
               Message.role == "agent", Message.content == "抱歉，这个问题我需要转人工处理。",
               Message.created_at >= day_start, Message.created_at < day_end)
        .group_by(Message.session_id)).all()
    refusals = sum(n for _, n in refusal_rows)

    top_intents = {}
    for li in db.scalars(select(ChatSession.last_intent)
                         .where(scope,
                                ChatSession.created_at >= day_start,
                                ChatSession.created_at < day_end,
                                ChatSession.last_intent.isnot(None))).all():
        first = ((li or {}).get("intents") or ["unknown"])[0]
        top_intents[first] = top_intents.get(first, 0) + 1

    # agent_runs 经 session 关联到租户
    llm_calls = db.scalar(
        select(func.count()).select_from(AgentRun)
        .join(ChatSession, AgentRun.session_id == ChatSession.id)
        .where(scope,
               AgentRun.created_at >= day_start,
               AgentRun.created_at < day_end,
               AgentRun.provider_name.isnot(None)))
    return {"date": str(day), "sessions": sessions, "escalated": escalated,
            "refusals": refusals, "llm_calls": llm_calls, "intent_dist": top_intents}


def generate_report(db: Session, day: date, tenant_id: uuid.UUID) -> InsightReport:
    """生成（或重生成）某租户某日日报：确定性统计 + LLM 摘要与发现。"""
    report = db.scalar(select(InsightReport).where(
        InsightReport.tenant_id == tenant_id, InsightReport.report_date == day))
    if report is None:
        report = InsightReport(tenant_id=tenant_id, report_date=day, status="generating")
        db.add(report)
        db.flush()
    else:
        db.execute(InsightFinding.__table__.delete().where(InsightFinding.report_id == report.id))
    report.status = "generating"

    stats = collect_stats(db, day, tenant_id)
    report.metrics = stats
    try:
        raw = llm.chat([{"role": "user", "content": SUMMARY_PROMPT.format(
            stats=json.dumps(stats, ensure_ascii=False))}], agent="insight", tenant_id=tenant_id)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        report.summary = (data.get("summary") or "今日无异常。")[:1000]
        for f in (data.get("findings") or [])[:3]:
            db.add(InsightFinding(
                report_id=report.id,
                severity=f.get("severity") if f.get("severity") in ("info", "warning", "critical") else "info",
                title=(f.get("title") or "")[:128],
                detail=(f.get("detail") or "")[:2000],
                evidence={"stats": stats},
            ))
        report.model_used = "llm"
    except Exception as exc:  # noqa: BLE001 —— LLM 挂了也要有日报骨架
        report.summary = f"统计快照已生成（LLM 摘要失败：{str(exc)[:100]}）"
    report.status = "generated"
    db.commit()
    db.refresh(report)
    return report
