"""数据报告领域服务：管理周期性分析报告的模板配置和自动生成。

真实数据流：定义报告模板（包含指标集/周期/输出格式）→ pipeline.generate_report 读取最新指标值
→ 组装结构化报告内容 → 写入 report_outputs → 快照管理。

预测复盘与日报签发：
- 复盘视图按业务日关联预测发布轮与实测，标出每个预测区间是否命中、哪一条计入日报准确性。
- 签发日报时把当次使用的实测版本、所有发布轮和计分轮冻结进 report_issues.content，
  之后晚到实测或预测重发只影响新视图，旧签发视图仍按当时数据回查。
"""
from __future__ import annotations

import json
from typing import Any

from app.database import db
from app.pipeline import generate_report
from app.review import (
    DEFAULT_ACCURACY_TARGET,
    SCORING_CALIBER,
    SCORING_RULE_TEXT,
    normalize_business_date,
    normalize_metric_name,
    normalize_timestamp,
    now_iso,
    release_payload,
    release_order_key,
    select_scored_release,
    to_float,
)
from app.services.base import BaseModuleService


class DataReportService(BaseModuleService):
    MODULE = "data_report"
    ENTITY = "报告生成器"
    OPERATION_TERM = "生成"
    LIST_FIELDS = ["报告名称", "包含指标集", "报告周期", "输出格式", "自动发送"]
    REQUIRED_FIELDS = ["报告名称", "包含指标集", "报告周期"]
    STATUS_ORDER = ["草稿", "已发布", "已停用"]
    ACTION_RULES = {"发布报告": "已发布", "停用报告": "已停用"}
    NEGATIVE_ACTIONS = []

    def generate(self, report_id: int) -> dict[str, Any]:
        """生成一次数据报告。"""
        report = db.fetchone("SELECT * FROM reports WHERE id=?", [report_id])
        if report is None:
            return {"ok": False, "message": f"报告 {report_id} 不存在"}

        result = generate_report(dict(report))
        return {"ok": True, "report_name": result["report_name"], "summary": result["summary"]}

    def recent_outputs(self, report_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """获取报告的历史生成结果。"""
        rows = db.fetchall(
            "SELECT * FROM report_outputs WHERE report_id=? ORDER BY generated_at DESC LIMIT ?",
            [report_id, limit],
        )
        for r in rows:
            try:
                r["output_content"] = json.loads(r["output_content"]) if isinstance(
                    r["output_content"], str) else r["output_content"]
            except json.JSONDecodeError:
                pass
        return rows

    def compare_outputs(self, output_id_a: int, output_id_b: int) -> dict[str, Any]:
        """对比两份报告输出的差异。"""
        a = db.fetchone("SELECT * FROM report_outputs WHERE id=?", [output_id_a])
        b = db.fetchone("SELECT * FROM report_outputs WHERE id=?", [output_id_b])
        if not a or not b:
            return {"ok": False, "message": "报告输出不存在"}

        try:
            content_a = json.loads(a["output_content"]) if isinstance(a["output_content"], str) else a["output_content"]
            content_b = json.loads(b["output_content"]) if isinstance(b["output_content"], str) else b["output_content"]
        except json.JSONDecodeError:
            return {"ok": False, "message": "内容解析失败"}

        diffs = []
        sections_a = content_a.get("sections", [])
        sections_b = content_b.get("sections", [])

        for sa, sb in zip(sections_a, sections_b):
            val_a = sa.get("current_value", 0)
            val_b = sb.get("current_value", 0)
            if val_a and val_b and val_a != 0:
                pct = round((val_a - val_b) / abs(val_a) * 100, 2)
                if abs(pct) > 5:
                    diffs.append({
                        "metric": sa.get("metric_name"),
                        "value_a": val_a,
                        "value_b": val_b,
                        "diff_pct": pct,
                    })

        return {
            "ok": True,
            "output_a_time": a["generated_at"],
            "output_b_time": b["generated_at"],
            "significant_diffs": len(diffs),
            "diffs": diffs,
        }

    # ------------------------------------------------------------------
    # 预测复盘视图
    # ------------------------------------------------------------------

    def review_view(
        self,
        business_date: str,
        target_metric: str | None = None,
        as_of: str | None = None,
        include_issue: bool = True,
    ) -> dict[str, Any]:
        """按业务日生成预测复盘视图：发布轮、命中情况、计分轮与准确性结论。

        include_issue=False 时只给出实时视图，不关联任何签发记录。
        """
        try:
            day = normalize_business_date(business_date)
            cutoff = normalize_timestamp(as_of)
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

        releases = self._releases_for_day(day, target_metric)
        if cutoff is not None:
            releases = [r for r in releases if str(r["released_at"]) <= cutoff]
        # 一次复盘只针对一个预测指标，避免不同指标的区间混在一起算出两个"计分轮"。
        # 未指定指标时取最后一次发布所用的指标。
        if not target_metric and releases:
            target_metric = max(releases, key=release_order_key)["target_metric"]
        if target_metric:
            releases = [r for r in releases if r["target_metric"] == target_metric]
        actual = self._actual_for_day(day, target_metric)
        actual_value = actual["actual_value"] if actual else None

        scored = select_scored_release(releases)
        scored_id = scored["id"] if scored else None
        rows = [release_payload(r, actual_value, scored_id) for r in releases]
        scored_row = next((r for r in rows if r["scored"]), None)

        accuracy_value = None
        target_met = None
        if scored_row is not None and scored_row["hit"] is not None:
            accuracy_value = 1.0 if scored_row["hit"] else 0.0
            target_met = accuracy_value >= DEFAULT_ACCURACY_TARGET

        result: dict[str, Any] = {
            "ok": True,
            "business_date": day,
            "target_metric": target_metric or (rows[0]["target_metric"] if rows else ""),
            "caliber": SCORING_CALIBER,
            "caliber_rule": SCORING_RULE_TEXT,
            "accuracy_target": DEFAULT_ACCURACY_TARGET,
            "as_of": cutoff,
            "actual": self._actual_payload(actual),
            "actual_versions": self._actual_versions(day, target_metric),
            "release_count": len(rows),
            "releases": rows,
            "scored_release": scored_row,
            "scored_hit": scored_row["hit"] if scored_row else None,
            "unscored_releases": [r for r in rows if not r["scored"]],
            "accuracy_value": accuracy_value,
            "target_met": target_met,
        }
        if include_issue:
            result["latest_issue"] = self._latest_issue(day, target_metric)
        return result

    def issue_daily_report(self, values: dict[str, Any]) -> dict[str, Any]:
        """签发一份日报，并冻结当次的计分口径与所用数据。

        同一报告/业务日可以多次签发，每次生成一个独立版本；旧版本不会被后续重算覆盖。
        """
        try:
            business_date = normalize_business_date(values.get("business_date"))
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

        report_id = values.get("report_id")
        if report_id in (None, ""):
            return {"ok": False, "message": "签发日报必须指定报告"}
        try:
            report_id = int(report_id)
        except (TypeError, ValueError):
            return {"ok": False, "message": "报告编号无效"}
        report = db.fetchone("SELECT * FROM reports WHERE id=?", [report_id])
        if report is None:
            return {"ok": False, "message": f"报告 {report_id} 不存在"}

        target_metric = normalize_metric_name(values.get("target_metric"))
        try:
            issued_at = normalize_timestamp(values.get("issued_at"), default=now_iso()) or now_iso()
            target = values.get("accuracy_target")
            accuracy_target = DEFAULT_ACCURACY_TARGET if target in (None, "") else to_float(target, "准确性目标")
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

        releases = self._releases_for_day(business_date, target_metric)
        # 签发时只能看到签发截止时间之前发布的轮次
        releases = [r for r in releases if str(r["released_at"]) <= issued_at]
        if not releases:
            return {"ok": False, "message": f"业务日 {business_date} 在签发前没有已发布预测"}

        if not target_metric:
            target_metric = releases[-1]["target_metric"]
        releases = [r for r in releases if r["target_metric"] == target_metric]
        if not releases:
            return {"ok": False, "message": f"业务日 {business_date} 没有指标 {target_metric} 的已发布预测"}

        # 实测必须和计分指标是同一条业务日/指标，避免拿别的指标的实测来算命中
        actual = self._actual_for_day(business_date, target_metric)
        if actual is None:
            return {"ok": False, "message": f"业务日 {business_date} 尚未确认实测，不能签发日报"}

        scored = select_scored_release(releases)
        assert scored is not None
        actual_value = actual["actual_value"]
        rows = [release_payload(r, actual_value, scored["id"]) for r in releases]
        scored_row = next(r for r in rows if r["scored"])
        accuracy_value = 1.0 if scored_row["hit"] else 0.0
        target_met = accuracy_value >= accuracy_target

        content = {
            "report_id": report_id,
            "report_name": report["report_name"],
            "business_date": business_date,
            "target_metric": target_metric,
            "issued_at": issued_at,
            "caliber": SCORING_CALIBER,
            "caliber_rule": SCORING_RULE_TEXT,
            "accuracy_target": accuracy_target,
            # 打开签发内容即可看到计分实际使用的实测版本
            "actual": self._actual_payload(actual),
            "releases": rows,
            "scored_release": scored_row,
            "scored_release_id": scored_row["id"],
            "scored_actual_id": actual["id"],
            "scored_hit": scored_row["hit"],
            "unscored_releases": [r for r in rows if not r["scored"]],
            "release_count": len(rows),
            "accuracy_value": accuracy_value,
            "target_met": target_met,
            "conclusion": self._conclusion(accuracy_target, accuracy_value, scored_row, actual_value),
        }

        issue_id = db.insert("report_issues", {
            "report_id": report_id,
            "business_date": business_date,
            "target_metric": target_metric,
            "issued_at": issued_at,
            "accuracy_target": accuracy_target,
            "scored_release_id": scored_row["id"],
            "scored_actual_id": actual["id"],
            "hit": 1 if scored_row["hit"] else 0,
            "release_count": len(rows),
            "content": json.dumps(content, ensure_ascii=False),
        })
        return {
            "ok": True,
            "message": f"日报已签发（第 {db.count('report_issues', 'report_id=? AND business_date=?', [report_id, business_date])} 版）",
            "issue_id": issue_id,
            "issue": self.get_issue(issue_id),
        }

    def list_issues(self, report_id: int | None = None, business_date: str | None = None,
                    limit: int = 50) -> dict[str, Any]:
        """列出发过的日报版本（只给摘要，回查内容走 get_issue）。"""
        where = ["1=1"]
        params: list[Any] = []
        if report_id not in (None, ""):
            where.append("report_id=?")
            params.append(int(report_id))
        if business_date:
            try:
                where.append("business_date=?")
                params.append(normalize_business_date(business_date))
            except ValueError as exc:
                return {"ok": False, "message": str(exc)}
        params.append(limit)
        rows = db.fetchall(
            f"SELECT * FROM report_issues WHERE {' AND '.join(where)} "
            "ORDER BY business_date DESC, issued_at DESC, id DESC LIMIT ?",
            params,
        )
        items = []
        for row in rows:
            content = self._load_content(row)
            items.append({
                "issue_id": row["id"],
                "report_id": row["report_id"],
                "report_name": content.get("report_name", ""),
                "business_date": row["business_date"],
                "target_metric": row["target_metric"],
                "issued_at": row["issued_at"],
                "scored_release_id": row["scored_release_id"],
                "scored_release_round": (content.get("scored_release") or {}).get("release_round"),
                "scored_interval": self._interval_text(content.get("scored_release")),
                "actual_value": (content.get("actual") or {}).get("actual_value"),
                "scored_hit": bool(row["hit"]),
                "accuracy_value": content.get("accuracy_value"),
                "accuracy_target": row["accuracy_target"],
                "target_met": content.get("target_met"),
                "release_count": row["release_count"],
            })
        return {"ok": True, "items": items, "total": len(items)}

    def get_issue(self, issue_id: int) -> dict[str, Any] | None:
        """按签发编号打开当时冻结的日报内容（不受后续实测/重发影响）。"""
        row = db.fetchone("SELECT * FROM report_issues WHERE id=?", [issue_id])
        if row is None:
            return None
        content = self._load_content(row)
        return {
            "issue_id": row["id"],
            "report_id": row["report_id"],
            "business_date": row["business_date"],
            "target_metric": row["target_metric"],
            "issued_at": row["issued_at"],
            "frozen": True,
            "content": content,
        }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _interval_text(release: dict[str, Any] | None) -> str | None:
        if not release:
            return None
        return f"{release['lower_bound']} ~ {release['upper_bound']}"

    @staticmethod
    def _conclusion(target: float, accuracy: float, scored_row: dict[str, Any],
                    actual_value: float) -> str:
        verdict = "达到" if accuracy >= target else "未达到"
        hit_text = "命中" if scored_row["hit"] else "未命中（实测落在区间之外）"
        return (
            f"计分预测为第 {scored_row['release_round']} 轮"
            f"（{scored_row['lower_bound']} ~ {scored_row['upper_bound']}，"
            f"发布于 {scored_row['released_at']}），实测 {actual_value}，判定{hit_text}；"
            f"本期准确性 {accuracy:.0%}，{verdict}目标 {target:.0%}。"
        )

    def _releases_for_day(self, business_date: str, target_metric: str | None) -> list[dict[str, Any]]:
        where = ["business_date=?"]
        params: list[Any] = [business_date]
        if target_metric:
            where.append("target_metric=?")
            params.append(normalize_metric_name(target_metric))
        rows = db.fetchall(
            f"SELECT * FROM forecast_releases WHERE {' AND '.join(where)} "
            "ORDER BY released_at ASC, release_round ASC, id ASC",
            params,
        )
        return sorted(rows, key=release_order_key)

    def _actual_for_day(self, business_date: str, target_metric: str | None) -> dict[str, Any] | None:
        where = ["business_date=?"]
        params: list[Any] = [business_date]
        if target_metric:
            where.append("target_metric=?")
            params.append(normalize_metric_name(target_metric))
        return db.fetchone(
            f"SELECT * FROM forecast_actuals WHERE {' AND '.join(where)} "
            "ORDER BY confirmed_at DESC, id DESC LIMIT 1",
            params,
        )

    def _actual_versions(self, business_date: str, target_metric: str | None) -> list[dict[str, Any]]:
        where = ["business_date=?"]
        params: list[Any] = [business_date]
        if target_metric:
            where.append("target_metric=?")
            params.append(normalize_metric_name(target_metric))
        return db.fetchall(
            f"SELECT * FROM forecast_actuals WHERE {' AND '.join(where)} "
            "ORDER BY confirmed_at ASC, id ASC",
            params,
        )

    @staticmethod
    def _actual_payload(actual: dict[str, Any] | None) -> dict[str, Any] | None:
        if actual is None:
            return None
        return {
            "id": actual["id"],
            "actual_value": actual["actual_value"],
            "confirmed_at": actual["confirmed_at"],
            "confirmed_by": actual.get("confirmed_by") or "",
            "note": actual.get("note") or "",
        }

    def _latest_issue(self, business_date: str, target_metric: str | None) -> dict[str, Any] | None:
        if target_metric:
            row = db.fetchone(
                "SELECT id FROM report_issues WHERE business_date=? AND target_metric=? "
                "ORDER BY issued_at DESC, id DESC LIMIT 1",
                [business_date, target_metric],
            )
        else:
            row = db.fetchone(
                "SELECT id FROM report_issues WHERE business_date=? "
                "ORDER BY issued_at DESC, id DESC LIMIT 1",
                [business_date],
            )
        return self.get_issue(row["id"]) if row else None

    @staticmethod
    def _load_content(row: dict[str, Any]) -> dict[str, Any]:
        try:
            return json.loads(row["content"]) if isinstance(row["content"], str) else (row["content"] or {})
        except json.JSONDecodeError:
            return {}

    def domain_snapshot(self) -> dict[str, Any]:
        snapshot = super().domain_snapshot()
        snapshot["total_reports"] = db.count("reports")
        snapshot["total_outputs"] = db.count("report_outputs")
        snapshot["total_issues"] = db.count("report_issues")
        return snapshot
