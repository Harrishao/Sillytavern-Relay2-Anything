"""
Telegram Bot 适配器
命令处理器 + inline 键盘回调 + pending 状态管理
"""
import asyncio
import datetime as dt
import os
import sys
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.error import TimedOut, NetworkError

# core 模块导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import core
from core import config as cfg
from core import browser, api, interaction, screenshot
from core import admin

PLATFORM = "telegram"

# ═══════════════════════════════════════════════════════════════
#  Pending state
# ═══════════════════════════════════════════════════════════════

_pending = {}
PENDING_TIMEOUT = 60


def _set_pending(user_id: int, action: str, data, **kwargs):
    _pending[user_id] = {
        "action": action,
        "data": data,
        "expires_at": time.time() + PENDING_TIMEOUT,
        **kwargs,
    }


def _get_pending(user_id: int) -> dict | None:
    p = _pending.get(user_id)
    if not p:
        return None
    if time.time() > p["expires_at"]:
        del _pending[user_id]
        return None
    return p


def _clear_pending(user_id: int):
    _pending.pop(user_id, None)


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

async def _check_whitelist(update: Update) -> bool:
    if not admin.is_whitelisted(update.effective_user.id, PLATFORM):
        await update.message.reply_text("管理员模式已开启，但你不在白名单中哦...")
        return False
    return True


async def _safe_send_photo(context: ContextTypes.DEFAULT_TYPE, chat_id: int,
                           path: str, caption: str = None, reply_markup=None,
                           fallback_text: str = None) -> bool:
    try:
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                await context.bot.send_photo(
                    chat_id, f, caption=caption or "",
                    reply_markup=reply_markup,
                )
        else:
            await context.bot.send_message(
                chat_id, caption or "操作已完成。",
                reply_markup=reply_markup,
            )
        return True
    except Exception as e:
        print(f"[telegram] 图片发送失败: {e}", flush=True)
        try:
            fallback = fallback_text or (caption or "操作已完成，但截图上传失败。")
            await context.bot.send_message(chat_id, fallback)
            return True
        except Exception as e2:
            print(f"[telegram] 文本回退也失败了: {e2}", flush=True)
            return False


# ═══════════════════════════════════════════════════════════════
#  Keyboards
# ═══════════════════════════════════════════════════════════════

def _list_keyboard(items_count: int, max_show: int = 20) -> InlineKeyboardMarkup:
    n = min(items_count, max_show)
    buttons = []
    for i in range(n):
        if i % 5 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(str(i), callback_data=str(i)))
    buttons.append([InlineKeyboardButton("❌ Exit", callback_data="exit")])
    return InlineKeyboardMarkup(buttons)


def _message_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◀ 左翻页", callback_data="left"),
            InlineKeyboardButton("▶ 右翻页", callback_data="right"),
        ],
        [InlineKeyboardButton("🔄 重新生成", callback_data="regenerate")],
    ])


# ═══════════════════════════════════════════════════════════════
#  Expiry scheduler
# ═══════════════════════════════════════════════════════════════

async def _schedule_expiry(context: ContextTypes.DEFAULT_TYPE,
                           chat_id: int, message_id: int,
                           user_id: int, delay: int = PENDING_TIMEOUT):
    await asyncio.sleep(delay)
    p = _pending.get(user_id)
    if p is None:
        return
    _clear_pending(user_id)
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id,
            text="⏰ 输入窗口已过期，请重新使用命令。",
        )
    except Exception:
        try:
            await context.bot.send_message(chat_id, "⏰ 输入窗口已过期，请重新使用命令。")
        except Exception as e:
            print(f"[telegram] 过期消息清理失败: {e}", flush=True)


# ═══════════════════════════════════════════════════════════════
#  /st
# ═══════════════════════════════════════════════════════════════

