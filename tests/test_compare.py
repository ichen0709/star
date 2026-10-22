from unit_price_agent import compare as cmp
from unit_price_agent.store import Record


def rec(i, unit_price, *, user="1", category="鮮奶", unit="ml", name="n", brand="b"):
    return Record(i, "", user, "u", category, name, brand, 1, 1, unit, unit_price, "", "", "")


def run(history, value, kind="volume", **kw):
    return cmp.compare(history, user_id="1", category="鮮奶", kind=kind, value=value, **kw)


def test_first_record_in_category():
    assert run([rec(1, 5, category="醬油")], 9).outcome == cmp.FIRST


def test_other_users_history_is_ignored():
    assert run([rec(1, 5, user="2")], 9).outcome == cmp.FIRST


def test_history_with_other_kind_only_cannot_compare():
    assert run([rec(1, 5, unit="g")], 9).outcome == cmp.NO_COMPARABLE


def test_mixed_kinds_compare_against_same_kind_only():
    result = run([rec(1, 1, unit="g"), rec(2, 8)], 9)
    assert result.outcome == cmp.HIGHER and result.lowest.record_id == 2


def test_liters_and_ml_compare_directly():
    assert run([rec(1, 8, unit="L")], 6).outcome == cmp.NEW_LOWEST


def test_new_lowest_tie_and_higher():
    history = [rec(1, 8), rec(2, 6)]
    assert run(history, 5).outcome == cmp.NEW_LOWEST
    assert run(history, 6.0000000001).outcome == cmp.TIES_LOWEST
    higher = run(history, 9)
    assert higher.outcome == cmp.HIGHER and higher.lowest.record_id == 2
    assert higher.diff == 3 and round(higher.diff_pct) == 50


def test_excluded_record_is_not_compared_with_itself():
    assert run([rec(7, 5)], 5, exclude_id=7).outcome == cmp.FIRST
