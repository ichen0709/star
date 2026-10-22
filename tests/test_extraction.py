import pytest

from unit_price_agent import replies
from unit_price_agent.units import unit_price
from unit_price_agent.validate import ValidationError, validate_extraction


def ok_data(**override):
    data = {"status": "ok", "reason": "", "name": "光泉鮮乳", "brand": "光泉", "price": 89,
            "amount": 936, "unit": "ml", "store": "全聯", "category": "鮮奶"}
    data.update(override)
    return data


def test_valid_extraction():
    ex = validate_extraction(ok_data(), ["鮮奶"])
    assert (ex.name, ex.brand, ex.price, ex.amount, ex.unit.unit, ex.category) == (
        "光泉鮮乳", "光泉", 89.0, 936.0, "ml", "鮮奶")


def test_known_category_name_is_reused():
    assert validate_extraction(ok_data(category="鮮奶 "), ["鮮奶"]).category == "鮮奶"


@pytest.mark.parametrize("override", [
    {"price": 0}, {"price": -1}, {"price": "89"}, {"price": None},
    {"amount": 0}, {"amount": None}, {"unit": "oz"}, {"unit": ""},
    {"name": ""}, {"name": "   "},
])
def test_bad_fields_are_rejected(override):
    with pytest.raises(ValidationError):
        validate_extraction(ok_data(**override), [])


@pytest.mark.parametrize("data", [None, [], "ok", {}, {"status": "weird"}, {"status": 1}])
def test_bad_shape_is_rejected(data):
    with pytest.raises(ValidationError):
        validate_extraction(data, [])


@pytest.mark.parametrize("status", ["unreadable", "not_label", "multiple_items"])
def test_non_ok_statuses_need_no_other_fields(status):
    ex = validate_extraction({"status": status, "reason": "原因"}, [])
    assert ex.status == status and ex.reason == "原因"
    assert validate_extraction({"status": status}, []).reason  # 有預設說明


def test_reply_for_ok_extraction():
    ex = validate_extraction(ok_data(), [])
    text = replies.for_extraction(ex, unit_price(ex.price, ex.amount, ex.unit))
    assert "品名：光泉鮮乳" in text
    assert "容量：936 ml" in text
    assert "單價：每 100ml 9.51" in text


def test_reply_for_non_ok():
    ex = validate_extraction({"status": "not_label", "reason": "一隻貓"}, [])
    assert "一隻貓" in replies.for_extraction(ex, None)
    assert "重拍" in replies.for_extraction(validate_extraction({"status": "unreadable"}, []), None)


def test_format_number():
    assert replies.format_number(9.5085) == "9.51"
    assert replies.format_number(10.0) == "10"
    assert replies.format_number(0.5) == "0.5"


# ---- 說明文字清洗（防護 2）----

from unit_price_agent.validate import MAX_REASON_LEN, clean_reason

DEFAULT = "預設說明"


@pytest.mark.parametrize("raw,expected", [
    ("價格被手指遮住了。", "價格被手指遮住了"),
    ("價格被遮住了！！", "價格被遮住了"),
    ("光線太暗…", "光線太暗"),
    ("太模糊, ", "太模糊"),
    ("看到一隻貓。 。", "看到一隻貓"),
    ("看到一隻貓", "看到一隻貓"),
])
def test_clean_reason_drops_trailing_punctuation(raw, expected):
    assert clean_reason(raw, DEFAULT) == expected


def test_reply_has_no_double_period():
    ex = validate_extraction({"status": "unreadable", "reason": "價格被遮住了。"}, [])
    text = replies.for_extraction(ex, None)
    assert "。。" not in text and text.startswith("看不清楚：價格被遮住了。")


def test_clean_reason_removes_newlines_and_extra_spaces():
    assert clean_reason("第一行\n第二行\r\n\t第三行", DEFAULT) == "第一行 第二行 第三行"


@pytest.mark.parametrize("raw", [
    "@everyone 快來", "@here 快來", "<@123456789012345678> 快來", "<@!123456789012345678> 快來",
    "<@&123456789012345678> 快來", "<#123456789012345678> 快來", "<:emoji:123456789012345678> 快來",
    "@someone 快來",
])
def test_clean_reason_removes_mentions(raw):
    result = clean_reason(raw, DEFAULT)
    assert "@" not in result and "<" not in result and "everyone" not in result and "here" not in result
    assert "123456" not in result
    assert result.endswith("快來")


@pytest.mark.parametrize("raw", [
    "請看 https://evil.example/a?b=c 這裡", "請看 http://evil.example 這裡", "請看 www.evil.example 這裡",
    "請看 discord.gg/abcdef 這裡", "請看 [點我](https://evil.example/x) 這裡",
])
def test_clean_reason_removes_urls(raw):
    result = clean_reason(raw, DEFAULT)
    assert "evil" not in result and "discord.gg" not in result and "http" not in result
    assert "請看" in result and "這裡" in result


def test_clean_reason_removes_markdown_symbols():
    result = clean_reason("**粗體** _斜體_ ~~刪除~~ `code` > 引用 | 表格", DEFAULT)
    assert not any(ch in result for ch in "`*_~>|")
    assert "粗體" in result and "表格" in result


def test_clean_reason_truncates_to_80_characters():
    result = clean_reason("很" * 200, DEFAULT)
    assert len(result) == MAX_REASON_LEN == 80
    # 截斷的位置剛好是標點，也要再去掉
    assert clean_reason("好" * 79 + "。後面還有很多", DEFAULT) == "好" * 79


@pytest.mark.parametrize("raw", ["", "   ", "。。。", "\n\n", "@everyone", "https://evil.example", "***", None, 5, ["x"]])
def test_clean_reason_uses_default_when_nothing_is_left(raw):
    assert clean_reason(raw, DEFAULT) == DEFAULT


