"""预测模型领域服务：基于历史指标数据执行趋势和时间序列预测。

真实数据流：定义预测任务（指标/周期/方法/基线天数）
→ pipeline.compute_forecast 执行 SES/移动平均/线性趋势预测
→ 写入 forecast_results → 下游报告和告警消费者。

发布轮与实测：
- 预测任务的计算结果不是计分对象，真正参与日报计分的是"发布轮"（forecast_releases），
  每一轮都有轮次、发布时间和可回查的预测区间，同一业务日可以发布多轮。
- 业务日结束后的实测以版本追加的方式写入 forecast_actuals，晚到实测不会覆盖旧版本。
"""
from __future__ import annotations

from typing import Any

from app.database import db
from app.pipeline import compute_forecast
from app.review import (
    normalize_business_date,
    normalize_metric_name,
    normalize_timestamp,
    now_iso,
    release_payload,
    to_float,
)
from app.services.base import BaseModuleService


class ForecastModelService(BaseModuleService):
    MODULE = "forecast_model"
    ENTITY = "预测任务"
    OPERATION_TERM = "预测"
    LIST_FIELDS = ["任务名称", "预测指标", "预测周期", "预测方式", "历史基线天数"]
    REQUIRED_FIELDS = ["任务名称", "预测指标", "预测周期"]
    STATUS_ORDER = ["待执行", "执行中", "已完成", "执行失败"]
    ACTION_RULES = {"启动预测": "已完成", "取消预测": "执行失败"}
    NEGATIVE_ACTIONS = []

    def run_forecast(self, task_id: int) -> dict[str, Any]:
        """执行预测任务。"""
        task = db.fetchone("SELECT * FROM forecast_tasks WHERE id=?", [task_id])
        if task is None:
            return {"ok": False, "message": f"预测任务 {task_id} 不存在"}

        db.update("forecast_tasks", {"status": "执行中"}, "id=?", [task_id])
        results = compute_forecast(dict(task))
        db.update("forecast_tasks", {"status": "已完成"}, "id=?", [task_id])

        return {
            "ok": True,
            "task_name": task["task_name"],
            "method": task["forecast_method"],
            "forecasts": results,
        }

    def forecast_data(self, task_id: int) -> list[dict[str, Any]]:
        """获取预测结果。"""
        return db.fetchall(
            "SELECT * FROM forecast_results WHERE task_id=? ORDER BY forecast_date ASC",
            [task_id],
        )

    # ------------------------------------------------------------------
    # 发布轮：可回查的预测区间
    # ------------------------------------------------------------------

    def publish_release(self, values: dict[str, Any]) -> dict[str, Any]:
        """登记一轮预测发布。

        同一业务日可以发布多轮，轮次在 (预测指标, 业务日) 内自增；
        released_at 既是发布时间也是后续"哪个计分"的唯一依据。
        """
        try:
            target_metric = normalize_metric_name(values.get("target_metric"))
            if not target_metric:
                raise ValueError("预测指标不能为空")
            business_date = normalize_business_date(values.get("business_date"))
            lower = to_float(values.get("lower_bound"), "区间下限")
            upper = to_float(values.get("upper_bound"), "区间上限")
            if lower > upper:
                raise ValueError("区间下限不能大于上限")
            predicted = values.get("predicted_value")
            predicted = (lower + upper) / 2 if predicted in (None, "") else to_float(predicted, "预测值")
            confidence = values.get("confidence")
            confidence = 0.95 if confidence in (None, "") else to_float(confidence, "置信度")
            released_at = normalize_timestamp(values.get("released_at"), default=now_iso())
            if released_at is None:
                released_at = now_iso()
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

        task_id = values.get("task_id")
        if task_id not in (None, ""):
            task = db.fetchone("SELECT * FROM forecast_tasks WHERE id=?", [task_id])
            if task is None:
                return {"ok": False, "message": f"预测任务 {task_id} 不存在"}
            task_id = int(task["id"])
        else:
            task_id = None

        existing = db.fetchone(
            "SELECT COALESCE(MAX(release_round), 0) AS r FROM forecast_releases "
            "WHERE target_metric=? AND business_date=?",
            [target_metric, business_date],
        )
        release_round = int(existing["r"]) + 1 if existing else 1

        release_id = db.insert("forecast_releases", {
            "task_id": task_id,
            "target_metric": target_metric,
            "business_date": business_date,
            "release_round": release_round,
            "released_at": released_at,
            "predicted_value": round(predicted, 4),
            "lower_bound": round(lower, 4),
            "upper_bound": round(upper, 4),
            "confidence": confidence,
            "note": str(values.get("note") or ""),
        })
        release = db.fetchone("SELECT * FROM forecast_releases WHERE id=?", [release_id])
        latest_actual = self.latest_actual(target_metric, business_date)
        return {
            "ok": True,
            "message": f"已发布第 {release_round} 轮预测",
            "release": release_payload(release, latest_actual["actual_value"] if latest_actual else None),
        }

    def list_releases(
        self,
        target_metric: str | None = None,
        business_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """按业务日回查所有发布轮（含发布时间与区间）。"""
        where = ["1=1"]
        params: list[Any] = []
        if target_metric:
            where.append("target_metric=?")
            params.append(normalize_metric_name(target_metric))
        if business_date:
            where.append("business_date=?")
            params.append(normalize_business_date(business_date))
        params.append(limit)
        rows = db.fetchall(
            f"SELECT * FROM forecast_releases WHERE {' AND '.join(where)} "
            "ORDER BY business_date DESC, target_metric, released_at ASC, release_round ASC LIMIT ?",
            params,
        )
        return rows

    # ------------------------------------------------------------------
    # 实测确认：版本追加
    # ------------------------------------------------------------------

    def confirm_actual(self, values: dict[str, Any]) -> dict[str, Any]:
        """确认某个业务日的实测值，追加一个实测版本。"""
        try:
            target_metric = normalize_metric_name(values.get("target_metric"))
            if not target_metric:
                raise ValueError("预测指标不能为空")
            business_date = normalize_business_date(values.get("business_date"))
            actual_value = to_float(values.get("actual_value"), "实测值")
            confirmed_at = normalize_timestamp(values.get("confirmed_at"), default=now_iso())
            if confirmed_at is None:
                confirmed_at = now_iso()
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

        actual_id = db.insert("forecast_actuals", {
            "target_metric": target_metric,
            "business_date": business_date,
            "actual_value": round(actual_value, 4),
            "confirmed_at": confirmed_at,
            "confirmed_by": str(values.get("confirmed_by") or ""),
            "note": str(values.get("note") or ""),
        })
        actual = db.fetchone("SELECT * FROM forecast_actuals WHERE id=?", [actual_id])
        version = db.count(
            "forecast_actuals", "target_metric=? AND business_date=?",
            [target_metric, business_date],
        )
        return {
            "ok": True,
            "message": f"已确认实测 {actual_value}（第 {version} 个实测版本）",
            "actual": actual,
            "version": version,
        }

    def list_actuals(
        self,
        target_metric: str | None = None,
        business_date: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """按业务日回查所有实测版本。"""
        where = ["1=1"]
        params: list[Any] = []
        if target_metric:
            where.append("target_metric=?")
            params.append(normalize_metric_name(target_metric))
        if business_date:
            where.append("business_date=?")
            params.append(normalize_business_date(business_date))
        params.append(limit)
        return db.fetchall(
            f"SELECT * FROM forecast_actuals WHERE {' AND '.join(where)} "
            "ORDER BY business_date DESC, target_metric, confirmed_at ASC, id ASC LIMIT ?",
            params,
        )

    def latest_actual(self, target_metric: str, business_date: str) -> dict[str, Any] | None:
        return db.fetchone(
            "SELECT * FROM forecast_actuals WHERE target_metric=? AND business_date=? "
            "ORDER BY confirmed_at DESC, id DESC LIMIT 1",
            [target_metric, business_date],
        )

    def evaluate_accuracy(self, task_id: int) -> dict[str, Any]:
        """评估预测准确率：对比预测值与实际值。"""
        task = db.fetchone("SELECT * FROM forecast_tasks WHERE id=?", [task_id])
        if task is None:
            return {"ok": False, "message": "任务不存在"}

        forecasts = db.fetchall(
            "SELECT * FROM forecast_results WHERE task_id=? ORDER BY forecast_date ASC LIMIT 7",
            [task_id],
        )

        metric = db.fetchone(
            "SELECT id FROM metrics WHERE metric_name LIKE ?",
            [f"%{task['target_metric']}%"],
        )
        if not metric:
            return {"ok": False, "message": "关联指标不存在"}

        actuals = db.fetchall(
            "SELECT snapshot_value, snapshot_time FROM metric_values WHERE metric_id=? ORDER BY snapshot_time DESC LIMIT 7",
            [metric["id"]],
        )

        errors = []
        for f, a in zip(forecasts, reversed(actuals)):
            err = abs(f["predicted_value"] - a["snapshot_value"]) / max(abs(a["snapshot_value"]), 0.0001)
            errors.append(err)

        mape = sum(errors) / max(len(errors), 1) * 100

        return {
            "ok": True,
            "task_name": task["task_name"],
            "mape_pct": round(mape, 2),
            "accuracy_rating": "good" if mape < 10 else ("acceptable" if mape < 20 else "poor"),
            "comparisons": len(errors),
        }

    def domain_snapshot(self) -> dict[str, Any]:
        snapshot = super().domain_snapshot()
        snapshot["total_tasks"] = db.count("forecast_tasks")
        snapshot["total_forecasts"] = db.count("forecast_results")
        snapshot["total_releases"] = db.count("forecast_releases")
        snapshot["total_actuals"] = db.count("forecast_actuals")
        return snapshot
