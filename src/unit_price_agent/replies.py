"""回覆範本。回覆內容由程式用範本組出，只填入驗證過的欄位；claude 的文字不原樣貼進回覆。"""

from . import compare as cmp
from .units import UnitPrice
from .validate import Extraction


def format_number(value: float) -> str:
    """9.0 → '9'，9.5081 → '9.51'。"""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def processing(number: int, total: int) -> str:
    return prefix(number, total) + "處理中…"


def failure() -> str:
    return "這次處理失敗，請稍後再傳一次"


def too_many_images(limit: int) -> str:
    return f"一次最多 {limit} 張，其餘請分開傳"


def rate_limited() -> str:
    return "這個小時傳太多了，請稍後再傳"


def bad_image(max_mb: int) -> str:
    return f"這個檔案不是可以處理的圖片（只收 jpg、png、webp、gif，最大 {max_mb}MB），請重傳"


def unreasonable() -> str:
    return "辨識出來的品名、價格、容量或單位看不清楚或不合理，請重拍一張更清楚的再傳一次"


def prefix(number: int, total: int) -> str:
    return "" if total == 1 else f"【第 {number} 張】"


def comparison(result: cmp.Comparison, unit_price: UnitPrice) -> str:
    label = unit_price.per_label
    if result.outcome == cmp.FIRST:
        return "比較：這是這個類別的第一筆"
    if result.outcome == cmp.NO_COMPARABLE:
        return "比較：單位不同，無法比較（已照樣記下來）"
    if result.outcome == cmp.NEW_LOWEST:
        return "比較：這次是目前最低"
    low = result.lowest
    who = low.name + (f"（{low.brand}）" if low.brand else "")
    if result.outcome == cmp.TIES_LOWEST:
        return f"比較：和目前最低一樣（{who}，{label} {format_number(low.unit_price)}）"
    return (f"比較：歷史最低是 {who}，{label} {format_number(low.unit_price)}；"
            f"這次貴了 {format_number(result.diff)}（{format_number(result.diff_pct)}%）")


def for_extraction(ex: Extraction, unit_price: UnitPrice | None,
                   result: cmp.Comparison | None = None) -> str:
    if ex.status == "unreadable":
        return f"看不清楚：{ex.reason}。請重拍一張更清楚的。"
    if ex.status == "not_label":
        return f"這不是標價牌或商品：{ex.reason}。請重傳。"
    if ex.status == "multiple_items":
        return "照片裡有多個商品，請重拍成只有一個商品的標價牌。"

    lines = ["辨識結果", f"品名：{ex.name}"]
    if ex.brand:
        lines.append(f"品牌：{ex.brand}")
    lines.append(f"類別：{ex.category}")
    lines.append(f"價格：{format_number(ex.price)}")
    lines.append(f"容量：{format_number(ex.amount)} {ex.unit.unit}")
    if ex.store:
        lines.append(f"店家：{ex.store}")
    lines.append(f"單價：{unit_price.per_label} {format_number(unit_price.value)}")
    if result is not None:
        lines.append(comparison(result, unit_price))
    return "\n".join(lines)
