"""Discord 收發、篩選、限流、佇列。

只聽 CHANNEL_ID 指定的頻道；工作排進同一個佇列，一次只處理一件。
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import discord

from . import replies
from .claude_client import ClaudeError, extract_from_image
from .config import Settings
from .store import load_state, save_state
from .units import unit_price
from .validate import ValidationError, check_image_bytes, validate_extraction

log = logging.getLogger("unit_price_agent")

MAX_IMAGES_PER_MESSAGE = 5
WINDOW_SECONDS = 3600
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def pick_images(attachments) -> list:
    """從附件裡挑出像圖片的（看 content-type 或副檔名；真正的型別之後用檔案內容再查）。"""
    picked = []
    for att in attachments:
        content_type = (att.content_type or "").lower()
        if content_type.startswith("image/") or att.filename.lower().endswith(IMAGE_EXTS):
            picked.append(att)
    return picked


class RateLimiter:
    """每人每小時的使用上限（滑動視窗：從現在往前算一小時）。計數存在 state.json。"""

    def __init__(self, state_path: Path, clock: Callable[[], float] = time.time):
        self.state_path = state_path
        self.clock = clock
        self.state = load_state(state_path)

    def _hits(self, kind: str, user_id: int) -> list[float]:
        rate = self.state.setdefault("rate", {})
        return rate.setdefault(kind, {}).setdefault(str(user_id), [])

    def consume(self, kind: str, user_id: int, wanted: int, limit: int) -> int:
        """想用 wanted 次，回傳實際准許幾次（可能比 wanted 少），並記下來。"""
        now = self.clock()
        hits = [t for t in self._hits(kind, user_id) if now - t < WINDOW_SECONDS]
        granted = max(0, min(wanted, limit - len(hits)))
        hits.extend([now] * granted)
        self.state["rate"][kind][str(user_id)] = hits
        save_state(self.state_path, self.state)
        return granted


@dataclass
class Job:
    message: discord.Message
    attachment: discord.Attachment
    number: int
    total: int


class PriceBot(discord.Client):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True  # 要在 Developer Portal 打開 Message Content Intent
        # 預設所有回覆都不能 @ 任何人（防護：其他保護）
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.limiter = RateLimiter(settings.data_dir / "state.json")
        self.fatal: str | None = None  # 啟動後發現的致命問題，main 會印出來並結束

    async def setup_hook(self) -> None:
        self.worker_task = asyncio.create_task(self._worker())

    async def on_ready(self) -> None:
        if self.get_channel(self.settings.channel_id) is None:
            self.fatal = ("找不到 CHANNEL_ID 指定的頻道。請確認 bot 已經被邀進那個 Server，"
                          "而且看得到那個頻道（見 docs/discord-bot-setup.md 第 5、7 節）")
            await self.close()
            return
        log.info("已連線，開始監聽指定頻道。按 Ctrl + C 停止。")

    async def close(self) -> None:
        task = getattr(self, "worker_task", None)
        if task:
            task.cancel()
        await super().close()

    # ---- 收訊息 ----
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.channel.id != self.settings.channel_id:
            log.info("收到其他頻道的訊息（頻道 ID %s），已忽略。監聽的是 CHANNEL_ID 指定的頻道。",
                     message.channel.id)
            return
        images = pick_images(message.attachments)
        log.info("收到指定頻道的訊息：%d 張圖片", len(images))
        if not images:
            return  # 階段 2 只處理照片；查詢、修正、週報在階段 4

        if len(images) > MAX_IMAGES_PER_MESSAGE:
            images = images[:MAX_IMAGES_PER_MESSAGE]
            await self._reply(message, replies.too_many_images(MAX_IMAGES_PER_MESSAGE))

        granted = self.limiter.consume(
            "photo", message.author.id, len(images), self.settings.max_photos_per_user_per_hour)
        if granted < len(images):
            await self._reply(message, replies.rate_limited())
        images = images[:granted]
        if not images:
            return

        await self._reply(message, replies.processing(len(images)))
        for number, att in enumerate(images, start=1):
            await self.queue.put(Job(message, att, number, len(images)))

    # ---- 佇列的 worker：一次處理一件 ----
    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                text = await self._process(job)
            except Exception as exc:  # 一件出錯不能讓 worker 停掉
                log.error("處理時發生未預期的錯誤：%s", type(exc).__name__)
                text = replies.failure()
            await self._reply(job.message, replies.prefix(job.number, job.total) + text)
            self.queue.task_done()

    def known_categories(self, user_id: int) -> list[str]:
        return []  # 階段 3 改成這個人用過的類別

    async def _process(self, job: Job) -> str:
        settings = self.settings
        try:
            if job.attachment.size > settings.max_image_mb * 1024 * 1024:
                raise ValidationError("圖片太大")
            data = await job.attachment.read()
            ext = check_image_bytes(data, settings.max_image_mb)
        except ValidationError:
            return replies.bad_image(settings.max_image_mb)
        except discord.HTTPException:
            return replies.failure()

        known = self.known_categories(job.message.author.id)
        try:
            raw = await extract_from_image(settings, data, ext, known)
        except ClaudeError as exc:
            log.error("claude 處理失敗：%s", type(exc).__name__)
            return replies.failure()
        try:
            extraction = validate_extraction(raw, known)
        except ValidationError:
            return replies.unreasonable()

        price = None
        if extraction.status == "ok":
            price = unit_price(extraction.price, extraction.amount, extraction.unit)
        return replies.for_extraction(extraction, price)

    async def _reply(self, message: discord.Message, text: str) -> None:
        try:
            await message.reply(text, mention_author=False)
        except discord.Forbidden:
            log.error("bot 在這個頻道沒有傳送訊息的權限，請檢查 Send Messages 權限")
        except discord.HTTPException as exc:
            log.error("傳送回覆失敗：HTTP %s", exc.status)
