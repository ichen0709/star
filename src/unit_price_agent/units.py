"""單位對照與換算單價。

三種類型：重量（以 g 為基準）、容量（以 ml 為基準）、個數。
只有類型一樣才能比；重量和容量換算成「每 100g」「每 100ml」，個數是「每個」。
"""

from dataclasses import dataclass

WEIGHT, VOLUME, COUNT = "weight", "volume", "count"

# 寫法 → (標準寫法, 類型, 換成基準單位的倍數)。key 一律小寫、去空白。
_UNITS: dict[str, tuple[str, str, float]] = {
    "g": ("g", WEIGHT, 1), "公克": ("g", WEIGHT, 1), "克": ("g", WEIGHT, 1),
    "kg": ("kg", WEIGHT, 1000), "公斤": ("kg", WEIGHT, 1000), "千克": ("kg", WEIGHT, 1000),
    "ml": ("ml", VOLUME, 1), "毫升": ("ml", VOLUME, 1), "cc": ("ml", VOLUME, 1), "c.c.": ("ml", VOLUME, 1),
    "l": ("L", VOLUME, 1000), "公升": ("L", VOLUME, 1000), "升": ("L", VOLUME, 1000),
}
for _word in ("個", "入", "顆", "粒", "片", "支", "條", "包", "罐", "瓶", "盒", "袋", "枚", "pcs", "pc"):
    _UNITS[_word] = (_word, COUNT, 1)

PER_LABEL = {WEIGHT: "每 100g", VOLUME: "每 100ml", COUNT: "每個"}


@dataclass(frozen=True)
class UnitInfo:
    unit: str    # 標準寫法，例如 'ml'、'L'、'入'
    kind: str    # WEIGHT / VOLUME / COUNT
    factor: float


@dataclass(frozen=True)
class UnitPrice:
    kind: str
    value: float        # 每 100g／每 100ml／每個 的價格
    per_label: str


def normalize_unit(raw: object) -> UnitInfo | None:
    """認得的單位回 UnitInfo，不認得回 None。"""
    if not isinstance(raw, str):
        return None
    found = _UNITS.get(raw.strip().lower().replace(" ", ""))
    return UnitInfo(*found) if found else None


def unit_price(price: float, amount: float, unit: UnitInfo) -> UnitPrice:
    """price 是總價，amount 是總容量（單位是 unit）。"""
    base_amount = amount * unit.factor
    scale = 1 if unit.kind == COUNT else 100
    return UnitPrice(unit.kind, price / base_amount * scale, PER_LABEL[unit.kind])
