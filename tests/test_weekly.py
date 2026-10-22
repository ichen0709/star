from datetime import datetime

import pytest

from unit_price_agent import replies
from unit_price_agent.store import Record
from unit_price_agent.weekly import build_report, compare_average, latest_due, week_start

SUN_20 = (6, 20, 0)
# 2026-10-26 是週一，2026-11-01 是週日
NOW = datetime(2026, 10, 28, 15, 0)  # 週三


def rec(i, when, unit_price, *, category="鮮奶", unit="ml", name="光泉鮮乳", brand="光泉"):
    return Record(i, when, "7", "u", category, name, brand, 1, 1, unit, unit_price, "", "p", "")


def test_week_start_is_monday_midnight():
    assert week_start(datetime(2026, 11, 1, 23, 59)) == datetime(2026, 10, 26)
    assert week_start(datetime(2026, 10, 26, 0, 0)) == datetime(2026, 10, 26)


@pytest.mark.parametrize("now, expected", [
    (datetime(2026, 11, 1, 20, 0), datetime(2026, 11, 1, 20, 0)),    # 剛好到點
    (datetime(2026, 11, 1, 19, 59), datetime(2026, 10, 25, 20, 0)),  # 還沒到：上一個週日
    (datetime(2026, 10, 28, 15, 0), datetime(2026, 10, 25, 20, 0)),
    (datetime(2026, 11, 2, 9, 0), datetime(2026, 11, 1, 20, 0)),
])
def test_latest_due(now, expected):
    assert latest_due(now, *SUN_20) == expected


def test_no_records_this_week_means_no_report():
    assert build_report([], NOW) is None
    assert build_report([rec(1, "2026-10-20 10:00:00", 9)], NOW) is None  # 只有上週
    assert build_report([rec(1, "2026-10-29 10:00:00", 9)], NOW) is None  # 還沒發生


def test_report_counts_cheapest_per_category():
    records = [rec(1, "2026-10-26 08:00:00", 10), rec(2, "2026-10-27 08:00:00", 8, name="便宜乳"),
               rec(3, "2026-10-27 09:00:00", 5, category="洋芋片", unit="g", name="薯片")]
    report = build_report(records, NOW)
    assert report.total == 3
    milk, chips = report.lines
    assert (milk.category, milk.count, milk.cheapest.name, milk.per_label) == ("鮮奶", 2, "便宜乳", "每 100ml")
    assert milk.avg == 9 and milk.last_week_avg is None
    assert (chips.category, chips.per_label) == ("洋芋片", "每 100g")


def test_last_week_average_only_when_same_category_and_kind_was_recorded():
    records = [rec(1, "2026-10-20 08:00:00", 6), rec(2, "2026-10-21 08:00:00", 8),  # 上週：平均 7
               rec(3, "2026-10-27 08:00:00", 9),
               rec(4, "2026-10-21 08:00:00", 1, category="洋芋片", unit="g"),
               rec(5, "2026-10-27 08:00:00", 5, category="洋芋片", unit="ml")]  # 上週是 g，這週是 ml
    milk, chips = build_report(records, NOW).lines
    assert milk.last_week_avg == 7
    assert chips.last_week_avg is None


def test_week_boundaries_monday_start_sunday_end():
    records = [rec(1, "2026-10-25 23:59:59", 6),   # 上週日最後一秒
               rec(2, "2026-10-26 00:00:00", 9)]   # 這週一第一秒
    line = build_report(records, NOW).lines[0]
    assert line.count == 1 and line.last_week_avg == 6


def test_sunday_report_counts_up_to_that_moment():
    sunday = datetime(2026, 11, 1, 20, 0)
    records = [rec(1, "2026-11-01 19:59:59", 9), rec(2, "2026-11-01 20:00:01", 5)]
    assert build_report(records, sunday).total == 1


def test_compare_average():
    assert compare_average(10, 8)[0] == "貴" and compare_average(6, 8)[0] == "便宜"
    assert compare_average(8, 8) == ("一樣", 0.0, 0.0)
    assert compare_average(10, 8)[1:] == (2, 25)


def test_weekly_text_says_more_expensive_or_cheaper_only_with_last_week():
    records = [rec(1, "2026-10-20 08:00:00", 8), rec(2, "2026-10-27 08:00:00", 10)]
    assert "平均單價比上週貴 2（25%）" in replies.weekly(build_report(records, NOW))
    cheaper = [rec(1, "2026-10-20 08:00:00", 10), rec(2, "2026-10-27 08:00:00", 8)]
    assert "比上週便宜 2（20%）" in replies.weekly(build_report(cheaper, NOW))
    assert "上週" not in replies.weekly(build_report([rec(2, "2026-10-27 08:00:00", 10)], NOW))
