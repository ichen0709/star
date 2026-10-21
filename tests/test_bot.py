import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from unit_price_agent import bot as bot_module
from unit_price_agent.bot import WINDOW_SECONDS, RateLimiter, pick_images
from unit_price_agent.claude_client import ClaudeError, ClaudeTimeout
from unit_price_agent.config import Settings


def att(filename, content_type=None):
    return SimpleNamespace(filename=filename, content_type=content_type)


def test_pick_images_by_content_type_or_extension():
    items = [att("a.PNG", "image/png"), att("b.txt", "text/plain"), att("c.jpg"), att("d.pdf")]
    assert [a.filename for a in pick_images(items)] == ["a.PNG", "c.jpg"]


class Clock:
    now = 1_000_000.0

    def __call__(self):
        return self.now


def test_rate_limiter_allows_up_to_limit_then_refuses(tmp_path):
    clock = Clock()
    limiter = RateLimiter(tmp_path / "state.json", clock)
    assert limiter.consume("photo", 1, 2, limit=2) == 2
    assert limiter.consume("photo", 1, 1, limit=2) == 0
    assert limiter.consume("photo", 2, 1, limit=2) == 1  # 另一個人不受影響


def test_rate_limiter_grants_only_what_is_left(tmp_path):
    limiter = RateLimiter(tmp_path / "state.json", Clock())
    assert limiter.consume("photo", 1, 1, limit=3) == 1
    assert limiter.consume("photo", 1, 5, limit=3) == 2


def test_rate_limiter_is_a_sliding_window(tmp_path):
    clock = Clock()
    limiter = RateLimiter(tmp_path / "state.json", clock)
    assert limiter.consume("photo", 1, 2, limit=2) == 2
    clock.now += WINDOW_SECONDS - 1
    assert limiter.consume("photo", 1, 1, limit=2) == 0
    clock.now += 2
    assert limiter.consume("photo", 1, 2, limit=2) == 2


def test_rate_limiter_survives_restart(tmp_path):
    clock = Clock()
    path = tmp_path / "state.json"
    RateLimiter(path, clock).consume("photo", 1, 2, limit=2)
    assert RateLimiter(path, clock).consume("photo", 1, 1, limit=2) == 0


def test_rate_limiter_ignores_corrupt_state_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert RateLimiter(path, Clock()).consume("photo", 1, 1, limit=1) == 1


# ---- 用假的 Discord 訊息測 on_message 與 _process（不連 Discord、不呼叫 claude）----

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
OK = {"status": "ok", "reason": "", "name": "光泉鮮乳", "brand": "光泉", "price": 89, "amount": 936,
      "unit": "ml", "store": "", "category": "鮮奶"}


def make_settings(tmp_path, **kw):
    base = dict(discord_token="x", channel_id=42, claude_model="haiku", data_dir=tmp_path,
                max_photos_per_user_per_hour=30)
    base.update(kw)
    return Settings(**base)


def fake_att(data=PNG, filename="a.png", size=None):
    return SimpleNamespace(filename=filename, content_type="image/png",
                           size=len(data) if size is None else size, read=AsyncMock(return_value=data))


def fake_msg(attachments, channel_id=42, author_id=7, is_bot=False):
    return SimpleNamespace(author=SimpleNamespace(id=author_id, bot=is_bot),
                           channel=SimpleNamespace(id=channel_id),
                           attachments=attachments, reply=AsyncMock())


def replies_of(msg):
    return [call.args[0] for call in msg.reply.await_args_list]


def test_messages_outside_the_channel_or_from_bots_are_ignored(tmp_path):
    bot = bot_module.PriceBot(make_settings(tmp_path))
    for msg in (fake_msg([fake_att()], channel_id=1), fake_msg([fake_att()], is_bot=True),
                fake_msg([])):
        asyncio.run(bot.on_message(msg))
        msg.reply.assert_not_awaited()
    assert bot.queue.qsize() == 0


def test_more_than_five_images_only_five_are_queued(tmp_path):
    bot = bot_module.PriceBot(make_settings(tmp_path))
    msg = fake_msg([fake_att() for _ in range(6)])
    asyncio.run(bot.on_message(msg))
    texts = replies_of(msg)
    assert any("一次最多 5 張，其餘請分開傳" in t for t in texts)
    assert any("處理中" in t for t in texts)
    assert bot.queue.qsize() == 5


def test_over_the_hourly_limit_is_refused_with_a_reminder(tmp_path):
    bot = bot_module.PriceBot(make_settings(tmp_path, max_photos_per_user_per_hour=2))
    first = fake_msg([fake_att(), fake_att()])
    asyncio.run(bot.on_message(first))
    assert bot.queue.qsize() == 2
    third = fake_msg([fake_att()])
    asyncio.run(bot.on_message(third))
    assert replies_of(third) == ["這個小時傳太多了，請稍後再傳"]
    assert bot.queue.qsize() == 2


def job_for(bot, att):
    return bot_module.Job(fake_msg([att]), att, 1, 1)


def test_process_ok_replies_with_unit_price(tmp_path):
    bot = bot_module.PriceBot(make_settings(tmp_path))
    with patch.object(bot_module, "extract_from_image", AsyncMock(return_value=OK)):
        text = asyncio.run(bot._process(job_for(bot, fake_att())))
    assert "單價：每 100ml 9.51" in text and "類別：鮮奶" in text


@pytest.mark.parametrize("error", [ClaudeError("x"), ClaudeTimeout("x")])
def test_process_claude_failure_replies_with_retry_message(tmp_path, error):
    bot = bot_module.PriceBot(make_settings(tmp_path))
    with patch.object(bot_module, "extract_from_image", AsyncMock(side_effect=error)):
        text = asyncio.run(bot._process(job_for(bot, fake_att())))
    assert text == "這次處理失敗，請稍後再傳一次"


def test_process_non_image_content_is_refused_without_calling_claude(tmp_path):
    bot = bot_module.PriceBot(make_settings(tmp_path))
    extract = AsyncMock(return_value=OK)
    with patch.object(bot_module, "extract_from_image", extract):
        text = asyncio.run(bot._process(job_for(bot, fake_att(b"MZ not an image", "evil.png"))))
    assert "不是可以處理的圖片" in text
    extract.assert_not_awaited()


def test_process_oversized_image_is_refused_without_downloading(tmp_path):
    bot = bot_module.PriceBot(make_settings(tmp_path, max_image_mb=1))
    att = fake_att(size=5 * 1024 * 1024)
    text = asyncio.run(bot._process(job_for(bot, att)))
    assert "不是可以處理的圖片" in text
    att.read.assert_not_awaited()


def test_process_unreasonable_values_are_refused(tmp_path):
    bot = bot_module.PriceBot(make_settings(tmp_path))
    bad = dict(OK, price=-5)
    with patch.object(bot_module, "extract_from_image", AsyncMock(return_value=bad)):
        text = asyncio.run(bot._process(job_for(bot, fake_att())))
    assert "不合理" in text


def test_process_not_a_label_explains_and_asks_to_resend(tmp_path):
    bot = bot_module.PriceBot(make_settings(tmp_path))
    data = {"status": "not_label", "reason": "一隻貓"}
    with patch.object(bot_module, "extract_from_image", AsyncMock(return_value=data)):
        text = asyncio.run(bot._process(job_for(bot, fake_att())))
    assert "一隻貓" in text and "重傳" in text
