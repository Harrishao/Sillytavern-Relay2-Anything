"""Web 管理面板 — FastAPI + 日志轮询 + 平台生命周期管理"""
import asyncio
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import config, reload_config, save_config, BASE_DIR

WEB_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="ST Relay Manager", docs_url=None, redoc_url=None)

_static_dir = os.path.join(WEB_DIR, "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# ═══════════════════════════════════════════════════════════════
#  日志缓冲（不 monkey-patch stdout，由各模块自行 print 到控制台）
# ═══════════════════════════════════════════════════════════════

_log_buffer: list[str] = []
_log_buffer_max = 500


def _emit(level: str, message: str):
    """同时写控制台和内存缓冲"""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {message}"
    print(line, flush=True)
    _log_buffer.append(line)
    if len(_log_buffer) > _log_buffer_max:
        _log_buffer.pop(0)


def log(level: str, message: str):
    _emit(level, message)


# ═══════════════════════════════════════════════════════════════
#  平台任务管理
# ═══════════════════════════════════════════════════════════════

_platform_tasks: dict[str, asyncio.Task] = {}
_IMPORTS = {
    "telegram": ("platforms.telegram.bot", "run_telegram_bot"),
    "discord":  ("platforms.discord.bot", "run_discord_bot"),
    "napcat":   ("platforms.napcat.server", "run_napcat_bot"),
}


def platform_is_running(platform: str) -> bool:
    t = _platform_tasks.get(platform)
    return t is not None and not t.done()


async def _run_platform(platform: str):
    import importlib
    mod_path, func_name = _IMPORTS[platform]
    mod = importlib.import_module(mod_path)
    launcher = getattr(mod, func_name)
    try:
        await launcher()
    except asyncio.CancelledError:
        _emit(platform, f"{platform} Bot 任务被取消")
        raise
    except Exception as e:
        _emit(platform, f"{platform} Bot 异常退出: {e}")
        import traceback
        traceback.print_exc()


async def start_platform(platform: str):
    if platform_is_running(platform):
        return
    pcfg = getattr(config, platform, None)
    if pcfg is not None:
        pcfg.enabled = True
    save_config(config)
    _platform_tasks[platform] = asyncio.create_task(_run_platform(platform))
    _emit(platform, f"{platform} Bot 已启动")


async def stop_platform(platform: str):
    task = _platform_tasks.pop(platform, None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    pcfg = getattr(config, platform, None)
    if pcfg is not None:
        pcfg.enabled = False
    save_config(config)
    _emit(platform, f"{platform} Bot 已停止")


# ═══════════════════════════════════════════════════════════════
#  页面路由
# ═══════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    html_path = os.path.join(WEB_DIR, "templates", "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>模板文件未找到</h1>", status_code=500)


# ═══════════════════════════════════════════════════════════════
#  API — 状态
# ═══════════════════════════════════════════════════════════════

@app.get("/api/status")
async def api_status():
    return {
        "telegram": {
            "running": platform_is_running("telegram"),
            "bot_token": bool(config.telegram.bot_token),
        },
        "discord": {
            "running": platform_is_running("discord"),
            "bot_token": bool(config.discord.bot_token),
        },
        "napcat": {
            "running": platform_is_running("napcat"),
            "port": config.napcat.port,
        },
    }


# ═══════════════════════════════════════════════════════════════
#  API — 平台启停
# ═══════════════════════════════════════════════════════════════

@app.post("/api/platform/{platform}/start")
async def api_start_platform(platform: str):
    if platform not in ("telegram", "discord", "napcat"):
        return JSONResponse({"ok": False, "error": f"未知平台: {platform}"}, 400)
    await start_platform(platform)
    return {"ok": True, "running": True}


@app.post("/api/platform/{platform}/stop")
async def api_stop_platform(platform: str):
    if platform not in ("telegram", "discord", "napcat"):
        return JSONResponse({"ok": False, "error": f"未知平台: {platform}"}, 400)
    await stop_platform(platform)
    return {"ok": True, "running": False}


# ═══════════════════════════════════════════════════════════════
#  API — 结构化配置
# ═══════════════════════════════════════════════════════════════

@app.get("/api/config")
async def api_get_config():
    return {
        "st": {
            "url": config.st.url,
        },
        "telegram": {
            "bot_token": config.telegram.bot_token,
            "admin_mode": config.telegram.admin_mode,
            "admins": config.telegram.admins,
        },
        "discord": {
            "bot_token": config.discord.bot_token,
            "admin_mode": config.discord.admin_mode,
            "admins": config.discord.admins,
        },
        "napcat": {
            "port": config.napcat.port,
            "admin_mode": config.napcat.admin_mode,
            "admins": config.napcat.admins,
        },
    }


@app.post("/api/config")
async def api_save_config(request: Request):
    body = await request.json()
    platform = body.get("platform", "")
    field = body.get("field", "")
    value = body.get("value")

    if platform == "st":
        pcfg = config.st
    elif platform in ("telegram", "discord", "napcat"):
        pcfg = getattr(config, platform, None)
    else:
        return JSONResponse({"ok": False, "error": f"未知平台: {platform}"}, 400)

    if pcfg is None:
        return JSONResponse({"ok": False, "error": "配置不存在"}, 400)

    if not hasattr(pcfg, field):
        return JSONResponse({"ok": False, "error": f"未知字段: {field}"}, 400)

    current = getattr(pcfg, field)
    if isinstance(current, bool):
        value = bool(value)
    elif isinstance(current, int):
        value = int(value)
    elif isinstance(current, list):
        return JSONResponse({"ok": False, "error": "admins 请使用 /api/config/admins 端点"}, 400)

    setattr(pcfg, field, value)

    try:
        save_config(config)
        _emit("web", f"配置已更新: {platform}.{field} = {value}")
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)


# ═══════════════════════════════════════════════════════════════
#  API — 管理员 ID 管理
# ═══════════════════════════════════════════════════════════════

@app.post("/api/config/admins/{platform}/add")
async def api_add_admin(platform: str, request: Request):
    if platform not in ("telegram", "discord", "napcat"):
        return JSONResponse({"ok": False, "error": f"未知平台: {platform}"}, 400)
    pcfg = getattr(config, platform, None)
    if pcfg is None:
        return JSONResponse({"ok": False, "error": "配置不存在"}, 400)

    body = await request.json()
    uid = str(body.get("user_id", "")).strip()
    if not uid:
        return JSONResponse({"ok": False, "error": "user_id 不能为空"}, 400)
    if uid in [str(a) for a in pcfg.admins]:
        return JSONResponse({"ok": False, "error": "该 ID 已存在"}, 400)

    pcfg.admins.append(uid)
    save_config(config)
    reload_config()
    _emit("web", f"{platform} 管理员已添加: {uid}")
    return {"ok": True, "admins": pcfg.admins}


@app.post("/api/config/admins/{platform}/remove")
async def api_remove_admin(platform: str, request: Request):
    if platform not in ("telegram", "discord", "napcat"):
        return JSONResponse({"ok": False, "error": f"未知平台: {platform}"}, 400)
    pcfg = getattr(config, platform, None)
    if pcfg is None:
        return JSONResponse({"ok": False, "error": "配置不存在"}, 400)

    body = await request.json()
    uid = str(body.get("user_id", "")).strip()
    if uid not in [str(a) for a in pcfg.admins]:
        return JSONResponse({"ok": False, "error": "该 ID 不存在"}, 400)

    pcfg.admins = [a for a in pcfg.admins if str(a) != uid]
    save_config(config)
    reload_config()
    _emit("web", f"{platform} 管理员已移除: {uid}")
    return {"ok": True, "admins": pcfg.admins}


# ═══════════════════════════════════════════════════════════════
#  日志轮询（替代 SSE，避免浏览器永久 loading）
# ═══════════════════════════════════════════════════════════════

@app.get("/api/logs")
async def api_logs(since: int = 0):
    """返回 since 索引之后的新日志行"""
    if since < 0 or since >= len(_log_buffer):
        return {"lines": [], "next_since": len(_log_buffer)}
    new_lines = _log_buffer[since:]
    return {"lines": new_lines, "next_since": len(_log_buffer)}


# ═══════════════════════════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════════════════════════

async def run_web(auto_start: bool = False):
    # 预检
    html_path = os.path.join(WEB_DIR, "templates", "index.html")
    if os.path.isfile(html_path):
        _emit("web", f"模板已就绪 ({os.path.getsize(html_path)} bytes)")
    else:
        _emit("web", f"警告: 模板文件不存在 {html_path}")

    import uvicorn
    cfg = {"app": app, "host": config.web.host, "port": config.web.port, "log_level": "warning"}
    server = uvicorn.Server(uvicorn.Config(**cfg))
    _emit("web", f"管理面板运行在 http://{config.web.host}:{config.web.port}")

    if auto_start:
        for p in ("telegram", "discord", "napcat"):
            pcfg = getattr(config, p, None)
            if pcfg and pcfg.enabled:
                await start_platform(p)

    await server.serve()
