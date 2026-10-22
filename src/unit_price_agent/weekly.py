"""週報：全由程式計算，不經過 claude。

「這週」「上週」用週一到週日的日曆週（Asia/Taipei）。紀錄的日期時間存的就是台北時間（不帶時區）。
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .store import TIME_FORMAT, Record
from .units import PER_LABEL, normalize_unit


@dataclass(frozen=True)
class GroupLine:
    category: str
    per_label: str
    count: int
    cheapest: Record
    avg: float
    last_week_avg: float | None  # 上週同類別、同類型沒記就是 None


@dataclass(frozen=True)
class WeeklyReport:
    total: int
    lines: list[GroupLine]


def week_start(now: datetime) -> datetime:
    """這個日曆週的週一 00:00。"""
    return (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def latest_due(now: datetime, weekday: int, hour: int, minute: int) -> datetime:
    """現在或之前、最近一次的排程時間（例如「每週日 20:00」）。"""
    due = (now - timedelta(days=(now.weekday() - weekday) % 7)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)
    return due if due <= now else due - timedelta(days=7)


def _when(record: Record) -> datetime | None:
    try:
        return datetime.strptime(record.when, TIME_FORMAT)
    except ValueError:
        return None


def _kind(record: Record) -> str | None:
    info = normalize_unit(record.unit)
    return info.kind if info else None


def build_report(user_records: list[Record], now: datetime) -> WeeklyReport | None:
    """一個人這週（週一 00:00 到 now）的週報；這週沒記東西回 None。"""
    start = week_start(now)
    last_start = start - timedelta(days=7)
    this_week, last_week = [], []
    for r in sorted(user_records, key=lambda r: r.record_id):
        when = _when(r)
        if when is None or _kind(r) is None:
            continue
        if start <= when <= now:
            this_week.append(r)
        elif last_start <= when < start:
            last_week.append(r)
    if not this_week:
        return None

    groups: dict[tuple[str, str], list[Record]] = {}
    for r in this_week:
        groups.setdefault((r.category, _kind(r)), []).append(r)
    lines = []
    for (category, kind), recs in groups.items():
        previous = [r.unit_price for r in last_week if r.category == category and _kind(r) == kind]
        lines.append(GroupLine(
            category=category, per_label=PER_LABEL[kind], count=len(recs),
            cheapest=min(recs, key=lambda r: (r.unit_price, r.record_id)),
            avg=sum(r.unit_price for r in recs) / len(recs),
            last_week_avg=sum(previous) / len(previous) if previous else None))
    return WeeklyReport(total=len(this_week), lines=lines)


def compare_average(this_avg: float, last_avg: float) -> tuple[str, float, float]:
    """回傳（'貴'／'便宜'／'一樣'，差多少，差幾 %）。"""
    diff = this_avg - last_avg
    if math.isclose(this_avg, last_avg, rel_tol=1e-6):
        return "一樣", 0.0, 0.0
    return ("貴" if diff > 0 else "便宜"), abs(diff), abs(diff) / last_avg * 100
