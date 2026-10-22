"""修正與查詢：claude 轉出來的固定格式，由程式驗證後才執行。

claude 只負責把白話轉成 {intent, field, value, category, limit}；這裡逐欄驗證，
不符的丟 ValidationError（訊息只有「欄位：規則」，不含原文）。要不要做、怎麼做，都是程式決定。
"""

import re
from dataclasses import dataclass

from .store import Record
from .units import UnitInfo, normalize_unit, unit_price
from .validate import (ValidationError, category_chars, clean_model_text, validate_amount,
                       validate_category, validate_price)

FIX_FIELDS = ("name", "brand", "price", "amount", "unit", "category", "store")
FIELD_LABELS = {"name": "品名", "brand": "品牌", "price": "價格", "amount": "容量", "unit": "單位",
                "category": "類別", "store": "店家或地點"}
_FIELD_ALIASES = {label: field for field, label in FIELD_LABELS.items()} | {"店家": "store", "地點": "store"}

QUERY_MAX = 10
MAX_VALUE_LEN = 100  # 新值在清洗前先截到這個長度


@dataclass(frozen=True)
class Intent:
    kind: str              # fix / query / none
    field: str = ""        # fix：FIX_FIELDS 其中一個
    value: str = ""        # fix：新值（還沒驗證）
    category: str = ""     # query：類別（空＝不限）
    limit: int = QUERY_MAX  # query：筆數，1～10


def parse_intent(raw: object) -> Intent:
    """驗證 claude 回的固定格式。欄位名稱必須在可修改清單；筆數限制在 1～10。"""
    if not isinstance(raw, dict):
        raise ValidationError("意圖：不是固定格式")
    kind = raw.get("intent")
    if kind == "none":
        return Intent("none")
    if kind == "fix":
        field = raw.get("field")
        field = _FIELD_ALIASES.get(field, field) if isinstance(field, str) else None
        if field not in FIX_FIELDS:
            raise ValidationError("欄位：不在可修改清單")
        value = raw.get("value")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValidationError("新值：不是文字或數字")
        return Intent("fix", field=field, value=str(value)[:MAX_VALUE_LEN])
    if kind == "query":
        category = raw.get("category")
        limit = raw.get("limit")
        if isinstance(limit, bool) or not isinstance(limit, int):
            limit = QUERY_MAX
        return Intent("query", category=category if isinstance(category, str) else "",
                      limit=max(1, min(QUERY_MAX, limit)))
    raise ValidationError("意圖：不在允許的值裡")


def _parse_number(value: str, label: str) -> float:
    cleaned = re.sub(r"[\s,，$＄元]|NT|nt", "", value)
    try:
        return float(cleaned)
    except ValueError:
        raise ValidationError(f"{label}：不是數字") from None


def apply_fix(record: Record, field: str, value: str, known_categories: list[str]) -> dict:
    """驗證新值，回傳要寫進紀錄的欄位（含重算過的 unit_price）。不合格丟 ValidationError。"""
    changes: dict = {}
    if field == "name":
        name = clean_model_text(value)
        if not name:
            raise ValidationError("品名：清洗後是空的")
        changes["name"] = name
    elif field in ("brand", "store"):
        changes[field] = clean_model_text(value)
    elif field == "price":
        changes["price"] = validate_price(_parse_number(value, "價格"))
    elif field == "amount":
        changes["amount"] = validate_amount(_parse_number(value, "容量"))
    elif field == "unit":
        info = normalize_unit(value)
        if info is None:
            raise ValidationError("單位：不在認得的清單裡")
        changes["unit"] = info.unit
    elif field == "category":
        changes["category"] = validate_category(value, known_categories, record.name)
    else:
        raise ValidationError("欄位：不在可修改清單")

    price = changes.get("price", record.price)
    amount = changes.get("amount", record.amount)
    info: UnitInfo = normalize_unit(changes.get("unit", record.unit))
    changes["unit_price"] = unit_price(price, amount, info).value
    return changes


def select_for_query(records: list[Record], category: str, limit: int,
                     known_categories: list[str]) -> tuple[list[Record], int, str]:
    """本人的紀錄（呼叫端已篩過）依類別篩，新的在前。回傳（要列的, 還有幾筆沒列, 實際用的類別）。"""
    wanted = category_chars(category)
    if wanted:
        wanted = next((k for k in known_categories if k.casefold() == wanted.casefold()), wanted)
        records = [r for r in records if r.category == wanted]
    ordered = sorted(records, key=lambda r: r.record_id, reverse=True)
    return ordered[:limit], max(0, len(ordered) - limit), wanted
