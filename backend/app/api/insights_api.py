"""洞察日报 API（P6 核心）：查看 / 重生成 / 建议应用。"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_operator
from app.core.db import get_db
from app.models import InsightFinding, InsightReport
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


@router.get("")
def get_insight(day: str | None = None, db: Session = Depends(get_db)):
    target = date.fromisoformat(day) if day else date.today()
    report = db.scalar(select(InsightReport).where(InsightReport.report_date == target))
    if report is None:
        return {"report_date": str(target), "status": "not_generated",
                "summary": None, "metrics": None, "findings": []}
    return _report_dict(db, report)


@router.post("/regenerate")
def regenerate(day: str | None = None, db: Session = Depends(get_db)):
    target = date.fromisoformat(day) if day else date.today()
    report = insight_svc.generate_report(db, target)
    return _report_dict(db, report)


@router.post("/findings/{finding_id}/apply")
def apply_finding(finding_id: uuid.UUID, db: Session = Depends(get_db)):
    f = db.get(InsightFinding, finding_id)
    if f is None:
        raise HTTPException(404, "finding not found")
    f.status = "applied"
    f.applied_action = {"type": "acknowledged", "at": str(date.today())}
    db.commit()
    return {"id": str(f.id), "status": f.status}


@router.post("/findings/{finding_id}/ignore")
def ignore_finding(finding_id: uuid.UUID, db: Session = Depends(get_db)):
    f = db.get(InsightFinding, finding_id)
    if f is None:
        raise HTTPException(404, "finding not found")
    f.status = "ignored"
    db.commit()
    return {"id": str(f.id), "status": f.status}
