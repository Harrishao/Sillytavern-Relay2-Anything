"""
无头浏览器管理模块
负责 Playwright Chromium 的启动、关闭、刷新及页面状态管理
"""
import asyncio
import atexit

from playwright.async_api import async_playwright
from .config import config

_playwright = None
_browser = None
_page = None


def get_page():
    return _page


async def init_browser():
    global _playwright, _browser, _page
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=config.st.headless)
    ctx = await _browser.new_context(
        viewport={"width": config.st.viewport_width + 80, "height": 800}
    )
    _page = await ctx.new_page()
    await _page.goto(config.st.url, wait_until="domcontentloaded")
    await _page.wait_for_function(
        "() => window.SillyTavern && window.SillyTavern.getContext",
        timeout=30000,
    )
    print(f"[core] 浏览器已启动, ST已就绪, viewport={config.st.viewport_width + 80}x800", flush=True)


async def close_browser():
    global _browser, _playwright, _page
    if _page:
        try:
            await _page.close()
        except Exception:
            pass
        _page = None
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
    print("[core] 浏览器已关闭", flush=True)


def _cleanup():
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(close_browser())
        else:
            loop.run_until_complete(close_browser())
    except Exception:
        pass


atexit.register(_cleanup)


async def refresh_page() -> bool:
    try:
        await _page.reload(wait_until="domcontentloaded")
        await _page.wait_for_function(
            "() => window.SillyTavern && window.SillyTavern.getContext",
            timeout=30000,
        )
        await _page.wait_for_timeout(config.st.refresh_delay * 1000)
        print("[core] 页面已刷新, ST已就绪", flush=True)
        return True
    except Exception as e:
        print(f"[core] 页面刷新失败: {e}", flush=True)
        return False


async def dismiss_toasts():
    try:
        await _page.evaluate(
            "() => { if (typeof toastr !== 'undefined') toastr.clear(); }"
        )
    except Exception:
        pass
