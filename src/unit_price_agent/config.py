"""從 .env 讀設定。

錯誤訊息只講設定的名稱，不講值；Settings 的 repr 也不會顯示 token。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

WEEKDAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


class ConfigError(Exception):
    """設定缺少或格式不對。訊息只含設定名稱。"""


@dataclass(frozen=True)
class Settings:
    discord_token: str = field(repr=False)
    channel_id: int
    claude_model: str
    data_dir: Path
    max_photos_per_user_per_hour: int = 30
    max_text_cmds_per_user_per_hour: int = 60
    claude_timeout_seconds: int = 90
    max_image_mb: int = 10
    weekly_weekday: int = 6  # 0=週一 … 6=週日
    weekly_hour: int = 20
    weekly_minute: int = 0


def _parse_weekly(raw: str) -> tuple[int, int, int]:
    """'SUN 20:00' → (6, 20, 0)。格式不對就丟 ConfigError（不帶值）。"""
    try:
        day, hhmm = raw.split()
        hour, minute = hhmm.split(":")
        weekday = WEEKDAYS[day.upper()]
        hour_i, minute_i = int(hour), int(minute)
        if not (0 <= hour_i < 24 and 0 <= minute_i < 60):
            raise ValueError
    except (ValueError, KeyError):
        raise ConfigError("WEEKLY_REPORT_TIME 格式不對，要像 SUN 20:00（MON～SUN + 24 小時制時間）") from None
    return weekday, hour_i, minute_i


def load_settings(env_path: Path | None = None, *, need_discord: bool = True) -> Settings:
    """讀 .env（和環境變數，環境變數優先）。缺必要設定時丟 ConfigError。

    need_discord=False 時不要求 DISCORD_TOKEN 和 CHANNEL_ID（階段 1 的自我檢查不連 Discord）。
    相對路徑（DATA_DIR）以 .env 所在的資料夾為基準。
    """
    env_path = env_path or Path.cwd() / ".env"
    file_values = dotenv_values(env_path) if env_path.exists() else {}

    def get(name: str) -> str | None:
        value = os.environ.get(name) or file_values.get(name)
        value = value.strip() if value else None
        return value or None

    required = ["CLAUDE_MODEL", "DATA_DIR"]
    if need_discord:
        required = ["DISCORD_TOKEN", "CHANNEL_ID", *required]
    missing = [name for name in required if get(name) is None]
    if missing:
        where = ".env" if env_path.exists() else ".env（找不到這個檔案）"
        raise ConfigError(f"{where} 缺少這些設定：{', '.join(missing)}")

    def get_int(name: str, default: int, minimum: int = 1) -> int:
        raw = get(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise ConfigError(f"{name} 必須是整數") from None
        if value < minimum:
            raise ConfigError(f"{name} 必須大於或等於 {minimum}")
        return value

    channel_id = get_int("CHANNEL_ID", 0) if need_discord else 0
    weekday, hour, minute = _parse_weekly(get("WEEKLY_REPORT_TIME") or "SUN 20:00")
    data_dir = Path(get("DATA_DIR"))
    if not data_dir.is_absolute():
        data_dir = env_path.resolve().parent / data_dir

    return Settings(
        discord_token=get("DISCORD_TOKEN") or "",
        channel_id=channel_id,
        claude_model=get("CLAUDE_MODEL"),
        data_dir=data_dir.resolve(),
        max_photos_per_user_per_hour=get_int("MAX_PHOTOS_PER_USER_PER_HOUR", 30),
        max_text_cmds_per_user_per_hour=get_int("MAX_TEXT_CMDS_PER_USER_PER_HOUR", 60),
        claude_timeout_seconds=get_int("CLAUDE_TIMEOUT_SECONDS", 90),
        max_image_mb=get_int("MAX_IMAGE_MB", 10),
        weekly_weekday=weekday,
        weekly_hour=hour,
        weekly_minute=minute,
    )
