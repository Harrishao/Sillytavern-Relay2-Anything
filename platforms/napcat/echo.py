"""OneBot v11 消息发送模块"""
import json


async def _send_action(websocket, action, params, echo=None):
    payload = {"action": action, "params": params}
    if echo is not None:
        payload["echo"] = echo
    await websocket.send(json.dumps(payload, ensure_ascii=False))
    print(f"[napcat] {json.dumps(payload, indent=2, ensure_ascii=False)}", flush=True)


async def echo_private_msg(websocket, user_id, message):
    await _send_action(
        websocket,
        "send_private_msg",
        {"user_id": user_id, "message": message},
    )


async def echo_group_msg(websocket, group_id, message):
    await _send_action(
        websocket,
        "send_group_msg",
        {"group_id": group_id, "message": message},
    )


async def echo_private_image(websocket, user_id, image_path):
    path = image_path.replace("\\", "/")
    await _send_action(
        websocket,
        "send_private_msg",
        {
            "user_id": user_id,
            "message": [{"type": "image", "data": {"file": f"file:///{path}"}}],
        },
    )


async def echo_group_image(websocket, group_id, image_path):
    path = image_path.replace("\\", "/")
    await _send_action(
        websocket,
        "send_group_msg",
        {
            "group_id": group_id,
            "message": [{"type": "image", "data": {"file": f"file:///{path}"}}],
        },
    )
