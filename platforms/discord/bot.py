"""
Discord Bot 适配器
通过 discord.py 桥接用户指令到 SillyTavern
"""
import asyncio
import os

import discord
from discord.ext import commands

import core
from core import admin

PLATFORM = "discord"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class RelayBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("platforms.discord.st_commands")
        await self.load_extension("platforms.discord.admin_commands")
        try:
            synced = await self.tree.sync()
            print(f"[discord] 已同步 {len(synced)} 条斜杠命令", flush=True)
        except Exception as e:
            print(f"[discord] 命令同步失败: {e}", flush=True)

    async def on_ready(self):
        print(f"[discord] 已登录: {self.user} (ID: {self.user.id})", flush=True)
        print("[discord] 正在启动浏览器...", flush=True)
        await core.init_browser()
        print("[discord] 就绪！", flush=True)

    async def close(self):
        if core.get_page() is not None:
            print("[discord] 正在关闭浏览器...", flush=True)
            await core.close_browser()
        await super().close()


async def run_discord_bot():
    token = core.config.discord.bot_token
    if not token:
        print("[discord] 错误: config.yaml 中未配置 bot_token，跳过启动", flush=True)
        return

    admin.init()
    print("[discord] 正在启动...", flush=True)
    bot = RelayBot()

    async with bot:
        await bot.start(token)