def test_validate_extraction_uses_status_default_reason_when_cleaned_reason_is_empty():
    ex = validate_extraction({"status": "not_label", "reason": "https://evil.example @everyone"}, [])
    assert ex.reason == "這看起來不是標價牌或商品"
    assert "evil" not in replies.for_extraction(ex, None)


# ---- 品名、品牌、店家：和說明文字共用同一個清洗函式 ----

from unit_price_agent.validate import MAX_TEXT_LEN, clean_model_text


@pytest.mark.parametrize("name", [
    "M&M's 巧克力", "100% 柳橙汁", "桂格養氣人蔘", "光泉鮮乳 1.5L/瓶", "Dr.Pepper 可樂",
    "7-ELEVEN 御飯糰", "好市多 Kirkland (2.5kg)", "蘋果西打 330ml x 6", "Lay's 樂事洋芋片!",
    "【限定】草莓牛奶", "C&C 冰淇淋", "Häagen-Dazs 冰淇淋", "A+ 高鈣牛奶", "$100 優惠組",
])
def test_normal_product_names_are_not_damaged(name):
    assert clean_model_text(name) == name
    assert validate_extraction(ok_data(name=name, brand=name, store=name), []).name == name


@pytest.mark.parametrize("raw,expected", [
    ("鮮乳 https://evil.example/a?b=c", "鮮乳"),
    ("鮮乳 www.evil.example", "鮮乳"),
    ("鮮乳 evil.com", "鮮乳"),
    ("鮮乳 discord.gg/abcdef", "鮮乳"),
    ("鮮乳 <@123456789012345678>", "鮮乳"),
    ("鮮乳 <@&123456789012345678>", "鮮乳"),
    ("@everyone 鮮乳", "鮮乳"),
    ("@here 鮮乳", "鮮乳"),
    ("**鮮乳**", "鮮乳"),
    ("`鮮乳` ~~特價~~ _限定_", "鮮乳 特價 限定"),
    ("> 鮮乳 | 特價", "鮮乳 特價"),
    ("鮮乳\n特價\r\n限定", "鮮乳 特價 限定"),
])
def test_name_is_cleaned_like_the_reason_text(raw, expected):
    assert validate_extraction(ok_data(name=raw), []).name == expected


@pytest.mark.parametrize("field", ["brand", "store"])
def test_brand_and_store_are_cleaned_too(field):
    ex = validate_extraction(ok_data(**{field: "光泉 <@123456789012345678> @everyone https://evil.example **全聯**\n分店"}), [])
    value = getattr(ex, field)
    assert value == "光泉 全聯 分店"


def test_name_brand_and_store_are_limited_to_60_characters():
    ex = validate_extraction(ok_data(name="名" * 100, brand="牌" * 100, store="店" * 100), [])
    assert len(ex.name) == len(ex.brand) == len(ex.store) == MAX_TEXT_LEN == 60


def test_name_keeps_its_trailing_punctuation_but_reason_does_not():
    assert clean_model_text("好吃!!") == "好吃!!"
    assert clean_model_text("好吃!!", strip_trailing_punct=True) == "好吃"


@pytest.mark.parametrize("name", ["", "   ", "https://evil.example", "<@123456789012345678>", "@everyone", "***", "\n\n", None, 5])
def test_empty_name_after_cleaning_is_a_recognition_failure(name):
    with pytest.raises(ValidationError):
        validate_extraction(ok_data(name=name), [])


@pytest.mark.parametrize("field", ["brand", "store"])
@pytest.mark.parametrize("value", ["", "https://evil.example", "@everyone", "***", None])
def test_empty_brand_or_store_after_cleaning_means_none(field, value):
    ex = validate_extraction(ok_data(**{field: value}), [])
    assert getattr(ex, field) == ""


def test_category_with_slash_is_cleaned_not_rejected():
    assert validate_extraction(ok_data(category="鮮奶/牛奶"), []).category == "鮮奶牛奶"
    assert validate_extraction(ok_data(category="鮮奶"), ["鮮奶"]).category == "鮮奶"


def test_category_equals_1_plus_1_is_cleaned_and_name_stays_plain_text_data():
    ex = validate_extraction(ok_data(name="=1+1", category="=1+1"), [])
    assert ex.name == "=1+1" and ex.category == "11"


@pytest.mark.parametrize("category", ["", "   ", "/// ", None])
def test_empty_category_uses_the_cleaned_name(category):
    ex = validate_extraction(ok_data(name="光泉/鮮乳", category=category), [])
    assert ex.category == "光泉鮮乳"
    assert validate_extraction(ok_data(name="名" * 40, category=category), []).category == "名" * 20


def test_name_with_nothing_usable_for_a_category_is_a_recognition_failure():
    with pytest.raises(ValidationError, match="類別"):
        validate_extraction(ok_data(name="!!!", category=""), [])


def test_validation_errors_name_the_field_and_never_quote_the_model():
    secret = "SECRET-MODEL-TEXT"
    for override, field in [({"price": secret}, "價格"), ({"amount": None}, "容量"),
                            ({"unit": secret}, "單位"), ({"name": "***"}, "品名")]:
        with pytest.raises(ValidationError) as info:
            validate_extraction(ok_data(**override), [])
        assert str(info.value).startswith(field) and secret not in str(info.value)


def test_reply_never_contains_mentions_links_or_markdown_from_the_model():
    ex = validate_extraction(ok_data(name="**@everyone** 鮮乳 https://evil.example", brand="<@1>光泉", store="`全聯`"), [])
    text = replies.for_extraction(ex, unit_price(ex.price, ex.amount, ex.unit))
    assert "@" not in text and "evil" not in text and "`" not in text and "*" not in text and "<" not in text
