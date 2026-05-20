"""
SillyTavern Relay2 Anything — 多平台入口
统一管理 Telegram / Discord / NapCat(QQ) 三个聊天平台的 SillyTavern 中继
以及一个 Web 管理面板（负责平台启停）
"""
import asyncio
import sys

from core.config import config, reload_config
from core import admin as admin_mod


async def main():
    cfg = reload_config()
    admin_mod.init()

    # 初始化浏览器（必须在平台 Bot 启动之前，Web 面板 auto_start 时会启动 Bot）
    from core.browser import init_browser
    await init_browser()

    # 启动 Web 管理面板，auto_start=True 会自动启动 enabled 的平台
    from web.server import run_web
    try:
        await run_web(auto_start=True)
    except KeyboardInterrupt:
        print("[main] 收到中断信号，正在关闭...", flush=True)
    finally:
        from core.browser import close_browser
        await close_browser()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
