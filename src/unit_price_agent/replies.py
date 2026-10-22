"""回覆範本。回覆內容由程式用範本組出，只填入驗證過的欄位；claude 的文字不原樣貼進回覆。"""

from . import compare as cmp
from .intents import FIELD_LABELS
from .store import Record
from .units import PER_LABEL, UnitPrice, normalize_unit
from .validate import Extraction
from .weekly import GroupLine, WeeklyReport, compare_average


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

    return "\n".join(_result_lines("辨識結果", ex, unit_price, result))


def _result_lines(header: str, ex: Extraction, unit_price: UnitPrice,
                  result: cmp.Comparison | None) -> list[str]:
    lines = [header, f"品名：{ex.name}"]
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
    return lines


# ---- 階段 4：修正、查詢、週報、說明 ----

def rate_limited_text() -> str:
    return "這個小時問太多了，請稍後再問"


def help_text() -> str:
    return ("我是單價比價員。傳標價牌或商品的照片，我會換算單價並和你以前記過的同類商品比較。\n"
            "辨識錯了，請回覆我的那則結果並說要改什麼（例如「價格改成 89」）；"
            "也可以問「我記過哪些鮮奶」，或輸入「週報」看你這週的紀錄。")


def fix_need_reply() -> str:
    return "請回覆要修正的那則 bot 訊息"


def fix_not_a_record() -> str:
    return "這則訊息不是一筆紀錄，請回覆要修正的那則辨識結果"


def fix_not_yours() -> str:
    return "這不是你的紀錄，不能修改"


def fix_rejected(label: str) -> str:
    return f"{label}的新值看不懂或不合理，沒有修改。請換個說法再試一次"


def fixed(field: str, record: Record, result: cmp.Comparison | None) -> str:
    ex = Extraction(status="ok", reason="", name=record.name, brand=record.brand, price=record.price,
                    amount=record.amount, unit=normalize_unit(record.unit), store=record.store,
                    category=record.category)
    kind = ex.unit.kind
    price = UnitPrice(kind, record.unit_price, PER_LABEL[kind])
    return "\n".join(_result_lines(f"已修正：{FIELD_LABELS[field]}", ex, price, result))


def _record_line(r: Record) -> str:
    who = r.name + (f"（{r.brand}）" if r.brand else "")
    kind = normalize_unit(r.unit).kind
    return (f"#{r.record_id} {r.when[:10]} {r.category}｜{who} "
            f"{format_number(r.price)} 元 / {format_number(r.amount)} {r.unit} → "
            f"{PER_LABEL[kind]} {format_number(r.unit_price)}")


def query_result(shown: list[Record], more: int, category: str) -> str:
    if not shown:
        return f"沒有找到「{category}」的紀錄" if category else "你還沒有任何紀錄"
    title = f"你的紀錄（{category}）" if category else "你的紀錄"
    lines = [f"{title}，新的在前："] + [_record_line(r) for r in shown]
    if more:
        lines.append(f"還有 {more} 筆")
    return "\n".join(lines)[:1900]


def weekly_empty() -> str:
    return "這週還沒有紀錄"


def _weekly_line(line: GroupLine) -> str:
    who = line.cheapest.name + (f"（{line.cheapest.brand}）" if line.cheapest.brand else "")
    text = (f"・{line.category}：{line.count} 筆，最便宜 {who} "
            f"{line.per_label} {format_number(line.cheapest.unit_price)}")
    if line.last_week_avg is not None:
        trend, diff, pct = compare_average(line.avg, line.last_week_avg)
        if trend == "一樣":
            text += "；平均單價和上週一樣"
        else:
            text += f"；平均單價比上週{trend} {format_number(diff)}（{format_number(pct)}%）"
    return text


def weekly(report: WeeklyReport) -> str:
    lines = [f"本週記了 {report.total} 筆"] + [_weekly_line(l) for l in report.lines]
    return "\n".join(lines)[:1900]
