"""Discord 收發、篩選、限流、佇列。

只聽 CHANNEL_ID 指定的頻道；工作排進同一個佇列，一次只處理一件。
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import discord

from . import replies
from .compare import compare
from .claude_client import ClaudeError, extract_from_image
from .config import Settings
from .store import RecordStore, StoreError, load_state, save_state
from .units import unit_price
from .validate import ValidationError, check_image_bytes, validate_extraction

log = logging.getLogger("unit_price_agent")

MAX_IMAGES_PER_MESSAGE = 5
WINDOW_SECONDS = 3600
TAIPEI = ZoneInfo("Asia/Taipei")
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
    status: discord.Message | None = None  # 那張照片的「處理中…」訊息；處理完會被編輯成結果


class PriceBot(discord.Client):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True  # 要在 Developer Portal 打開 Message Content Intent
        # 預設所有回覆都不能 @ 任何人（防護：其他保護）
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.limiter = RateLimiter(settings.data_dir / "state.json")
        self.store = RecordStore(settings.data_dir)
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

        for number, att in enumerate(images, start=1):
            status = await self._reply(message, replies.processing(number, len(images)))
            await self.queue.put(Job(message, att, number, len(images), status))

    # ---- 佇列的 worker：一次處理一件 ----
    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            record_id = None
            try:
                text, record_id = await self._process_job(job)
            except Exception as exc:  # 一件出錯不能讓 worker 停掉
                log.error("處理時發生未預期的錯誤：%s", type(exc).__name__)
                text = replies.failure()
            final = await self._deliver(job, replies.prefix(job.number, job.total) + text)
            stored_id = job.status.id if job.status is not None else None
            if record_id is not None and final is not None and final.id != stored_id:
                try:  # 改成送了新訊息，回覆訊息 ID 跟著換（修正時靠它找到這一筆）
                    await asyncio.to_thread(self.store.set_reply_id, record_id, final.id)
                except StoreError as exc:
                    log.error("記回覆訊息 ID 失敗：%s", exc)
            self.queue.task_done()

    async def _deliver(self, job: Job, content: str) -> discord.Message | None:
        """把結果編輯進「處理中…」那則訊息；編輯失敗就改送新的回覆。回傳最後留下的那則訊息。"""
        if job.status is not None:
            try:
                return await job.status.edit(content=content,
                                             allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as exc:
                log.warning("編輯「處理中…」訊息失敗（HTTP %s），改送一則新的回覆", exc.status)
        return await self._reply(job.message, content)

    async def _process(self, job: Job) -> str:
        return (await self._process_job(job))[0]

    async def _process_job(self, job: Job) -> tuple[str, int | None]:
        """回傳（回覆文字, 新紀錄編號或 None）。讀寫 Excel 都在這裡，也就是都在 worker 裡。"""
        settings = self.settings
        try:
            if job.attachment.size > settings.max_image_mb * 1024 * 1024:
                raise ValidationError("圖片太大")
            data = await job.attachment.read()
            ext = check_image_bytes(data, settings.max_image_mb)
        except ValidationError:
            return replies.bad_image(settings.max_image_mb), None
        except discord.HTTPException:
            return replies.failure(), None

        user = job.message.author
        try:
            known = await asyncio.to_thread(self.store.user_categories, user.id)
        except StoreError as exc:
            log.error("讀紀錄失敗：%s", exc)
            return replies.failure(), None
        try:
            raw = await extract_from_image(settings, data, ext, known)
        except ClaudeError as exc:
            log.error("claude 處理失敗：%s", type(exc).__name__)
            return replies.failure(), None
        try:
            extraction = validate_extraction(raw, known)
        except ValidationError as exc:  # 訊息只有「欄位：規則」，不含 claude 的原文
            log.warning("辨識結果驗證失敗：%s", exc)
            return replies.unreasonable(), None
        if extraction.status != "ok":
            return replies.for_extraction(extraction, None), None

        price = unit_price(extraction.price, extraction.amount, extraction.unit)
        try:
            history = await asyncio.to_thread(self.store.user_records, user.id)
            result = compare(history, user_id=str(user.id), category=extraction.category,
                             kind=price.kind, value=price.value)
            record = await asyncio.to_thread(
                self.store.add_record, when=datetime.now(TAIPEI).replace(tzinfo=None),
                user_id=user.id, user_name=getattr(user, "display_name", "") or str(user.id),
                category=extraction.category, name=extraction.name, brand=extraction.brand,
                price=extraction.price, amount=extraction.amount, unit=extraction.unit.unit,
                unit_price=price.value, store=extraction.store, photo_bytes=data, photo_ext=ext,
                reply_id=job.status.id if job.status is not None else "")
        except StoreError as exc:  # 例如 Excel 開著鎖住檔案；照片和半成品已在 store 裡清掉
            log.error("存檔失敗：%s", exc)
            return replies.failure(), None
        return replies.for_extraction(extraction, price, result), record.record_id

    async def _reply(self, message: discord.Message, text: str) -> discord.Message | None:
        try:
            return await message.reply(text, mention_author=False)
        except discord.Forbidden:
            log.error("bot 在這個頻道沒有傳送訊息的權限，請檢查 Send Messages 權限")
        except discord.HTTPException as exc:
            log.error("傳送回覆失敗：HTTP %s", exc.status)
        return None
