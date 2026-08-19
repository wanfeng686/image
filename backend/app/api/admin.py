"""管理 API：Eval 黄金集跑分 + 演示数据重置（admin 角色专属）。"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_operator
from app.core.db import get_db, SessionLocal
from app.graph.supervisor import supervisor
from app.models import (
    AgentRun, ChatSession, EvalCase, EvalRun, ExecutedAction, Message, Operator, User,
)
from app.services import escalation as escalation_svc
from app.services.demo import reset_demo
from app.models import Tenant

router = APIRouter(prefix="/api/admin", tags=["admin"])

DEMO_WIDGET_KEY = "pk_demo000000000000"   # 与迁移/seed 共用的演示租户标识


def _demo_tenant(db: Session) -> Tenant:
    t = db.scalar(select(Tenant).where(Tenant.widget_key == DEMO_WIDGET_KEY))
    if t is None:
        raise HTTPException(500, "演示租户未初始化，请先跑 scripts/seed.py")
    return t


def _require_admin(op: Operator = Depends(get_current_operator)) -> Operator:
    if op.role != "admin":
        raise HTTPException(403, "仅管理员可用")
    return op


class EvalRunRequest(BaseModel):
    preset: str | None = "balanced"


def _run_case(db: Session, case: EvalCase) -> EvalRun:
    """单用例：全新会话逐条消息跑全链路（升级前置 + 状态机），按期望打分。
    Eval 固定跑在演示商城租户上（黄金集引用其订单/知识库）。"""
    tenant = _demo_tenant(db)
    script = case.user_script
    user = db.scalar(select(User).where(
        User.tenant_id == tenant.id,
        User.external_id == script.get("user_external_id", "eval")))
    if user is None:
        user = User(tenant_id=tenant.id,
                    external_id=script.get("user_external_id", "eval"), nickname="Eval用户")
        db.add(user)
        db.flush()
    session = ChatSession(tenant_id=tenant.id, user_id=user.id, config_snapshot={})
    db.add(session)
    db.flush()

    answers, intents = [], []
    for text in script.get("messages", []):
        db.add(Message(session_id=session.id, role="customer", content=text))
        db.flush()
        hit, reason = escalation_svc.evaluate(db, session, user, text)
        if hit:
            session.status, session.escalated_reason = "escalated", reason
            answers.append(escalation_svc.ESCALATION_REPLY)
            continue
        result = supervisor.invoke({
            "question": text, "history": [], "steps": [],
            "intent": None, "chunks": [], "answer": None, "refused": False,
            "card": None, "order_no": None, "sentiment": None, "session_status": None,
            "qc_passed": True, "qc_feedback": None, "rewrite_count": 0,
            "db": db, "session_obj": session, "user_id": session.user_id, "message_id": None,
        })
        answers.append(result.get("answer"))
        intents.append(result.get("intent"))
    db.commit()

    # 断言评估
    exp = case.expectations or {}
    scores = {}
    if "expect_intent" in exp:
        scores["intent_correct"] = (exp["expect_intent"] in intents)
    if exp.get("must_refuse"):
        scores["refused_correct"] = any(
            a and ("转人工" in a) for a in answers)
    if exp.get("should_escalate"):
        scores["escalated_correct"] = session.status == "escalated"
    if exp.get("expect_not_found"):
        scores["not_found_correct"] = any(a and "没有找到" in a for a in answers)
    if exp.get("must_not_execute"):
        n = len(db.scalars(select(ExecutedAction)
                           .where(ExecutedAction.session_id == session.id)).all())
        scores["no_execution"] = (n == 0)
    scores["completed"] = True
    passed = all(bool(v) for v in scores.values())

    return EvalRun(case_id=case.id, preset=None, trajectory={"answers": answers, "intents": intents},
                   scores=scores, passed=passed)


@router.post("/eval/run")
def run_eval(body: EvalRunRequest | None = None, db: Session = Depends(get_db),
             _: Operator = Depends(_require_admin)):
    """跑全部启用的黄金集用例。"""
    cases = db.scalars(select(EvalCase).where(EvalCase.enabled)).all()
    results = []
    for case in cases:
        run = _run_case(db, case)
        db.add(run)
        db.commit()
        db.refresh(run)
        results.append({"case_id": case.id, "scenario": case.scenario, "name": case.name,
                        "passed": run.passed, "scores": run.scores})
    passed_n = sum(1 for r in results if r["passed"])
    return {"total": len(results), "passed": passed_n,
            "pass_rate": round(passed_n / len(results), 3) if results else None,
            "results": results}


@router.get("/eval/runs")
def list_eval_runs(db: Session = Depends(get_db), _: Operator = Depends(_require_admin)):
    runs = db.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(50)).all()
    case_names = {c.id: c.name for c in db.scalars(select(EvalCase)).all()}
    return {"items": [{"id": r.id, "case_id": r.case_id, "name": case_names.get(r.case_id),
                       "passed": r.passed, "scores": r.scores, "created_at": r.created_at}
                      for r in runs], "total": len(runs)}


@router.post("/demo/reset")
def demo_reset(_: Operator = Depends(_require_admin)):
    """重置演示数据（动态数据清空，静态种子保留）。"""
    return reset_demo()
