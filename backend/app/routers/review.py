"""预测复盘路由：预测发布轮、实测确认、日报签发与复盘视图查询。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.database import db
from app.services import service_for

router = APIRouter(prefix="/api/review", tags=["预测复盘"])


class ReleasePayload(BaseModel):
    target_metric: str
    business_date: str
    lower_bound: float
    upper_bound: float
    predicted_value: float | None = None
    confidence: float | None = None
    released_at: str | None = None
    task_id: int | None = None
    note: str | None = None


class ActualPayload(BaseModel):
    target_metric: str
    business_date: str
    actual_value: float
    confirmed_at: str | None = None
    confirmed_by: str | None = None
    note: str | None = None


class IssuePayload(BaseModel):
    report_id: int
    business_date: str
    target_metric: str | None = None
    issued_at: str | None = None
    accuracy_target: float | None = None
    remark: str | None = None


def _forecast_service():
    return service_for("forecast_model")


def _report_service():
    return service_for("data_report")


@router.post("/forecast-releases")
def publish_forecast_release(payload: ReleasePayload) -> dict[str, Any]:
    """发布一轮预测区间；同一业务日可多次发布，轮次自动累加。"""
    return _forecast_service().publish_release(payload.model_dump(exclude_none=True))


@router.get("/forecast-releases")
def list_forecast_releases(
    business_date: str | None = Query(default=None),
    target_metric: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """按业务日回查所有发布轮及其区间、发布时间。"""
    try:
        rows = _forecast_service().list_releases(
            target_metric=target_metric, business_date=business_date, limit=limit)
    except ValueError as exc:
        return {"ok": False, "message": str(exc), "items": []}
    return {"ok": True, "items": rows, "total": len(rows)}


@router.post("/forecast-actuals")
def confirm_forecast_actual(payload: ActualPayload) -> dict[str, Any]:
    """确认业务日实测值；重复确认会追加新版本而不是覆盖旧版本。"""
    return _forecast_service().confirm_actual(payload.model_dump(exclude_none=True))


@router.get("/forecast-actuals")
def list_forecast_actuals(
    business_date: str | None = Query(default=None),
    target_metric: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    """按业务日回查实测版本。"""
    try:
        rows = _forecast_service().list_actuals(
            target_metric=target_metric, business_date=business_date, limit=limit)
    except ValueError as exc:
        return {"ok": False, "message": str(exc), "items": []}
    return {"ok": True, "items": rows, "total": len(rows)}


@router.get("/daily")
def daily_review(
    business_date: str = Query(...),
    target_metric: str | None = Query(default=None),
    as_of: str | None = Query(default=None),
) -> dict[str, Any]:
    """复盘视图：按业务日关联实测与各发布轮，标出命中轮和计分轮。

    `as_of` 传入某个签发时间即可回看当时的口径（只取该时刻前发布的轮次）。
    """
    return _report_service().review_view(
        business_date, target_metric=target_metric, as_of=as_of)


@router.post("/issues")
def issue_daily_report(payload: IssuePayload) -> dict[str, Any]:
    """签发日报，冻结当次计分口径与实际使用的数据。"""
    return _report_service().issue_daily_report(payload.model_dump(exclude_none=True))


@router.get("/issues")
def list_report_issues(
    report_id: int | None = Query(default=None),
    business_date: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict[str, Any]:
    """列出发过的日报版本。"""
    return _report_service().list_issues(
        report_id=report_id, business_date=business_date, limit=limit)


@router.get("/issues/{issue_id}")
def get_report_issue(issue_id: int) -> dict[str, Any]:
    """打开某次签发时冻结的日报内容（含计分实际值）。"""
    issue = _report_service().get_issue(issue_id)
    if issue is None:
        return {"ok": False, "message": f"签发记录 {issue_id} 不存在"}
    return {"ok": True, "issue": issue}


@router.get("/options")
def review_options() -> dict[str, Any]:
    """复盘页下拉选项：报告与预测指标。"""
    reports = db.fetchall("SELECT id, report_name, status FROM reports ORDER BY id")
    metrics = db.fetchall("SELECT DISTINCT target_metric FROM forecast_tasks ORDER BY target_metric")
    return {
        "reports": reports,
        "target_metrics": [m["target_metric"] for m in metrics],
    }
