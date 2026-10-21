import pytest

from unit_price_agent.units import COUNT, VOLUME, WEIGHT, normalize_unit, unit_price


@pytest.mark.parametrize("raw,unit,kind,factor", [
    ("g", "g", WEIGHT, 1), ("公克", "g", WEIGHT, 1), ("克", "g", WEIGHT, 1),
    ("kg", "kg", WEIGHT, 1000), ("KG", "kg", WEIGHT, 1000), ("公斤", "kg", WEIGHT, 1000),
    ("ml", "ml", VOLUME, 1), ("ML", "ml", VOLUME, 1), ("毫升", "ml", VOLUME, 1), ("cc", "ml", VOLUME, 1),
    ("L", "L", VOLUME, 1000), ("l", "L", VOLUME, 1000), ("公升", "L", VOLUME, 1000),
    ("個", "個", COUNT, 1), ("入", "入", COUNT, 1), (" 入 ", "入", COUNT, 1), ("罐", "罐", COUNT, 1),
])
def test_known_units(raw, unit, kind, factor):
    info = normalize_unit(raw)
    assert (info.unit, info.kind, info.factor) == (unit, kind, factor)


@pytest.mark.parametrize("raw", ["", "斤", "oz", "公尺", "=1+1", None, 5, "ml; rm"])
def test_unknown_units_return_none(raw):
    assert normalize_unit(raw) is None


def test_volume_per_100ml():
    result = unit_price(89, 936, normalize_unit("ml"))
    assert result.kind == VOLUME and result.per_label == "每 100ml"
    assert result.value == pytest.approx(9.5085, abs=1e-3)


def test_liters_convert_to_ml():
    assert unit_price(120, 2, normalize_unit("L")).value == pytest.approx(6.0)
    assert unit_price(120, 2, normalize_unit("公升")).value == pytest.approx(
        unit_price(120, 2000, normalize_unit("ml")).value)


def test_weight_per_100g():
    assert unit_price(50, 500, normalize_unit("g")).value == pytest.approx(10.0)
    result = unit_price(100, 1, normalize_unit("kg"))
    assert result.value == pytest.approx(10.0) and result.per_label == "每 100g"


def test_count_per_item():
    result = unit_price(60, 6, normalize_unit("入"))
    assert result.kind == COUNT and result.per_label == "每個"
    assert result.value == pytest.approx(10.0)
