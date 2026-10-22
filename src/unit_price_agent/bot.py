"""Discord 收發、篩選、限流、佇列。

只聽 CHANNEL_ID 指定的頻道；工作排進同一個佇列，一次只處理一件。
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

import discord

from . import replies, weekly
from .claude_client import ClaudeError, extract_from_image, interpret_text
from .compare import compare
from .config import Settings
from .store import RecordStore, StoreError, load_state, save_state
from .intents import FIELD_LABELS, apply_fix, parse_intent, select_for_query
from .units import normalize_unit, unit_price
from .validate import ValidationError, check_image_bytes, validate_extraction

log = logging.getLogger("unit_price_agent")

MAX_IMAGES_PER_MESSAGE = 5
WINDOW_SECONDS = 3600
TAIPEI = ZoneInfo("Asia/Taipei")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
# 白話訊息的粗篩：回覆 bot、@ bot、或含這些字眼才會呼叫 claude -p，其他聊天直接忽略、不花額度
KEYWORD_RE = re.compile("紀錄|記錄|記過|最近|查|列|改|修正|更正")
WEEKLY_COMMAND = "週報"  # 完全比對才觸發，不經過 claude
MAX_TEXT_CHARS = 300
STATE_WEEKLY_LAST = "weekly_last_due"
SCHEDULER_INTERVAL_SECONDS = 60


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

    def get(self, key: str):
        return self.state.get(key)

    def set(self, key: str, value) -> None:
        self.state[key] = value
        save_state(self.state_path, self.state)

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


@dataclass
class TextJob:
    """一句白話（修正、查詢）。reference_id 是被回覆的 bot 訊息 ID，沒有回覆 bot 就是 None。"""
    message: discord.Message
    text: str
    mentioned: bool
    reference_id: int | None
    status: discord.Message | None = None


@dataclass
class WeeklyCommandJob:
    """有人輸入「週報」：立刻發他本人這週的內容。"""
    message: discord.Message
    status: discord.Message | None = None


@dataclass
class ScheduledWeeklyJob:
    """排程時間到了：每個這週有記東西的人各發一則並 @。due 是這次排程的時間。"""
    due: datetime


def taipei_now() -> datetime:
    return datetime.now(TAIPEI).replace(tzinfo=None)


class PriceBot(discord.Client):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True  # 要在 Developer Portal 打開 Message Content Intent
        # 預設所有回覆都不能 @ 任何人（防護：其他保護）
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.queue: asyncio.Queue = asyncio.Queue()
        self.limiter = RateLimiter(settings.data_dir / "state.json")
        self.store = RecordStore(settings.data_dir)
        self.now: Callable[[], datetime] = taipei_now  # 台北時間（不帶時區），測試時可換掉
        self.weekly_pending = False  # 週報已經排進佇列、還沒做完
        self.fatal: str | None = None  # 啟動後發現的致命問題，main 會印出來並結束

    async def setup_hook(self) -> None:
        self.worker_task = asyncio.create_task(self._worker())
        self.scheduler_task = asyncio.create_task(self._scheduler())

    async def on_ready(self) -> None:
        if self.get_channel(self.settings.channel_id) is None:
            self.fatal = ("找不到 CHANNEL_ID 指定的頻道。請確認 bot 已經被邀進那個 Server，"
                          "而且看得到那個頻道（見 docs/discord-bot-setup.md 第 5、7 節）")
            await self.close()
            return
        log.info("已連線，開始監聽指定頻道。按 Ctrl + C 停止。")

    async def close(self) -> None:
        for name in ("worker_task", "scheduler_task"):
            task = getattr(self, name, None)
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
            await self._on_text(message)
            return

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

    async def _on_text(self, message: discord.Message) -> None:
        """沒有圖片的訊息：先粗篩，只有該處理的才排進佇列（同一條佇列）。"""
        bot_id = getattr(self.user, "id", None)
        mentioned = any(m.id == bot_id for m in getattr(message, "mentions", []))
        ref = getattr(message, "reference", None)
        replied = getattr(ref, "resolved", None)
        reply_to_bot = bot_id is not None and getattr(getattr(replied, "author", None), "id", None) == bot_id
        text = re.sub(rf"<@!?{bot_id}>", " ", message.content or "").strip()
        text = " ".join(text.split())[:MAX_TEXT_CHARS]

        if text == WEEKLY_COMMAND:
            status = await self._reply(message, replies.processing(1, 1))
            await self.queue.put(WeeklyCommandJob(message, status))
            return
        if not (mentioned or reply_to_bot or KEYWORD_RE.search(text)):
            return  # 一般聊天：不回應、不花額度
        if not text:  # 只有 @bot，沒說什麼
            await self._reply(message, replies.help_text())
            return
        granted = self.limiter.consume(
            "text", message.author.id, 1, self.settings.max_text_cmds_per_user_per_hour)
        if not granted:
            await self._reply(message, replies.rate_limited_text())
            return
        status = await self._reply(message, replies.processing(1, 1))
        await self.queue.put(TextJob(message, text, mentioned, ref.message_id if reply_to_bot else None, status))

    # ---- 排程：每分鐘看一次，該發週報就丟一件工作進佇列 ----
    async def _scheduler(self) -> None:
        await self.wait_until_ready()
        while True:
            self.check_weekly_schedule()
            await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)

    def check_weekly_schedule(self) -> None:
        s = self.settings
        due = weekly.latest_due(self.now(), s.weekly_weekday, s.weekly_hour, s.weekly_minute)
        raw = self.limiter.get(STATE_WEEKLY_LAST)
        try:
            last = datetime.fromisoformat(raw) if raw else None
        except ValueError:
            last = None
        if last is None:  # 第一次啟動：把之前的排程當作已經過了，不補發
            self.limiter.set(STATE_WEEKLY_LAST, due.isoformat())
        elif last < due and not self.weekly_pending:  # 錯過或時間到了：只補最近這一次，不補多週
            self.weekly_pending = True
            self.queue.put_nowait(ScheduledWeeklyJob(due))

    # ---- 佇列的 worker：一次處理一件 ----
    async def _worker(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                if isinstance(job, ScheduledWeeklyJob):
                    await self._handle_scheduled_weekly(job)
                elif isinstance(job, WeeklyCommandJob):
                    await self._finish(job, await self._weekly_command(job))
                elif isinstance(job, TextJob):
                    await self._finish(job, await self._text_command(job))
                else:
                    await self._handle_photo(job)
            except Exception as exc:  # 一件出錯不能讓 worker 停掉
                log.error("處理時發生未預期的錯誤：%s", type(exc).__name__)
            finally:
                self.queue.task_done()

    async def _finish(self, job, text: str | None) -> None:
        """白話工作做完：編輯「處理中…」成結果；沒什麼好說的（text 是 None）就把它刪掉。"""
        if text is not None:
            await self._deliver(job, text)
        elif job.status is not None:
            try:
                await job.status.delete()
            except discord.HTTPException:
                pass

    async def _handle_photo(self, job: Job) -> None:
        record_id = None
        try:
            text, record_id = await self._process_job(job)
        except Exception as exc:
            log.error("處理照片時發生未預期的錯誤：%s", type(exc).__name__)
            text = replies.failure()
        final = await self._deliver(job, replies.prefix(job.number, job.total) + text)
        stored_id = job.status.id if job.status is not None else None
        if record_id is not None and final is not None and final.id != stored_id:
            try:  # 改成送了新訊息，回覆訊息 ID 跟著換（修正時靠它找到這一筆）
                await asyncio.to_thread(self.store.set_reply_id, record_id, final.id)
            except StoreError as exc:
                log.error("記回覆訊息 ID 失敗：%s", exc)

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
                self.store.add_record, when=self.now(),
                user_id=user.id, user_name=getattr(user, "display_name", "") or str(user.id),
                category=extraction.category, name=extraction.name, brand=extraction.brand,
                price=extraction.price, amount=extraction.amount, unit=extraction.unit.unit,
                unit_price=price.value, store=extraction.store, photo_bytes=data, photo_ext=ext,
                reply_id=job.status.id if job.status is not None else "")
        except StoreError as exc:  # 例如 Excel 開著鎖住檔案；照片和半成品已在 store 裡清掉
            log.error("存檔失敗：%s", exc)
            return replies.failure(), None
        return replies.for_extraction(extraction, price, result), record.record_id

    # ---- 修正與查詢（白話）----
    async def _text_command(self, job: TextJob) -> str | None:
        """claude 只把白話轉成固定格式；驗證與執行都在這裡（程式），而且用上傳者的 Discord ID 篩。"""
        user = job.message.author
        try:
            known = await asyncio.to_thread(self.store.user_categories, user.id)
            raw = await interpret_text(self.settings, job.text, known)
            try:
                intent = parse_intent(raw)
            except ValidationError as exc:
                log.warning("白話轉格式的結果驗證失敗：%s", exc)
                intent = None
            if intent is None or intent.kind == "none":
                return replies.help_text() if (job.mentioned or job.reference_id) else None
            if intent.kind == "query":
                mine = await asyncio.to_thread(self.store.user_records, user.id)
                shown, more, category = select_for_query(mine, intent.category, intent.limit, known)
                return replies.query_result(shown, more, category)
            return await self._fix(job, intent, known)
        except ClaudeError as exc:
            log.error("claude 處理失敗：%s", type(exc).__name__)
            return replies.failure()
        except StoreError as exc:
            log.error("讀寫紀錄失敗：%s", exc)
            return replies.failure()

    async def _fix(self, job: TextJob, intent, known: list[str]) -> str:
        user = job.message.author
        if job.reference_id is None:
            return replies.fix_need_reply()
        record = await asyncio.to_thread(self.store.find_by_reply_id, job.reference_id)
        if record is None:
            return replies.fix_not_a_record()
        if record.user_id != str(user.id):  # 只能改本人的紀錄
            return replies.fix_not_yours()
        try:
            changes = apply_fix(record, intent.field, intent.value, known)
        except ValidationError as exc:
            log.warning("修正的新值驗證失敗：%s", exc)
            return replies.fix_rejected(FIELD_LABELS[intent.field])
        updated = await asyncio.to_thread(self.store.update_record, record.record_id, **changes)
        history = await asyncio.to_thread(self.store.user_records, user.id)
        kind = normalize_unit(updated.unit).kind
        result = compare(history, user_id=str(user.id), category=updated.category, kind=kind,
                         value=updated.unit_price, exclude_id=updated.record_id)
        return replies.fixed(intent.field, updated, result)

    # ---- 週報 ----
    async def _weekly_command(self, job: WeeklyCommandJob) -> str:
        try:
            mine = await asyncio.to_thread(self.store.user_records, job.message.author.id)
        except StoreError as exc:
            log.error("讀紀錄失敗：%s", exc)
            return replies.failure()
        report = weekly.build_report(mine, self.now())
        return replies.weekly(report) if report else replies.weekly_empty()

    async def _handle_scheduled_weekly(self, job: ScheduledWeeklyJob) -> None:
        """每個這週有記東西的人各發一則並 @。這是唯一允許 @ 人的地方。"""
        try:
            records = await asyncio.to_thread(self.store.all_records)
            channel = self.get_channel(self.settings.channel_id)
            if channel is None:
                log.error("週報：找不到頻道，沒有發送")
                return
            now = self.now()
            by_user: dict[str, list] = {}
            for r in records:
                by_user.setdefault(r.user_id, []).append(r)
            for user_id, mine in by_user.items():
                report = weekly.build_report(mine, now)
                if report is None:
                    continue  # 這週沒記東西的人不發
                # 只允許 @ 這一個人；AllowedMentions 的預設是全部允許，所以其他都要明確關掉
                mention = discord.AllowedMentions(everyone=False, roles=False, replied_user=False,
                                                  users=[discord.Object(id=int(user_id))])
                try:
                    await channel.send(f"<@{int(user_id)}>\n{replies.weekly(report)}", allowed_mentions=mention)
                except discord.HTTPException as exc:
                    log.error("週報傳送失敗：HTTP %s", exc.status)
        except StoreError as exc:
            log.error("週報讀紀錄失敗：%s", exc)
        finally:  # 不管成功與否都記下來，避免每分鐘重送
            self.limiter.set(STATE_WEEKLY_LAST, job.due.isoformat())
            self.weekly_pending = False

    async def _reply(self, message: discord.Message, text: str) -> discord.Message | None:
        try:
            return await message.reply(text, mention_author=False)
        except discord.Forbidden:
            log.error("bot 在這個頻道沒有傳送訊息的權限，請檢查 Send Messages 權限")
        except discord.HTTPException as exc:
            log.error("傳送回覆失敗：HTTP %s", exc.status)
        return None
