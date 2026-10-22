"""輸入與輸出的驗證與清洗。

防護 3（檔名與路徑清洗）在這個檔案。
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .units import UnitInfo, normalize_unit

# 價格、容量的上限先寫寬鬆，實作時再依實際使用調整。
MAX_PRICE = 100_000
MAX_AMOUNT = 100_000
MAX_TEXT_LEN = 60
MAX_CATEGORY_LEN = 20

IMAGE_SIGNATURES = {
    ".jpg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".gif": (b"GIF87a", b"GIF89a"),
}

ALLOWED_IMAGE_EXTS = {*IMAGE_SIGNATURES, ".webp"}

_CONTROL_RE =re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁦-⁩﻿]")
_CATEGORY_STRIP_RE = re.compile(r"[^一-鿿A-Za-z0-9]")


class ValidationError(ValueError):
    """輸入或 claude 的輸出不合格。訊息不含使用者給的原文。"""


# ==== 防護 3：檔名與路徑清洗　開始 ====
_FORBIDDEN_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename_part(text: str, max_len: int = 30, default: str = "item") -> str:
    """把品名之類的文字清成可以放進檔名的一小段。

    去掉路徑符號、「..」、控制字元、Windows 不能用的字元與保留字，限制長度；
    清完是空的就用預設名稱。
    """
    text = _CONTROL_RE.sub("", text or "")
    text = _FORBIDDEN_FILENAME_CHARS.sub("", text)
    text = re.sub(r"\.{2,}", "", text)
    text = re.sub(r"\s+", "", text)
    text = text.strip(". ")
    text = text[:max_len].strip(". ")
    if not text or text.upper() in _WINDOWS_RESERVED:
        return default
    return text


def build_photo_filename(when: datetime, product_name: str, ext: str) -> str:
    """檔名：日期時間_品名簡稱.副檔名。副檔名只收程式自己判斷出來的那幾種。"""
    if ext not in ALLOWED_IMAGE_EXTS:
        raise ValidationError("不支援的圖片副檔名")
    stamp = when.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}_{sanitize_filename_part(product_name)}{ext}"


def ensure_inside(base_dir: Path, target: Path) -> Path:
    """確認 target 真的在 base_dir 底下（擋掉 .. 和符號連結繞出去）。"""
    base = base_dir.resolve()
    resolved = target.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValidationError("路徑不在允許的資料夾內")
    return resolved
# ==== 防護 3 結束 ====


def clean_text(text: object, max_len: int = MAX_TEXT_LEN) -> str:
    """文字欄位（品名、品牌、店家）：去控制字元、合併空白、限制長度。"""
    if not isinstance(text, str):
        return ""
    text = _CONTROL_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len].strip()


def _category_chars(text: object) -> str:
    """只留中英文與數字，限 20 字。"""
    if not isinstance(text, str):
        return ""
    return _CATEGORY_STRIP_RE.sub("", text)[:MAX_CATEGORY_LEN]


def validate_category(raw: object, known: list[str], fallback_name: str = "") -> str:
    """類別：先清洗成只剩中英文與數字（限 20 字），和這個人用過的名稱同名就沿用那個寫法。

    清完是空的，改用清洗後的品名（fallback_name，同樣限 20 字）；品名也清不出內容才丟 ValidationError。
    """
    cleaned = _category_chars(raw) or _category_chars(fallback_name)
    if not cleaned:
        raise ValidationError("類別：清洗後是空的，品名也清不出可用的字")
    for name in known:
        if cleaned.casefold() == name.casefold():
            return name
    return cleaned


def _validate_positive_number(raw: object, upper: float, label: str) -> float:
    # bool 是 int 的子類別，要先排除
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValidationError(f"{label}：不是數字")
    value = float(raw)
    if not math.isfinite(value) or value <= 0 or value > upper:
        raise ValidationError(f"{label}：超出合理範圍")
    return value


def validate_price(raw: object) -> float:
    return _validate_positive_number(raw, MAX_PRICE, "價格")


def validate_amount(raw: object) -> float:
    return _validate_positive_number(raw, MAX_AMOUNT, "容量")


def sniff_image_ext(header: bytes) -> str | None:
    """用檔案開頭的位元組判斷圖片型別，不信使用者給的副檔名或 content-type。"""
    for ext, signatures in IMAGE_SIGNATURES.items():
        if any(header.startswith(sig) for sig in signatures):
            return ext
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    return None


def check_image_bytes(data: bytes, max_mb: int) -> str:
    """檢查圖片大小與型別，回傳副檔名（例如 '.png'）。不合格丟 ValidationError。"""
    if not data:
        raise ValidationError("圖片是空的")
    if len(data) > max_mb * 1024 * 1024:
        raise ValidationError(f"圖片超過 {max_mb}MB")
    ext = sniff_image_ext(data[:16])
    if ext is None:
        raise ValidationError("不是支援的圖片型別（只收 jpg、png、webp、gif）")
    return ext


# ---- claude 看圖的輸出驗證 ----

STATUSES = {"ok", "unreadable", "not_label", "multiple_items"}
_DEFAULT_REASON = {
    "unreadable": "看不清楚",
    "not_label": "這看起來不是標價牌或商品",
    "multiple_items": "照片裡有多個商品",
}

# ==== 防護 2：模型給的文字清洗（說明、品名、品牌、店家）　開始 ====
# 模型回的這幾種文字會貼進回覆、也會寫進紀錄，都走同一個清洗函式 clean_model_text。
# 類別不走這裡，照 validate_category 的規則。
MAX_REASON_LEN = 80

_MENTION_RE = re.compile(r"<(?:@[!&]?|#|a?:\w+:)\d*>?|@(?:everyone|here)", re.IGNORECASE)  # <@123> <@&1> <#1> <:emoji:1>
_COMMON_TLDS = ("com|net|org|io|gg|co|tw|cn|jp|me|ly|xyz|info|app|dev|ai|tv|link|top|club|"
                "shop|store|site|online|cc|to|us|uk|de|fr")
_URL_RE = re.compile(
    r"(?:https?://|www\.)\S+"                                          # 有 http:// 或 www.
    r"|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}/\S*"                           # 網域加路徑，例如 discord.gg/abc（1.5L/瓶 的最後一段有數字，不會中）
    rf"|\b[\w-]+(?:\.[\w-]+)*\.(?:{_COMMON_TLDS})\b",                  # 沒有路徑的常見網域，例如 evil.com
    re.IGNORECASE)
_MARKDOWN_RE = re.compile(r"[`*_~>|<@]")  # Markdown 符號，另外連單獨的 < 和 @ 也一起去掉
_TRAILING_PUNCT = " 　。.!！?？、,，;；:：…~～"


def clean_model_text(text: object, max_len: int = MAX_TEXT_LEN, *, strip_trailing_punct: bool = False) -> str:
    """模型給的文字，貼進回覆或寫進紀錄前先清洗。清完是空的就回傳空字串。

    去掉換行、Discord 提及格式、網址、Markdown 符號，合併空白，超過 max_len 就截斷。
    strip_trailing_punct=True（說明文字用）時，結尾標點也去掉，由範本自己加句號，
    不然會出現「。。」；品名這類文字不去掉結尾標點。
    """
    if not isinstance(text, str):
        return ""
    text = _MENTION_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    text = _MARKDOWN_RE.sub("", text)
    text = clean_text(text, 10_000)  # 去控制字元與換行、合併空白（先不截斷，等標點處理完）
    if strip_trailing_punct:
        return text.strip(_TRAILING_PUNCT)[:max_len].rstrip(_TRAILING_PUNCT)
    return text[:max_len].strip()


def clean_reason(text: object, default: str) -> str:
    """模型說「看到什麼／為什麼看不清楚」的文字。限 80 字；清完是空的就用預設說明。"""
    return clean_model_text(text, MAX_REASON_LEN, strip_trailing_punct=True) or default
# ==== 防護 2 結束 ====


@dataclass(frozen=True)
class Extraction:
    status: str            # ok / unreadable / not_label / multiple_items
    reason: str            # 非 ok 時給使用者看的說明
    name: str = ""
    brand: str = ""
    price: float = 0.0
    amount: float = 0.0
    unit: UnitInfo | None = None
    store: str = ""
    category: str = ""


def validate_extraction(data: object, known_categories: list[str]) -> Extraction:
    """驗證 claude 回的固定格式。不合格丟 ValidationError（訊息只有「欄位：規則」，不含 claude 的原文）。"""
    if not isinstance(data, dict):
        raise ValidationError("辨識結果：不是固定格式")
    status = data.get("status")
    if status not in STATUSES:
        raise ValidationError("status：不在允許的值裡")
    if status != "ok":
        reason = clean_reason(data.get("reason"), _DEFAULT_REASON[status])
        return Extraction(status=status, reason=reason)

    name = clean_model_text(data.get("name"))
    if not name:
        raise ValidationError("品名：清洗後是空的")
    unit = normalize_unit(data.get("unit"))
    if unit is None:
        raise ValidationError("單位：不在認得的清單裡")
    return Extraction(
        status="ok",
        reason="",
        name=name,
        brand=clean_model_text(data.get("brand")),
        price=validate_price(data.get("price")),
        amount=validate_amount(data.get("amount")),
        unit=unit,
        store=clean_model_text(data.get("store")),
        category=validate_category(data.get("category"), known_categories, name),
    )
