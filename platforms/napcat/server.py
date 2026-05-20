"""NapCat/QQ OneBot v11 WebSocket 服务器"""
import asyncio
import json
import sys

import websockets

import core
from core import admin
from .responder import handle_message

PLATFORM = "napcat"


async def _handle_connection(websocket, debug: bool):
    print(f"[napcat] 已连接", flush=True)
    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[napcat] [原始消息] {raw}", flush=True)
                continue
            if debug:
                print(f"[napcat] [收到消息] {json.dumps(data, indent=2, ensure_ascii=False)}", flush=True)
            asyncio.create_task(handle_message(websocket, data))
    except websockets.exceptions.ConnectionClosed as e:
        print(f"[napcat] 断开: {e}", flush=True)


async def run_napcat_bot():
    cfg = core.config.napcat
    if not cfg.enabled:
        print("[napcat] 未启用，跳过启动", flush=True)
        return

    admin.init()
    port = cfg.port
    debug = getattr(cfg, "debug", False)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    print(f"[napcat] WebSocket 服务监听在 ws://{cfg.host}:{port}  (debug={debug})", flush=True)

    async def _handle(ws):
        await _handle_connection(ws, debug)

    try:
        async with websockets.serve(_handle, cfg.host, port):
            await asyncio.Future()
    except Exception as e:
        print(f"[napcat] 服务异常: {e}", flush=True)
