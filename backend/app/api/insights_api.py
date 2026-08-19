"""洞察日报 API（P6 核心）：查看 / 重生成 / 建议应用。SaaS 化：租户隔离。"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_operator
from app.core.db import get_db
from app.models import InsightFinding, InsightReport, Operator
from app.services import insight as insight_svc

router = APIRouter(prefix="/api/console/insights", tags=["insights"],
                   dependencies=[Depends(get_current_operator)])


def _report_dict(db: Session, report: InsightReport) -> dict:
    findings = db.scalars(select(InsightFinding)
                          .where(InsightFinding.report_id == report.id)).all()
    return {
        "id": str(report.id), "report_date": str(report.report_date),
        "status": report.status, "summary": report.summary, "metrics": report.metrics,
        "findings": [{"id": str(f.id), "severity": f.severity, "title": f.title,
                      "detail": f.detail, "status": f.status} for f in findings],
        "created_at": report.created_at,
    }


def _get_scoped_report(db: Session, op: Operator, target: date) -> InsightReport | None:
    q = select(InsightReport).where(InsightReport.report_date == target)
    if op.tenant_id is not None:
        q = q.where(InsightReport.tenant_id == op.tenant_id)
    return db.scalar(q)


def _get_scoped_finding(db: Session, op: Operator, finding_id: uuid.UUID) -> InsightFinding:
    f = db.get(InsightFinding, finding_id)
    if f is None:
        raise HTTPException(404, "finding not found")
    if op.tenant_id is not None:
        report = db.get(InsightReport, f.report_id)
        if report is None or report.tenant_id != op.tenant_id:
            raise HTTPException(404, "finding not found")
    return f


@router.get("")
def get_insight(day: str | None = None, db: Session = Depends(get_db),
                op: Operator = Depends(get_current_operator)):
    target = date.fromisoformat(day) if day else date.today()
    report = _get_scoped_report(db, op, target)
    if report is None:
        return {"report_date": str(target), "status": "not_generated",
                "summary": None, "metrics": None, "findings": []}
    return _report_dict(db, report)


@router.post("/regenerate")
def regenerate(day: str | None = None, db: Session = Depends(get_db),
               op: Operator = Depends(get_current_operator)):
    if op.tenant_id is None:
        raise HTTPException(403, "平台账号无租户上下文，请用商户账号生成日报")
    target = date.fromisoformat(day) if day else date.today()
    report = insight_svc.generate_report(db, target, op.tenant_id)
    return _report_dict(db, report)


@router.post("/findings/{finding_id}/apply")
def apply_finding(finding_id: uuid.UUID, db: Session = Depends(get_db),
                  op: Operator = Depends(get_current_operator)):
    f = _get_scoped_finding(db, op, finding_id)
    f.status = "applied"
    f.applied_action = {"type": "acknowledged", "at": str(date.today())}
    db.commit()
    return {"id": str(f.id), "status": f.status}


@router.post("/findings/{finding_id}/ignore")
def ignore_finding(finding_id: uuid.UUID, db: Session = Depends(get_db),
                   op: Operator = Depends(get_current_operator)):
    f = _get_scoped_finding(db, op, finding_id)
    f.status = "ignored"
    db.commit()
    return {"id": str(f.id), "status": f.status}
