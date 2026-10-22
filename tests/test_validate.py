from datetime import datetime
from pathlib import Path

import pytest

from unit_price_agent.validate import (
    ValidationError,
    build_photo_filename,
    check_image_bytes,
    clean_text,
    ensure_inside,
    sanitize_filename_part,
    validate_amount,
    validate_category,
    validate_price,
)

WHEN = datetime(2026, 1, 2, 3, 4, 5)


@pytest.mark.parametrize("raw", ["../../evil", "..\\..\\evil", "a/b\\c", "a:b*c?d|e<f>g\"h"])
def test_filename_has_no_path_characters(raw):
    part = sanitize_filename_part(raw)
    assert ".." not in part
    assert not any(c in part for c in '/\\:*?"<>|')


@pytest.mark.parametrize("raw", ["", "   ", "..", "...", "CON", "nul", "com1", "\x00\x01"])
def test_filename_falls_back_to_default(raw):
    assert sanitize_filename_part(raw) == "item"


def test_filename_is_shortened():
    assert len(sanitize_filename_part("很長" * 50)) <= 30


def test_filename_keeps_normal_chinese():
    assert sanitize_filename_part("光泉 鮮乳 936ml") == "光泉鮮乳936ml"


def test_build_photo_filename():
    assert build_photo_filename(WHEN, "鮮乳", ".png") == "20260102-030405_鮮乳.png"


def test_build_photo_filename_rejects_unknown_extension():
    with pytest.raises(ValidationError):
        build_photo_filename(WHEN, "鮮乳", ".exe")


def test_build_photo_filename_traversal_stays_a_plain_name():
    name = build_photo_filename(WHEN, "../../evil", ".jpg")
    assert "/" not in name and "\\" not in name and ".." not in name


def test_ensure_inside(tmp_path):
    base = tmp_path / "photos"
    base.mkdir()
    assert ensure_inside(base, base / "a.png") == (base / "a.png").resolve()
    with pytest.raises(ValidationError):
        ensure_inside(base, base / ".." / "evil.png")
    with pytest.raises(ValidationError):
        ensure_inside(base, Path(tmp_path) / "other.png")


def test_clean_text_removes_control_characters_and_limits_length():
    assert clean_text("光泉\x00\x1b鮮乳\n\t 936") == "光泉 鮮乳 936"
    assert len(clean_text("a" * 500)) == 60
    assert clean_text(123) == ""


def test_category_prefers_known_name():
    assert validate_category("鮮奶", ["鮮奶", "洋芋片"]) == "鮮奶"
    assert validate_category(" ABC ", ["abc"]) == "abc"


def test_category_accepts_new_valid_name():
    assert validate_category("礦泉水", ["鮮奶"]) == "礦泉水"


@pytest.mark.parametrize("raw, expected", [
    ("鮮奶/牛奶", "鮮奶牛奶"), ("../x", "x"), ("鮮奶=1+1", "鮮奶11"), ("**鮮奶**", "鮮奶"),
    ("Coca Cola", "CocaCola"), ("a" * 30, "a" * 20), ("鮮奶!", "鮮奶"),
])
def test_category_is_cleaned_to_chinese_english_digits_and_20_chars(raw, expected):
    assert validate_category(raw, []) == expected


def test_cleaned_category_still_reuses_the_known_spelling():
    assert validate_category("鮮奶/", ["鮮奶"]) == "鮮奶"


@pytest.mark.parametrize("raw", ["", "   ", "=+-", "///", None, 5])
def test_empty_category_falls_back_to_cleaned_name_limited_to_20(raw):
    assert validate_category(raw, [], "光泉/鮮乳 936ml") == "光泉鮮乳936ml"
    assert validate_category(raw, [], "名" * 30) == "名" * 20


@pytest.mark.parametrize("raw", ["", "=+-", None])
@pytest.mark.parametrize("name", ["", "   ", "!!!", "///", None])
def test_category_and_name_both_empty_is_an_error_naming_the_field(raw, name):
    with pytest.raises(ValidationError, match="類別"):
        validate_category(raw, ["鮮奶"], name)


@pytest.mark.parametrize("raw", [89, 89.5, 0.01])
def test_price_and_amount_accept_positive_numbers(raw):
    assert validate_price(raw) == float(raw)
    assert validate_amount(raw) == float(raw)


@pytest.mark.parametrize("raw", [0, -5, 10**7, float("nan"), float("inf"), "89", None, True, [1]])
def test_price_and_amount_reject_bad_values(raw):
    with pytest.raises(ValidationError):
        validate_price(raw)
    with pytest.raises(ValidationError):
        validate_amount(raw)


@pytest.mark.parametrize("data,ext", [
    (b"\x89PNG\r\n\x1a\n" + b"0" * 20, ".png"),
    (b"\xff\xd8\xff\xe0" + b"0" * 20, ".jpg"),
    (b"GIF89a" + b"0" * 20, ".gif"),
    (b"RIFF\x00\x00\x00\x00WEBP" + b"0" * 20, ".webp"),
])
def test_image_types_by_content(data, ext):
    assert check_image_bytes(data, 10) == ext


@pytest.mark.parametrize("data", [b"", b"MZ\x90\x00" + b"0" * 20, b"<html>x</html>", b"%PDF-1.7 ...."])
def test_image_rejects_other_content(data):
    with pytest.raises(ValidationError):
        check_image_bytes(data, 10)


def test_image_rejects_too_big():
    with pytest.raises(ValidationError):
        check_image_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024), 1)
