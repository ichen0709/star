"""啟動入口：uv run python -m unit_price_agent

缺設定、token 不對、沒打開 Message Content Intent 時，印出清楚的中文訊息並結束。
任何訊息都不會包含 token 或其他設定的值。
"""

import logging
import shutil
import sys

import discord

from .bot import PriceBot
from .claude_client import cleanup_stale_workdirs
from .config import ConfigError, load_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.ERROR)  # 去掉「沒裝語音套件」的提示，我們不用語音

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"設定有問題：{exc}\n請看 README 的「設定 .env」，名稱見 .env.example。")
        return 2

    if shutil.which("claude") is None:
        print("找不到 claude 指令。請先安裝 Claude Code 並登入，確認終端機打 claude --version 有反應。")
        return 2

    cleanup_stale_workdirs()
    bot = PriceBot(settings)
    try:
        bot.run(settings.discord_token, log_handler=None)
    except discord.LoginFailure:
        print("Discord 拒絕登入：DISCORD_TOKEN 不正確（或已經被重設）。\n"
              "請到 Developer Portal → Bot → Reset Token 取得新的，填進 .env 的 DISCORD_TOKEN。")
        return 3
    except discord.PrivilegedIntentsRequired:
        print("Discord 說這個 bot 沒有打開 Message Content Intent。\n"
              "請到 Developer Portal → Bot → Privileged Gateway Intents 打開 Message Content Intent，"
              "按 Save Changes，再重新啟動。")
        return 3
    except KeyboardInterrupt:
        pass

    if bot.fatal:
        print(bot.fatal)
        return 3
    print("已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