async def cmd_st(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    if not core.acquire_lock():
        await update.message.reply_text("有正在处理中的消息，请稍后再试...或使用 /stop 中止")
        return

    chat_id = update.effective_chat.id
    text = " ".join(context.args) if context.args else ""

    if not text:
        core.release_lock()
        await update.message.reply_text("用法: /st <消息内容>")
        return

    status_msg = await update.message.reply_text("处理中...")
    try:
        result = await interaction.send_message(text)
        if result is None or not result.get("content"):
            await status_msg.delete()
            await update.message.reply_text("消息发送失败或等待回复超时...")
            return

        path = result.get("screenshot_path")
        await status_msg.delete()
        if path and os.path.isfile(path):
            await _safe_send_photo(context, chat_id, path, reply_markup=_message_keyboard())
        else:
            content = result["content"][:1900]
            await context.bot.send_message(chat_id, content, reply_markup=_message_keyboard())
    finally:
        core.release_lock()


# ═══════════════════════════════════════════════════════════════
#  /stop
# ═══════════════════════════════════════════════════════════════

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    ok = await interaction.cancel_processing()
    core.release_lock()
    if ok:
        await update.message.reply_text("已中止当前生成。")
    else:
        await update.message.reply_text("没有正在进行的生成。")


# ═══════════════════════════════════════════════════════════════
#  /lastmsg
# ═══════════════════════════════════════════════════════════════

async def cmd_lastmsg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    chat_id = update.effective_chat.id
    path = await screenshot.capture_screenshot()
    if path and os.path.isfile(path):
        await _safe_send_photo(context, chat_id, path, reply_markup=_message_keyboard())
    else:
        await update.message.reply_text("截图失败，请稍后重试...")


# ═══════════════════════════════════════════════════════════════
#  /ss
# ═══════════════════════════════════════════════════════════════

async def cmd_ss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    chat_id = update.effective_chat.id
    path = await screenshot.capture_full_screenshot()
    if path and os.path.isfile(path):
        await _safe_send_photo(context, chat_id, path)
    else:
        await update.message.reply_text("截图失败，请稍后重试...")


# ═══════════════════════════════════════════════════════════════
#  /rf
# ═══════════════════════════════════════════════════════════════

async def cmd_rf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    chat_id = update.effective_chat.id
    ok = await browser.refresh_page()
    if not ok:
        await update.message.reply_text("页面刷新失败...")
        return
    path = await screenshot.capture_full_screenshot()
    if path and os.path.isfile(path):
        await _safe_send_photo(context, chat_id, path, caption="页面已刷新:")
    else:
        await update.message.reply_text("页面已刷新，但截图失败。")


# ═══════════════════════════════════════════════════════════════
#  /del
# ═══════════════════════════════════════════════════════════════

async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    chat_id = update.effective_chat.id
    n = 1
    if context.args:
        try:
            n = int(context.args[0])
        except ValueError:
            pass
    if n not in (1, 2):
        n = 1

    ok = await api.delete_messages(n)
    if not ok:
        await update.message.reply_text("删除消息失败。")
        return
    await asyncio.sleep(1)
    path = await screenshot.capture_screenshot()
    if path and os.path.isfile(path):
        await _safe_send_photo(context, chat_id, path,
                               caption=f"已删除最后 {n} 条消息:",
                               reply_markup=_message_keyboard())
    else:
        await context.bot.send_message(chat_id, f"已删除最后 {n} 条消息。",
                                       reply_markup=_message_keyboard())


# ═══════════════════════════════════════════════════════════════
#  /left
# ═══════════════════════════════════════════════════════════════

async def cmd_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    chat_id = update.effective_chat.id
    ok = await interaction.swipe_left()
    if not ok:
        await update.message.reply_text("左翻页失败，没有更多备选回复或当前不在聊天中。")
        return
    path = await screenshot.capture_screenshot()
    if path and os.path.isfile(path):
        await _safe_send_photo(context, chat_id, path, reply_markup=_message_keyboard())
    else:
        await update.message.reply_text("截图失败，请稍后重试...")


# ═══════════════════════════════════════════════════════════════
#  /right
# ═══════════════════════════════════════════════════════════════

async def cmd_right(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    chat_id = update.effective_chat.id
    if not core.acquire_lock():
        await update.message.reply_text("有正在处理中的消息，请稍后再试...")
        return

    try:
        result = await interaction.swipe_right()
        if result is None:
            await update.message.reply_text("右翻页失败，当前不在聊天中。")
            return
        if result == "generating":
            response = await interaction.wait_for_response()
            if not response:
                await update.message.reply_text("等待LLM回复超时...")
                return
        path = await screenshot.capture_screenshot()
        if path and os.path.isfile(path):
            await _safe_send_photo(context, chat_id, path, reply_markup=_message_keyboard())
        else:
            await update.message.reply_text("截图失败，请稍后重试...")
    finally:
        core.release_lock()


# ═══════════════════════════════════════════════════════════════
#  /regenerate
# ═══════════════════════════════════════════════════════════════

async def cmd_regenerate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    chat_id = update.effective_chat.id
    if not core.acquire_lock():
        await update.message.reply_text("有正在处理中的消息，请稍后再试...或使用 /stop 中止")
        return

    try:
        ok = await interaction.regenerate()
        if not ok:
            await update.message.reply_text("重新生成触发失败...")
            return
        response = await interaction.wait_for_response()
        if not response:
            await update.message.reply_text("等待LLM回复超时...")
            return
        path = await screenshot.capture_screenshot()
        if path and os.path.isfile(path):
            await _safe_send_photo(context, chat_id, path, reply_markup=_message_keyboard())
        else:
            content = response.get("content", "")[:1900]
            await context.bot.send_message(chat_id, content, reply_markup=_message_keyboard())
    finally:
        core.release_lock()


# ═══════════════════════════════════════════════════════════════
#  /chat
# ═══════════════════════════════════════════════════════════════

async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    args = context.args or []
    pending = _get_pending(user_id)

    if args and pending and pending["action"] == "chat_pick_for_char":
        try:
            index = int(args[0])
        except ValueError:
            await update.message.reply_text("参数无效，请输入 /chat <数字序号>")
            return
        chats = pending["data"]
        if index < 0 or index >= len(chats):
            await update.message.reply_text(f"序号超出范围，共 {len(chats)} 条聊天。")
            return
        chat = chats[index]
        file_name = chat.get("file_name", "")
        if not file_name:
            await update.message.reply_text("无法获取聊天文件名。")
            return
        ok = await api.open_chat(file_name)
        if not ok:
            await update.message.reply_text("切换聊天失败。")
            return
        _clear_pending(user_id)
        await asyncio.sleep(2)
        path = await screenshot.capture_screenshot()
        name = file_name.replace(".jsonl", "")
        if path and os.path.isfile(path):
            await _safe_send_photo(context, chat_id, path,
                                   caption=f"已切换到: {name}",
                                   reply_markup=_message_keyboard())
        else:
            await update.message.reply_text("截图失败...")
        return

    chats = await api.fetch_recent_chats()
    if not chats:
        await update.message.reply_text("获取聊天列表失败。")
        return

    if args:
        try:
            index = int(args[0])
        except ValueError:
            await update.message.reply_text("参数无效，请输入 /chat <数字序号>")
            return
        if pending and pending["action"] == "chat_pick":
            chats = pending["data"]
        if index < 0 or index >= len(chats):
            await update.message.reply_text(f"序号超出范围，共 {len(chats)} 条聊天。")
            return
        chat = chats[index]
        file_name = chat.get("file_name", "")
        if not file_name:
            await update.message.reply_text("无法获取聊天文件名。")
            return
        ok = await api.open_chat(file_name)
        if not ok:
            await update.message.reply_text("切换聊天失败。")
            return
        _clear_pending(user_id)
        await asyncio.sleep(2)
        path = await screenshot.capture_screenshot()
        name = file_name.replace(".jsonl", "")
        if path and os.path.isfile(path):
            await _safe_send_photo(context, chat_id, path,
                                   caption=f"已切换到: {name}",
                                   reply_markup=_message_keyboard())
        else:
            await update.message.reply_text("截图失败...")
        return

    lines = [f"**最近聊天 ({len(chats)}条)**"]
    for i, c in enumerate(chats[:20]):
        ch_name = c.get("file_name", "?").replace(".jsonl", "")
        items = c.get("chat_items", 0)
        mes = (c.get("mes", "") or "")[:50].replace("\n", " ")
        lines.append(f"`{i}` — {ch_name}  _(消息:{items})_")
        if mes:
            lines.append(f"> {mes}")
    if len(chats) > 20:
        lines.append(f"...还有 {len(chats) - 20} 条")
    lines.append("使用按钮选择聊天，或 `/chat <序号>` / `/exit` 退出")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n...(截断)"

    sent = await update.message.reply_text(msg, reply_markup=_list_keyboard(len(chats)))
    _set_pending(user_id, "chat_pick", chats, message_id=sent.message_id, chat_id=chat_id)
    asyncio.create_task(_schedule_expiry(context, chat_id, sent.message_id, user_id))


# ═══════════════════════════════════════════════════════════════
#  /char
# ═══════════════════════════════════════════════════════════════

async def cmd_char(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    args = context.args or []
    pending = _get_pending(user_id)

    if args and pending and pending["action"] == "char_pick":
        try:
            index = int(args[0])
        except ValueError:
            await update.message.reply_text("参数无效，请输入 /char <数字序号>")
            return
        chars = pending["data"]
        if index < 0 or index >= len(chars):
            await update.message.reply_text(f"序号超出范围，共 {len(chars)} 个角色。")
            return
        char = chars[index]
        avatar = char.get("avatar", "")
        char_name = char.get("name", "?")
        chats = await api.fetch_character_chats(avatar)
        if not chats:
            await update.message.reply_text(f"角色 **{char_name}** 没有聊天记录。")
            _clear_pending(user_id)
            return
        if len(chats) == 1:
            file_name = chats[0].get("file_name", "")
            if not file_name:
                await update.message.reply_text("无法获取聊天文件名。")
                _clear_pending(user_id)
                return
            ok = await api.open_chat(file_name)
            if not ok:
                await update.message.reply_text("切换聊天失败。")
                _clear_pending(user_id)
                return
            _clear_pending(user_id)
            await asyncio.sleep(2)
            path = await screenshot.capture_screenshot()
            if path and os.path.isfile(path):
                await _safe_send_photo(context, chat_id, path,
                                       caption=f"已切换到: {char_name}",
                                       reply_markup=_message_keyboard())
            else:
                await update.message.reply_text("截图失败...")
        else:
            lines = [f"**{char_name} 的聊天记录 ({len(chats)}条)**"]
            for i, c in enumerate(chats[:20]):
                fname = c.get("file_name", "?").replace(".jsonl", "")
                items = c.get("chat_items", 0)
                lines.append(f"`{i}` — {fname}  _(消息:{items})_")
            if len(chats) > 20:
                lines.append(f"...还有 {len(chats) - 20} 条")
            lines.append("使用按钮选择聊天，或 `/chat <序号>` / `/exit` 退出")
            msg = "\n".join(lines)
            if len(msg) > 4000:
                msg = msg[:3900] + "\n...(截断)"
            sent = await update.message.reply_text(msg, reply_markup=_list_keyboard(len(chats)))
            _set_pending(user_id, "chat_pick_for_char", chats,
                         char_name=char_name,
                         message_id=sent.message_id, chat_id=chat_id)
            asyncio.create_task(_schedule_expiry(context, chat_id, sent.message_id, user_id))
        return

    chars = await api.fetch_characters()
    if not chars:
        await update.message.reply_text("获取角色卡列表失败。")
        return

    if args:
        try:
            index = int(args[0])
        except ValueError:
            await update.message.reply_text("参数无效，请输入 /char <数字序号>")
            return
        if index < 0 or index >= len(chars):
            await update.message.reply_text(f"序号超出范围，共 {len(chars)} 个角色。")
            return
        char = chars[index]
        avatar = char.get("avatar", "")
        char_name = char.get("name", "?")
        chats = await api.fetch_character_chats(avatar)
        if not chats:
            await update.message.reply_text(f"角色 **{char_name}** 没有聊天记录。")
            return
        if len(chats) == 1:
            file_name = chats[0].get("file_name", "")
            if not file_name:
                await update.message.reply_text("无法获取聊天文件名。")
                return
            ok = await api.open_chat(file_name)
            if not ok:
                await update.message.reply_text("切换聊天失败。")
                return
            await asyncio.sleep(2)
            path = await screenshot.capture_screenshot()
            if path and os.path.isfile(path):
                await _safe_send_photo(context, chat_id, path,
                                       caption=f"已切换到: {char_name}",
                                       reply_markup=_message_keyboard())
            else:
                await update.message.reply_text("截图失败...")
        else:
            lines = [f"**{char_name} 的聊天记录 ({len(chats)}条)**"]
            for i, c in enumerate(chats[:20]):
                fname = c.get("file_name", "?").replace(".jsonl", "")
                items = c.get("chat_items", 0)
                lines.append(f"`{i}` — {fname}  _(消息:{items})_")
            if len(chats) > 20:
                lines.append(f"...还有 {len(chats) - 20} 条")
            lines.append("使用按钮选择聊天，或 `/chat <序号>` / `/exit` 退出")
            msg = "\n".join(lines)
            if len(msg) > 4000:
                msg = msg[:3900] + "\n...(截断)"
            sent = await update.message.reply_text(msg, reply_markup=_list_keyboard(len(chats)))
            _set_pending(user_id, "chat_pick_for_char", chats,
                         char_name=char_name,
                         message_id=sent.message_id, chat_id=chat_id)
            asyncio.create_task(_schedule_expiry(context, chat_id, sent.message_id, user_id))
        return

    lines = [f"**角色卡列表 ({len(chars)}个)**"]
    for i, c in enumerate(chars[:25]):
        c_name = c.get("name", "?")
        last = c.get("date_last_chat", 0)
        if last:
            try:
                last_str = dt.datetime.fromtimestamp(last / 1000).strftime("%m/%d %H:%M")
            except Exception:
                last_str = str(last)
        else:
            last_str = "从未"
        lines.append(f"`{i}` — {c_name}  _(最后: {last_str})_")
    if len(chars) > 25:
        lines.append(f"...还有 {len(chars) - 25} 个")
    lines.append("使用按钮选择角色，或 `/char <序号>` / `/exit` 退出")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n...(截断)"

    sent = await update.message.reply_text(msg, reply_markup=_list_keyboard(len(chars)))
    _set_pending(user_id, "char_pick", chars, message_id=sent.message_id, chat_id=chat_id)
    asyncio.create_task(_schedule_expiry(context, chat_id, sent.message_id, user_id))


# ═══════════════════════════════════════════════════════════════
#  /user
# ═══════════════════════════════════════════════════════════════

async def cmd_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    user_id = update.effective_user.id
    args = context.args or []
    pending = _get_pending(user_id)

    if args and pending and pending["action"] == "user_pick":
        try:
            index = int(args[0])
        except ValueError:
            await update.message.reply_text("参数无效，请输入 /user <数字序号>")
            return
        personas = pending["data"]
        if index < 0 or index >= len(personas):
            await update.message.reply_text(f"序号超出范围，共 {len(personas)} 个用户设定。")
            return
        p = personas[index]
        ok = await api.select_persona(p["avatar_id"])
        if not ok:
            await update.message.reply_text("切换用户设定失败。")
            return
        _clear_pending(user_id)
        current = await api.get_current_persona()
        await update.message.reply_text(f"已切换用户设定为: **{current}** _(序号:{index})_")
        return

    personas = await api.fetch_personas()
    if not personas:
        await update.message.reply_text("获取用户设定列表失败。")
        return

    if args:
        try:
            index = int(args[0])
        except ValueError:
            await update.message.reply_text("参数无效，请输入 /user <数字序号>")
            return
        if index < 0 or index >= len(personas):
            await update.message.reply_text(f"序号超出范围，共 {len(personas)} 个用户设定。")
            return
        p = personas[index]
        ok = await api.select_persona(p["avatar_id"])
        if not ok:
            await update.message.reply_text("切换用户设定失败。")
            return
        current = await api.get_current_persona()
        await update.message.reply_text(f"已切换用户设定为: **{current}** _(序号:{index})_")
        return

    chat_id = update.effective_chat.id
    lines = [f"**用户设定列表 ({len(personas)}个)**"]
    for i, p in enumerate(personas[:20]):
        name = p.get("name", "?")
        desc = (p.get("description", "") or "[无描述]")[:80]
        lines.append(f"`{i}` — **{name}**")
        if desc:
            lines.append(f"> {desc}")
    if len(personas) > 20:
        lines.append(f"...还有 {len(personas) - 20} 个")
    lines.append("使用按钮选择用户设定，或 `/user <序号>` / `/exit` 退出")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3900] + "\n...(截断)"

    sent = await update.message.reply_text(msg, reply_markup=_list_keyboard(len(personas)))
    _set_pending(user_id, "user_pick", personas, message_id=sent.message_id, chat_id=chat_id)
    asyncio.create_task(_schedule_expiry(context, chat_id, sent.message_id, user_id))


# ═══════════════════════════════════════════════════════════════
#  /exit
# ═══════════════════════════════════════════════════════════════

async def cmd_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _check_whitelist(update):
        return
    _clear_pending(update.effective_user.id)
    await update.message.reply_text("已退出输入窗口。")


# ═══════════════════════════════════════════════════════════════
#  /admin
# ═══════════════════════════════════════════════════════════════

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin.is_l1_admin(update.effective_user.id, PLATFORM):
        return
    new_state = admin.toggle_admin_mode(PLATFORM)
    state_str = "开启" if new_state else "关闭"
    await update.message.reply_text(f"收到，已{state_str}管理员模式")


# ═══════════════════════════════════════════════════════════════
#  /admin_add
# ═══════════════════════════════════════════════════════════════

async def cmd_admin_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin.is_l1_admin(update.effective_user.id, PLATFORM):
        return
    target = context.args[0] if context.args else ""
    if not target:
        await update.message.reply_text("用法: /admin_add <用户ID>")
        return
    admin.add_whitelist(target)
    await update.message.reply_text(f"已将 {target} 加入白名单。")


# ═══════════════════════════════════════════════════════════════
#  /admin_del
# ═══════════════════════════════════════════════════════════════

async def cmd_admin_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin.is_l1_admin(update.effective_user.id, PLATFORM):
        return
    target = context.args[0] if context.args else ""
    if not target:
        await update.message.reply_text("用法: /admin_del <用户ID>")
        return
    admin.remove_whitelist(target)
    await update.message.reply_text(f"已将 {target} 移出白名单。")


# ═══════════════════════════════════════════════════════════════
#  Inline button callback
# ═══════════════════════════════════════════════════════════════

async def on_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    data = query.data
    pending = _get_pending(user_id)

    if data == "exit":
        _clear_pending(user_id)
        try:
            await query.message.edit_text("已退出输入窗口。")
        except Exception:
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(chat_id, "已退出输入窗口。")
        return

    if data in ("left", "right", "regenerate"):
        if not admin.is_whitelisted(user_id, PLATFORM):
            await query.message.reply_text("管理员模式已开启，但你不在白名单中哦...")
            return
        await _handle_message_action(update, context, data)
        return

    if data.isdigit() and pending:
        if not admin.is_whitelisted(user_id, PLATFORM):
            await query.message.reply_text("管理员模式已开启，但你不在白名单中哦...")
            return
        index = int(data)
        await _handle_list_select(update, context, pending, index)
        return

    await context.bot.send_message(chat_id, "操作已过期，请重新使用命令。")


# ═══════════════════════════════════════════════════════════════
#  List selection handler
# ═══════════════════════════════════════════════════════════════

async def _handle_list_select(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              pending: dict, index: int):
    query = update.callback_query
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    action = pending["action"]
    items = pending["data"]

    if index < 0 or index >= len(items):
        await context.bot.send_message(chat_id, "序号超出范围。")
        return

    if action == "char_pick":
        char = items[index]
        avatar = char.get("avatar", "")
        char_name = char.get("name", "?")
        chats = await api.fetch_character_chats(avatar)
        if not chats:
            _clear_pending(user_id)
            await context.bot.send_message(chat_id, f"角色 **{char_name}** 没有聊天记录。")
            return
        if len(chats) == 1:
            try:
                await query.message.delete()
            except Exception:
                pass
            file_name = chats[0].get("file_name", "")
            if not file_name:
                _clear_pending(user_id)
                await context.bot.send_message(chat_id, "无法获取聊天文件名。")
                return
            ok = await api.open_chat(file_name)
            if not ok:
                _clear_pending(user_id)
                await context.bot.send_message(chat_id, "切换聊天失败。")
                return
            _clear_pending(user_id)
            await asyncio.sleep(2)
            path = await screenshot.capture_screenshot()
            if path and os.path.isfile(path):
                await _safe_send_photo(context, chat_id, path,
                                       caption=f"已切换到: {char_name}",
                                       reply_markup=_message_keyboard())
            else:
                await context.bot.send_message(chat_id, "截图失败...")
        else:
            lines = [f"**{char_name} 的聊天记录 ({len(chats)}条)**"]
            for i, c in enumerate(chats[:20]):
                fname = c.get("file_name", "?").replace(".jsonl", "")
                items_count = c.get("chat_items", 0)
                lines.append(f"`{i}` — {fname}  _(消息:{items_count})_")
            if len(chats) > 20:
                lines.append(f"...还有 {len(chats) - 20} 条")
            lines.append("使用按钮选择聊天，或 `/chat <序号>` / `/exit` 退出")
            msg = "\n".join(lines)
            if len(msg) > 4000:
                msg = msg[:3900] + "\n...(截断)"
            keyboard = _list_keyboard(len(chats))
            try:
                await query.message.edit_text(msg, reply_markup=keyboard)
                sent = query.message
            except Exception:
                try:
                    await query.message.delete()
                except Exception:
                    pass
                sent = await context.bot.send_message(chat_id, msg, reply_markup=keyboard)
            _set_pending(user_id, "chat_pick_for_char", chats,
                         char_name=char_name,
                         message_id=sent.message_id, chat_id=chat_id)
            asyncio.create_task(_schedule_expiry(context, chat_id, sent.message_id, user_id))

    elif action in ("chat_pick", "chat_pick_for_char"):
        try:
            await query.message.delete()
        except Exception:
            pass
        chat = items[index]
        file_name = chat.get("file_name", "")
        if not file_name:
            _clear_pending(user_id)
            await context.bot.send_message(chat_id, "无法获取聊天文件名。")
            return
        ok = await api.open_chat(file_name)
        if not ok:
            _clear_pending(user_id)
            await context.bot.send_message(chat_id, "切换聊天失败。")
            return
        _clear_pending(user_id)
        await asyncio.sleep(2)
        path = await screenshot.capture_screenshot()
        name = file_name.replace(".jsonl", "")
        if path and os.path.isfile(path):
            await _safe_send_photo(context, chat_id, path,
                                   caption=f"已切换到: {name}",
                                   reply_markup=_message_keyboard())
        else:
            await context.bot.send_message(chat_id, "截图失败...")

    elif action == "user_pick":
        p = items[index]
        ok = await api.select_persona(p["avatar_id"])
        if not ok:
            _clear_pending(user_id)
            await context.bot.send_message(chat_id, "切换用户设定失败。")
            return
        _clear_pending(user_id)
        current = await api.get_current_persona()
        text = f"已切换用户设定为: **{current}** _(序号:{index})_"
        try:
            await query.message.edit_text(text)
        except Exception:
            try:
                await query.message.delete()
            except Exception:
                pass
            await context.bot.send_message(chat_id, text)


# ═══════════════════════════════════════════════════════════════
#  Message action handler
# ═══════════════════════════════════════════════════════════════

async def _edit_message_media(context: ContextTypes.DEFAULT_TYPE, chat_id: int,
                              message, path: str, reply_markup=None) -> bool:
    try:
        with open(path, "rb") as f:
            await context.bot.edit_message_media(
                chat_id=chat_id, message_id=message.message_id,
                media=InputMediaPhoto(f),
                reply_markup=reply_markup,
            )
        return True
    except Exception as e:
        print(f"[telegram] edit_media 失败: {e}", flush=True)
        return False


async def _handle_message_action(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 action: str):
    query = update.callback_query
    chat_id = update.effective_chat.id
    msg = query.message

    if action == "left":
        ok = await interaction.swipe_left()
        if not ok:
            await context.bot.send_message(chat_id, "左翻页失败，没有更多备选回复或当前不在聊天中。")
            return
        path = await screenshot.capture_screenshot()
        if path and os.path.isfile(path):
            if not await _edit_message_media(context, chat_id, msg, path,
                                             reply_markup=_message_keyboard()):
                try:
                    await msg.delete()
                except Exception:
                    pass
                await _safe_send_photo(context, chat_id, path, reply_markup=_message_keyboard())
        else:
            try:
                await msg.edit_caption(caption="操作已完成，但截图上传失败。",
                                       reply_markup=_message_keyboard())
            except Exception:
                await context.bot.send_message(chat_id, "截图失败，请稍后重试...")

    elif action == "right":
        if not core.acquire_lock():
            await context.bot.send_message(chat_id, "有正在处理中的消息，请稍后再试...")
            return
        try:
            result = await interaction.swipe_right()
            if result is None:
                await context.bot.send_message(chat_id, "右翻页失败，当前不在聊天中。")
                return
            if result == "generating":
                try:
                    await msg.delete()
                except Exception:
                    pass
                status_msg = await context.bot.send_message(chat_id, "正在重新生成...")
                print("[telegram] 右翻页触发了新生成，等待LLM回复...", flush=True)
                response = await interaction.wait_for_response()
                if not response:
                    await status_msg.edit_text("等待LLM回复超时...")
                    return
                await status_msg.delete()
                path = await screenshot.capture_screenshot()
                if path and os.path.isfile(path):
                    await _safe_send_photo(context, chat_id, path, reply_markup=_message_keyboard())
                else:
                    await context.bot.send_message(chat_id, "截图失败，请稍后重试...")
            else:
                path = await screenshot.capture_screenshot()
                if path and os.path.isfile(path):
                    if not await _edit_message_media(context, chat_id, msg, path,
                                                     reply_markup=_message_keyboard()):
                        try:
                            await msg.delete()
                        except Exception:
                            pass
                        await _safe_send_photo(context, chat_id, path,
                                               reply_markup=_message_keyboard())
                else:
                    try:
                        await msg.edit_caption(caption="操作已完成，但截图上传失败。",
                                               reply_markup=_message_keyboard())
                    except Exception:
                        await context.bot.send_message(chat_id, "截图失败，请稍后重试...")
        finally:
            core.release_lock()

    elif action == "regenerate":
        if not core.acquire_lock():
            await context.bot.send_message(chat_id, "有正在处理中的消息，请稍后再试...或使用 /stop 中止")
            return
        try:
            try:
                await msg.delete()
            except Exception:
                pass
            status_msg = await context.bot.send_message(chat_id, "正在重新生成...")
            print("[telegram] 已触发重新生成，等待LLM回复...", flush=True)
            ok = await interaction.regenerate()
            if not ok:
                await status_msg.edit_text("重新生成触发失败...")
                return
            response = await interaction.wait_for_response()
            if not response:
                await status_msg.delete()
                await context.bot.send_message(chat_id, "等待LLM回复超时...")
                return
            await status_msg.delete()
            path = await screenshot.capture_screenshot()
            if path and os.path.isfile(path):
                await _safe_send_photo(context, chat_id, path, reply_markup=_message_keyboard())
            else:
                content = response.get("content", "")[:1900]
                await context.bot.send_message(chat_id, content, reply_markup=_message_keyboard())
        finally:
            core.release_lock()


# ═══════════════════════════════════════════════════════════════
#  Global error handler
# ═══════════════════════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    print(f"[telegram] 全局异常捕获: {type(err).__name__}: {err}", flush=True)

    if isinstance(err, (TimedOut, NetworkError)):
        return

    try:
        if update and hasattr(update, "effective_chat"):
            chat_id = update.effective_chat.id if update.effective_chat else None
            if chat_id:
                await context.bot.send_message(
                    chat_id, f"操作失败: {type(err).__name__}，请稍后重试。"
                )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  Bot launcher
# ═══════════════════════════════════════════════════════════════

async def _post_init(app: Application):
    cmds = [
        BotCommand("st", "发送消息到酒馆并获取AI回复截图"),
        BotCommand("stop", "停止当前正在生成的AI回复"),
        BotCommand("lastmsg", "截取酒馆最后一条消息"),
        BotCommand("ss", "全页截取酒馆当前界面"),
        BotCommand("rf", "刷新酒馆页面并截图"),
        BotCommand("del", "删除当前聊天最后N条消息（1或2）"),
        BotCommand("left", "切换到上一个备选回复（左翻页）"),
        BotCommand("right", "切换到下一个备选回复（右翻页）"),
        BotCommand("regenerate", "重新生成AI回复"),
        BotCommand("chat", "查看最近聊天列表或切换到指定聊天"),
        BotCommand("char", "查看角色卡列表或选择角色"),
        BotCommand("user", "查看用户设定列表或选择用户设定"),
        BotCommand("exit", "退出当前输入窗口"),
        BotCommand("admin", "切换管理员模式（仅L1管理员）"),
        BotCommand("admin_add", "添加用户到白名单（仅L1管理员）"),
        BotCommand("admin_del", "从白名单移除用户（仅L1管理员）"),
    ]
    try:
        await app.bot.set_my_commands(cmds)
        print(f"[telegram] 已注册 {len(cmds)} 条命令", flush=True)
    except Exception as e:
        print(f"[telegram] 命令注册失败: {e}", flush=True)
    print("[telegram] Bot 已就绪！", flush=True)


async def run_telegram_bot():
    """启动 Telegram Bot"""
    token = cfg.config.telegram.bot_token
    if not token:
        print("[telegram] 未配置 bot_token，跳过启动", flush=True)
        return

    app = Application.builder().token(token).post_init(_post_init).build()

    app.add_handler(CommandHandler("st", cmd_st))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("lastmsg", cmd_lastmsg))
    app.add_handler(CommandHandler("ss", cmd_ss))
    app.add_handler(CommandHandler("rf", cmd_rf))
    app.add_handler(CommandHandler("del", cmd_del))
    app.add_handler(CommandHandler("left", cmd_left))
    app.add_handler(CommandHandler("right", cmd_right))
    app.add_handler(CommandHandler("regenerate", cmd_regenerate))
    app.add_handler(CommandHandler("chat", cmd_chat))
    app.add_handler(CommandHandler("char", cmd_char))
    app.add_handler(CommandHandler("user", cmd_user))
    app.add_handler(CommandHandler("exit", cmd_exit))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("admin_add", cmd_admin_add))
    app.add_handler(CommandHandler("admin_del", cmd_admin_del))
    app.add_handler(CallbackQueryHandler(on_button_click))
    app.add_error_handler(error_handler)

    print("[telegram] 正在启动...", flush=True)
    await app.run_polling()
