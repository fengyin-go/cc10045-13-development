"""预测复盘公共规则：业务日、发布轮、实测版本与"每日只计一条预测"的计分口径。

这些规则同时被预测模型服务（发布预测轮/确认实测）和数据报告服务（签发日报/复盘）
使用，集中在这里避免两边各写一套判断，出现同一份报告两个口径的情况。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

# 一份报告只能有一个计分口径：取签发截止时间之前最新发布的一轮预测。
SCORING_CALIBER = "最新发布轮"
SCORING_RULE_TEXT = (
    "同一业务日只计入一条已发布预测：在签发截止时间之前发布的轮次中，"
    "取发布时间最新的一轮作为计分区间，其余轮次保留为未计分版本。"
)

DEFAULT_ACCURACY_TARGET = 1.0


def now_iso() -> str:
    """带毫秒的 UTC 时间戳，保证同一秒内两次发布会话也能区分先后。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def normalize_timestamp(value: Any, *, default: str | None = None) -> str | None:
    """把日期时间输入统一成可比较的 `YYYY-MM-DDTHH:MM:SS.sss`。

    支持 `YYYY-MM-DD`、`YYYY-MM-DD HH:MM`、`YYYY-MM-DDTHH:MM:SS`、带 Z/时区的 ISO 串。
    空值返回 default。
    """
    if value is None or not str(value).strip():
        return default
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1]
    if len(text) == 10:
        text += "T00:00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"时间格式无法识别：{value}") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def normalize_business_date(value: Any) -> str:
    """业务日统一为 `YYYY-MM-DD`。"""
    text = str(value or "").strip()
    if not text:
        raise ValueError("业务日不能为空")
    text = text[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"业务日格式应为 YYYY-MM-DD：{value}") from exc
    return text


def normalize_metric_name(value: Any) -> str:
    return str(value or "").strip()


def to_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}必须是数字") from exc


def interval_hit(actual_value: float, lower_bound: float, upper_bound: float) -> bool:
    """命中判定：实测值落在闭区间 [下限, 上限] 内。"""
    return float(lower_bound) <= float(actual_value) <= float(upper_bound)


def release_order_key(release: dict[str, Any]) -> tuple[str, int, int]:
    """发布先后顺序：发布时间 → 发布轮 → 记录 id。"""
    return (
        str(release.get("released_at") or ""),
        int(release.get("release_round") or 0),
        int(release.get("id") or 0),
    )


def select_scored_release(releases: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """按唯一计分口径选出计分轮。调用方应先按签发截止时间过滤。"""
    candidates = list(releases)
    if not candidates:
        return None
    return max(candidates, key=release_order_key)


def release_payload(release: dict[str, Any], actual_value: float | None,
                    scored_release_id: int | None = None) -> dict[str, Any]:
    """把一条发布轮转成复盘视图需要的结构，附带当前实测下的命中结果。"""
    lower = float(release["lower_bound"])
    upper = float(release["upper_bound"])
    hit = None if actual_value is None else interval_hit(actual_value, lower, upper)
    return {
        "id": release["id"],
        "task_id": release.get("task_id"),
        "target_metric": release.get("target_metric"),
        "business_date": release.get("business_date"),
        "release_round": release.get("release_round"),
        "released_at": release.get("released_at"),
        "predicted_value": release.get("predicted_value"),
        "lower_bound": lower,
        "upper_bound": upper,
        "confidence": release.get("confidence"),
        "note": release.get("note") or "",
        "hit": hit,
        "scored": scored_release_id is not None and release["id"] == scored_release_id,
    }
