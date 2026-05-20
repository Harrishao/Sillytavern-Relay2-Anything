"""
管理员/白名单系统
两级权限：L1 管理员从统一 config 读取，L2 白名单持久化到 admin_whitelist.json
"""
import json
import os

from .config import config, BASE_DIR

_whitelist: set = set()
_whitelist_file = os.path.join(BASE_DIR, "admin_whitelist.json")


def init(admins: list = None):
    global _whitelist
    if os.path.isfile(_whitelist_file):
        try:
            with open(_whitelist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                _whitelist = set(data.get("whitelist", []))
        except Exception:
            _whitelist = set()


def _save():
    try:
        with open(_whitelist_file, "w", encoding="utf-8") as f:
            json.dump({"whitelist": list(_whitelist)}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[core] 保存白名单失败: {e}", flush=True)


def is_l1_admin(user_id, platform: str) -> bool:
    """检查是否为 L1 管理员"""
    platform_config = getattr(config, platform, None)
    if platform_config is None:
        return False
    return str(user_id) in [str(a) for a in platform_config.admins]


def is_whitelisted(user_id, platform: str) -> bool:
    """检查用户是否可使用 Bot"""
    platform_config = getattr(config, platform, None)
    if platform_config is None:
        return False
    if not platform_config.admin_mode:
        return True
    admins = [str(a) for a in platform_config.admins]
    return str(user_id) in admins or str(user_id) in _whitelist


def toggle_admin_mode(platform: str) -> bool:
    """切换指定平台的管理员模式"""
    platform_config = getattr(config, platform, None)
    if platform_config is None:
        return False
    platform_config.admin_mode = not platform_config.admin_mode
    return platform_config.admin_mode


def add_whitelist(user_id: str):
    _whitelist.add(str(user_id))
    _save()


def remove_whitelist(user_id: str):
    _whitelist.discard(str(user_id))
    _save()
