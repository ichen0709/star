import pytest

from unit_price_agent.config import ConfigError, load_settings

NAMES = ["DISCORD_TOKEN", "CHANNEL_ID", "CLAUDE_MODEL", "DATA_DIR",
         "MAX_PHOTOS_PER_USER_PER_HOUR", "MAX_TEXT_CMDS_PER_USER_PER_HOUR",
         "CLAUDE_TIMEOUT_SECONDS", "MAX_IMAGE_MB", "WEEKLY_REPORT_TIME"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def write_env(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_settings_are_reported_by_name_only(tmp_path):
    path = write_env(tmp_path, "DISCORD_TOKEN=\nCHANNEL_ID=\nCLAUDE_MODEL=haiku\nDATA_DIR=./data\n")
    with pytest.raises(ConfigError) as exc:
        load_settings(path)
    assert "DISCORD_TOKEN" in str(exc.value) and "CHANNEL_ID" in str(exc.value)
    assert "CLAUDE_MODEL" not in str(exc.value)


def test_missing_env_file_is_reported(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_settings(tmp_path / ".env", need_discord=False)
    assert "CLAUDE_MODEL" in str(exc.value)


def test_defaults_and_relative_data_dir(tmp_path):
    path = write_env(tmp_path, "DISCORD_TOKEN=abc\nCHANNEL_ID=123\nCLAUDE_MODEL=haiku\nDATA_DIR=./data\n")
    s = load_settings(path)
    assert s.channel_id == 123
    assert s.data_dir == (tmp_path / "data").resolve()
    assert (s.max_photos_per_user_per_hour, s.max_text_cmds_per_user_per_hour) == (30, 60)
    assert (s.weekly_weekday, s.weekly_hour, s.weekly_minute) == (6, 20, 0)


def test_token_is_never_in_repr_or_error_messages(tmp_path):
    secret = "SECRET-TOKEN-VALUE-1234567890"
    path = write_env(tmp_path, f"DISCORD_TOKEN={secret}\nCHANNEL_ID=notanumber\nCLAUDE_MODEL=haiku\nDATA_DIR=./d\n")
    with pytest.raises(ConfigError) as exc:
        load_settings(path)
    assert secret not in str(exc.value) and "notanumber" not in str(exc.value)
    path = write_env(tmp_path, f"DISCORD_TOKEN={secret}\nCHANNEL_ID=1\nCLAUDE_MODEL=haiku\nDATA_DIR=./d\n")
    assert secret not in repr(load_settings(path))


@pytest.mark.parametrize("bad", ["abc", "0", "-3"])
def test_bad_numbers_are_rejected(tmp_path, bad):
    path = write_env(tmp_path, f"CLAUDE_MODEL=haiku\nDATA_DIR=./d\nMAX_IMAGE_MB={bad}\n")
    with pytest.raises(ConfigError) as exc:
        load_settings(path, need_discord=False)
    assert "MAX_IMAGE_MB" in str(exc.value) and bad not in str(exc.value).replace("MAX_IMAGE_MB", "")


def test_weekly_time_parsing(tmp_path):
    path = write_env(tmp_path, "CLAUDE_MODEL=haiku\nDATA_DIR=./d\nWEEKLY_REPORT_TIME=MON 07:30\n")
    s = load_settings(path, need_discord=False)
    assert (s.weekly_weekday, s.weekly_hour, s.weekly_minute) == (0, 7, 30)
    path = write_env(tmp_path, "CLAUDE_MODEL=haiku\nDATA_DIR=./d\nWEEKLY_REPORT_TIME=someday\n")
    with pytest.raises(ConfigError):
        load_settings(path, need_discord=False)
