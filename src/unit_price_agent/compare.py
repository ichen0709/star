"""找同類歷史、組比較結果。

歷史 = 同一個 Discord ID、同一個類別、類型（重量／容量／個數）一樣、不是這筆自己。
"""

import math
from dataclasses import dataclass

from .store import Record
from .units import normalize_unit

FIRST, NO_COMPARABLE, NEW_LOWEST, TIES_LOWEST, HIGHER = (
    "first", "no_comparable", "new_lowest", "ties_lowest", "higher")


@dataclass(frozen=True)
class Comparison:
    outcome: str
    lowest: Record | None = None   # 只有 TIES_LOWEST、HIGHER 會有：歷史最低那一筆
    diff: float = 0.0              # HIGHER：這次比最低貴多少（同一個單價基準）
    diff_pct: float = 0.0          # HIGHER：貴了幾 %


def _kind_of(record: Record) -> str | None:
    info = normalize_unit(record.unit)
    return info.kind if info else None


def compare(history: list[Record], *, user_id: str, category: str, kind: str, value: float,
            exclude_id: int | None = None) -> Comparison:
    """history 傳整份紀錄也可以；這裡再篩一次本人、同類別，並排除 exclude_id（這筆自己）。"""
    mine = [r for r in history
            if r.user_id == user_id and r.category == category and r.record_id != exclude_id]
    if not mine:
        return Comparison(FIRST)
    same_kind = [r for r in mine if _kind_of(r) == kind]
    if not same_kind:
        return Comparison(NO_COMPARABLE)

    lowest = min(same_kind, key=lambda r: (r.unit_price, r.record_id))
    if math.isclose(value, lowest.unit_price, rel_tol=1e-6):
        return Comparison(TIES_LOWEST, lowest)
    if value < lowest.unit_price:
        return Comparison(NEW_LOWEST)
    diff = value - lowest.unit_price
    return Comparison(HIGHER, lowest, diff, diff / lowest.unit_price * 100)
