"""
SillyTavern 无头浏览器交互核心
平台无关，为各聊天平台机器人提供统一的 ST 操作接口
"""
import asyncio

from .config import config, reload_config, BASE_DIR
from .browser import init_browser, close_browser, refresh_page, get_page, dismiss_toasts
from .api import *
from .interaction import *
from .screenshot import capture_screenshot, capture_full_screenshot
from .admin import (
    init as admin_init,
    is_l1_admin,
    is_whitelisted,
    toggle_admin_mode,
    add_whitelist,
    remove_whitelist,
)

# 全局处理锁，防止多个平台同时操作浏览器
_processing_lock = False


def acquire_lock() -> bool:
    global _processing_lock
    if _processing_lock:
        return False
    _processing_lock = True
    return True


def release_lock():
    global _processing_lock
    _processing_lock = False


def is_locked() -> bool:
    return _processing_lock
