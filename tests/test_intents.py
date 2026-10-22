import pytest

from unit_price_agent.intents import apply_fix, parse_intent, select_for_query
from unit_price_agent.store import Record
from unit_price_agent.validate import ValidationError


def rec(i=1, *, category="鮮奶", name="光泉鮮乳", price=89.0, amount=936.0, unit="ml", unit_price=9.5):
    return Record(i, "2026-10-20 10:00:00", "7", "u", category, name, "光泉", price, amount, unit,
                  unit_price, "", "photos/x.png", "")


# ---- parse_intent：claude 回的固定格式 ----

def test_none_and_fix_and_query_are_parsed():
    assert parse_intent({"intent": "none"}).kind == "none"
    fix = parse_intent({"intent": "fix", "field": "price", "value": "89", "category": "", "limit": None})
    assert (fix.kind, fix.field, fix.value) == ("fix", "price", "89")
    query = parse_intent({"intent": "query", "field": "", "value": "", "category": "鮮奶", "limit": 3})
    assert (query.kind, query.category, query.limit) == ("query", "鮮奶", 3)


def test_chinese_field_names_are_accepted():
    assert parse_intent({"intent": "fix", "field": "價格", "value": "1"}).field == "price"
    assert parse_intent({"intent": "fix", "field": "店家", "value": "x"}).field == "store"


@pytest.mark.parametrize("field", ["id", "record_id", "user_id", "photo", "unit_price", "reply_id", "", None, 5])
def test_fix_only_allows_the_listed_fields(field):
    with pytest.raises(ValidationError, match="欄位"):
        parse_intent({"intent": "fix", "field": field, "value": "1"})


@pytest.mark.parametrize("raw", [None, [], "fix", {}, {"intent": "delete"}, {"intent": 1}])
def test_bad_shape_is_rejected(raw):
    with pytest.raises(ValidationError):
        parse_intent(raw)


@pytest.mark.parametrize("limit, expected", [(None, 10), (0, 1), (-3, 1), (5, 5), (10, 10), (999, 10),
                                              ("5", 10), (True, 10), (2.5, 10)])
def test_query_limit_is_clamped_to_1_to_10(limit, expected):
    assert parse_intent({"intent": "query", "category": "", "limit": limit}).limit == expected


# ---- apply_fix：驗證新值並重算單價 ----

def test_price_fix_recomputes_unit_price():
    changes = apply_fix(rec(), "price", "$100 元", [])
    assert changes["price"] == 100.0 and changes["unit_price"] == pytest.approx(100 / 936 * 100)


def test_amount_and_unit_fix_recompute_with_the_new_unit_kind():
    changes = apply_fix(rec(price=60, amount=600), "unit", "公斤", [])
    assert changes["unit"] == "kg" and changes["unit_price"] == pytest.approx(60 / 600000 * 100)
    assert apply_fix(rec(price=60, amount=600), "amount", "300", [])["unit_price"] == pytest.approx(20)


@pytest.mark.parametrize("field, value", [
    ("price", "-5"), ("price", "0"), ("price", "一百萬"), ("price", "1000000"), ("price", "abc"),
    ("price", "nan"), ("price", "inf"), ("amount", "-1"), ("amount", "很多"), ("unit", "oz"), ("unit", ""),
    ("name", "***"), ("name", "   "),
])
def test_unreasonable_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        apply_fix(rec(), field, value, [])


def test_text_fields_are_cleaned_but_formula_like_text_is_kept_as_data():
    assert apply_fix(rec(), "name", "=1+1", [])["name"] == "=1+1"
    assert apply_fix(rec(), "name", "+1", [])["name"] == "+1"
    assert apply_fix(rec(), "name", "-1", [])["name"] == "-1"
    assert apply_fix(rec(), "name", "@everyone <@123> https://evil.example **新**", [])["name"] == "新"
    assert apply_fix(rec(), "brand", "", [])["brand"] == ""  # 品牌可以清空
    assert "\t" not in apply_fix(rec(), "store", "\t=1+1", [])["store"]


def test_category_fix_follows_the_category_rules():
    assert apply_fix(rec(), "category", "鮮奶/牛奶", [])["category"] == "鮮奶牛奶"
    assert apply_fix(rec(), "category", "洋芋片 ", ["洋芋片"])["category"] == "洋芋片"
    assert apply_fix(rec(name="光泉鮮乳"), "category", "///", [])["category"] == "光泉鮮乳"


def test_fix_never_touches_other_fields():
    changes = apply_fix(rec(), "price", "99", [])
    assert set(changes) == {"price", "unit_price"}


# ---- 查詢 ----

def test_query_lists_newest_first_up_to_limit_and_counts_the_rest():
    records = [rec(i) for i in range(1, 13)]
    shown, more, _ = select_for_query(records, "", 10, ["鮮奶"])
    assert [r.record_id for r in shown] == list(range(12, 2, -1)) and more == 2


def test_query_filters_by_category_and_reuses_known_spelling():
    records = [rec(1), rec(2, category="洋芋片"), rec(3)]
    shown, more, category = select_for_query(records, "洋芋片!", 10, ["洋芋片", "鮮奶"])
    assert [r.record_id for r in shown] == [2] and more == 0 and category == "洋芋片"
    assert select_for_query(records, "醬油", 10, ["鮮奶"])[0] == []
