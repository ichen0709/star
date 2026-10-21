"""輸入與輸出的驗證與清洗。

防護 3（檔名與路徑清洗）在這個檔案。
"""

import math
import re
from datetime import datetime
from pathlib import Path

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
_CATEGORY_RE = re.compile(r"[一-鿿A-Za-z0-9]{1,%d}" % MAX_CATEGORY_LEN)


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


def validate_category(raw: object, known: list[str]) -> str:
    """類別必須是這個人用過的名稱，或符合規則的新名稱。"""
    cleaned = clean_text(raw, MAX_CATEGORY_LEN * 2)
    if not cleaned:
        raise ValidationError("類別是空的")
    for name in known:
        if cleaned.casefold() == name.casefold():
            return name
    if not _CATEGORY_RE.fullmatch(cleaned):
        raise ValidationError("類別名稱不符合規則（只能是中英文與數字，最多 20 字）")
    return cleaned


def _validate_positive_number(raw: object, upper: float, label: str) -> float:
    # bool 是 int 的子類別，要先排除
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValidationError(f"{label}不是數字")
    value = float(raw)
    if not math.isfinite(value) or value <= 0 or value > upper:
        raise ValidationError(f"{label}超出合理範圍")
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
