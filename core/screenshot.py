"""
截图模块
负责截取 SillyTavern 消息区域的截图及全页截图
"""
import os
import time

from .config import SCREENSHOT_DIR
from .browser import get_page, dismiss_toasts


def _make_filename(prefix: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}.png"


async def capture_screenshot(output_dir: str = None) -> str | None:
    page = get_page()
    if output_dir is None:
        output_dir = SCREENSHOT_DIR
    os.makedirs(output_dir, exist_ok=True)

    filename = _make_filename("msg")
    output_path = os.path.join(output_dir, filename)

    await dismiss_toasts()

    try:
        el = page.locator(".mes").last
        await el.wait_for(state="visible", timeout=5000)

        box = await el.bounding_box()
        if box:
            viewport = page.viewport_size
            original_height = viewport["height"]
            original_width = viewport["width"]

            needed_height = int(box["height"] + 200)
            if needed_height > original_height:
                try:
                    await page.set_viewport_size(
                        {"width": original_width, "height": needed_height}
                    )
                    await page.wait_for_timeout(300)
                except Exception:
                    pass

            try:
                await el.scroll_into_view_if_needed()
                await page.wait_for_timeout(200)
            except Exception:
                pass

            await el.screenshot(path=output_path, type="png")
            print(f"[core] 消息截图已保存: {output_path} (高度={box['height']})", flush=True)

            try:
                await page.set_viewport_size(
                    {"width": original_width, "height": original_height}
                )
            except Exception:
                pass

            return output_path
        else:
            await el.screenshot(path=output_path, type="png")
            print(f"[core] 消息截图已保存: {output_path}", flush=True)
            return output_path

    except Exception as e:
        print(f"[core] .mes截图失败({e})，回退到.mes_text", flush=True)

    try:
        el = page.locator(".mes_text").last
        await el.wait_for(state="visible", timeout=5000)

        box = await el.bounding_box()
        if box:
            viewport = page.viewport_size
            original_height = viewport["height"]
            original_width = viewport["width"]
            needed_height = int(box["height"] + 200)
            if needed_height > original_height:
                await page.set_viewport_size(
                    {"width": original_width, "height": needed_height}
                )
                await page.wait_for_timeout(300)
            await el.scroll_into_view_if_needed()
            await page.wait_for_timeout(200)

        await el.screenshot(path=output_path, type="png")
        print(f"[core] 消息文本截图已保存: {output_path}", flush=True)

        try:
            viewport = page.viewport_size
            await page.set_viewport_size({"width": viewport["width"], "height": 800})
        except Exception:
            pass

        return output_path
    except Exception as e2:
        print(f"[core] .mes_text截图也失败({e2})，回退到全页截图", flush=True)

    try:
        await page.screenshot(path=output_path, full_page=True)
        print(f"[core] 全页截图已保存: {output_path}", flush=True)
        return output_path
    except Exception as e2:
        print(f"[core] 截图完全失败: {e2}", flush=True)
        return None


async def capture_full_screenshot(output_dir: str = None) -> str | None:
    page = get_page()
    if output_dir is None:
        output_dir = SCREENSHOT_DIR
    os.makedirs(output_dir, exist_ok=True)

    filename = _make_filename("full")
    output_path = os.path.join(output_dir, filename)

    await dismiss_toasts()

    try:
        await page.screenshot(path=output_path, full_page=True)
        print(f"[core] 全页截图已保存: {output_path}", flush=True)
        return output_path
    except Exception as e:
        print(f"[core] 全页截图失败: {e}", flush=True)
        return None
