"""Discord ST命令 Cog — 所有 /st /chat /char 等命令和交互View"""
import asyncio
import datetime as dt
import os
import time
import traceback

import discord
from discord import app_commands
from discord.ext import commands

import core
from core import admin

PLATFORM = "discord"
DISCORD_MSG_LIMIT = 2000


def _truncate(text: str, limit: int = DISCORD_MSG_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 50] + "\n...(截断)"


async def _safe_followup(interaction: discord.Interaction, *,
                         content: str = None, file_path: str = None,
                         fallback_text: str = None,
                         view: discord.ui.View = None) -> bool:
    try:
        if file_path and os.path.isfile(file_path):
            await interaction.followup.send(
                content=content or "", file=discord.File(file_path), view=view,
            )
        else:
            await interaction.followup.send(content=content or "", view=view)
        return True
    except (discord.HTTPException, OSError) as e:
        print(f"[discord] 文件上传失败(网络错误): {e}", flush=True)
        try:
            fallback = fallback_text or (content or "操作已完成，但截图上传失败。")
            await interaction.followup.send(content=fallback)
            return True
        except Exception as e2:
            print(f"[discord] 文本回退也失败了: {e2}", flush=True)
            return False


class MessageActionView(discord.ui.View):
    """消息结果按钮：左翻页 / 右翻页 / 重新生成"""

    def __init__(self, cog: "STCommands", timeout: float = 60):
        super().__init__(timeout=timeout)
        self.cog = cog

        left_btn = discord.ui.Button(label="◀ 左翻页", style=discord.ButtonStyle.secondary, row=0)
        left_btn.callback = self._on_left
        self.add_item(left_btn)

        right_btn = discord.ui.Button(label="▶ 右翻页", style=discord.ButtonStyle.secondary, row=0)
        right_btn.callback = self._on_right
        self.add_item(right_btn)

        regen_btn = discord.ui.Button(label="🔄 重新生成", style=discord.ButtonStyle.primary, row=0)
        regen_btn.callback = self._on_regenerate
        self.add_item(regen_btn)

    async def _check_access(self, interaction: discord.Interaction) -> bool:
        if not admin.is_whitelisted(interaction.user.id, PLATFORM):
            await interaction.response.send_message(
                "管理员模式已开启，但你不在白名单中哦...", ephemeral=True
            )
            return False
        return True

    async def _on_left(self, interaction: discord.Interaction):
        if not await self._check_access(interaction):
            return
        await interaction.response.defer()
        try:
            ok = await core.swipe_left()
            if not ok:
                await interaction.followup.send("左翻页失败，没有更多备选回复或当前不在聊天中。", ephemeral=True)
                return
            path = await core.capture_screenshot()
            if path and os.path.isfile(path):
                await _safe_followup(interaction, file_path=path, view=MessageActionView(self.cog))
            else:
                await interaction.followup.send("截图失败，请稍后重试...")
        finally:
            try:
                await interaction.message.delete()
            except Exception:
                pass

    async def _on_right(self, interaction: discord.Interaction):
        if not await self._check_access(interaction):
            return
        if not core.acquire_lock():
            await interaction.response.send_message(
                "有正在处理中的消息，请稍后再试...", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            result = await core.swipe_right()
            if result is None:
                await interaction.followup.send("右翻页失败，当前不在聊天中。", ephemeral=True)
                return
            if result == "generating":
                response = await core.wait_for_response()
                if not response:
                    await interaction.followup.send("等待LLM回复超时...", ephemeral=True)
                    return
            path = await core.capture_screenshot()
            if path and os.path.isfile(path):
                await _safe_followup(interaction, file_path=path, view=MessageActionView(self.cog))
            else:
                await interaction.followup.send("截图失败，请稍后重试...")
        finally:
            core.release_lock()
            try:
                await interaction.message.delete()
            except Exception:
                pass

    async def _on_regenerate(self, interaction: discord.Interaction):
        if not await self._check_access(interaction):
            return
        if not core.acquire_lock():
            await interaction.response.send_message(
                "有正在处理中的消息，请稍后再试...或使用 /stop 中止", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            ok = await core.regenerate()
            if not ok:
                await interaction.followup.send("重新生成触发失败...", ephemeral=True)
                return
            response = await core.wait_for_response()
            if not response:
                await interaction.followup.send("等待LLM回复超时...", ephemeral=True)
                return
            path = await core.capture_screenshot()
            if path and os.path.isfile(path):
                await _safe_followup(interaction, file_path=path, view=MessageActionView(self.cog))
            else:
                content = response.get("content", "")[:1900]
                await interaction.followup.send(
                    f"```\n{content}\n```", view=MessageActionView(self.cog)
                )
        finally:
            core.release_lock()
            try:
                await interaction.message.delete()
            except Exception:
                pass

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class ListSelectView(discord.ui.View):
    """列表按钮：数字选择 + Exit"""

    def __init__(self, cog: "STCommands", items: list, action_type: str,
                 channel_id: int, user_id: int, char_name: str = "", timeout: float = 60):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.items = items
        self.action_type = action_type
        self.channel_id = channel_id
        self.user_id = user_id
        self.char_name = char_name
        self._message_id = None

        max_show = min(len(items), 20)
        for i in range(max_show):
            btn = discord.ui.Button(label=str(i), style=discord.ButtonStyle.secondary, row=i // 5)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

        exit_btn = discord.ui.Button(label="Exit", style=discord.ButtonStyle.danger, row=4)
        exit_btn.callback = self._on_exit
        self.add_item(exit_btn)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            await self._on_select(interaction, index)
        return callback

    async def _check_access(self, interaction: discord.Interaction) -> bool:
        if not admin.is_whitelisted(interaction.user.id, PLATFORM):
            await interaction.response.send_message(
                "管理员模式已开启，但你不在白名单中哦...", ephemeral=True
            )
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction, index: int):
        if not await self._check_access(interaction):
            return
        await interaction.response.defer()

        if self.action_type == "char_pick":
            await self._handle_char_pick(interaction, index)
        elif self.action_type in ("chat_pick", "chat_pick_for_char"):
            await self._handle_chat_pick(interaction, index)
        elif self.action_type == "user_pick":
            await self._handle_user_pick(interaction, index)

        try:
            await interaction.message.delete()
        except Exception:
            pass
        self.cog._clear_pending(interaction.user.id)

    async def _handle_char_pick(self, interaction: discord.Interaction, index: int):
        char = self.items[index]
        avatar = char.get("avatar", "")
        char_name = char.get("name", "?")

        chats = await core.fetch_character_chats(avatar)
        if not chats:
            await interaction.followup.send(f"角色 **{char_name}** 没有聊天记录。")
            return

        if len(chats) == 1:
            file_name = chats[0].get("file_name", "")
            if not file_name:
                await interaction.followup.send("无法获取聊天文件名。")
                return
            ok = await core.open_chat(file_name)
            if not ok:
                await interaction.followup.send("切换聊天失败。")
                return
            await asyncio.sleep(2)
            path = await core.capture_screenshot()
            if path and os.path.isfile(path):
                await _safe_followup(
                    interaction, content=f"已切换到: {char_name}", file_path=path,
                    view=MessageActionView(self.cog),
                )
            else:
                await interaction.followup.send("截图失败...")
        else:
            lines = [f"**{char_name} 的聊天记录 ({len(chats)}条)**"]
            for i, c in enumerate(chats[:20]):
                fname = c.get("file_name", "?").replace(".jsonl", "")
                items_count = c.get("chat_items", 0)
                lines.append(f"`{i}` — {fname}  _(消息:{items_count})_")
            if len(chats) > 20:
                lines.append(f"...还有 {len(chats) - 20} 条")
            lines.append("使用按钮选择聊天，或 `/chat <序号>` / `/exit` 退出")
            msg = _truncate("\n".join(lines))

            self.cog._set_pending(
                interaction.user.id, "chat_pick_for_char", chats,
                char_name=char_name,
            )
            view = ListSelectView(
                self.cog, chats, "chat_pick_for_char",
                channel_id=interaction.channel_id,
                user_id=interaction.user.id,
                char_name=char_name,
            )
            sent = await interaction.followup.send(msg, view=view)
            view._message_id = sent.id

    async def _handle_chat_pick(self, interaction: discord.Interaction, index: int):
        chat = self.items[index]
        file_name = chat.get("file_name", "")
        if not file_name:
            await interaction.followup.send("无法获取聊天文件名。")
            return

        ok = await core.open_chat(file_name)
        if not ok:
            await interaction.followup.send("切换聊天失败。")
            return

        await asyncio.sleep(2)
        path = await core.capture_screenshot()
        name = file_name.replace(".jsonl", "")
        if path and os.path.isfile(path):
            await _safe_followup(
                interaction, content=f"已切换到: {name}", file_path=path,
                view=MessageActionView(self.cog),
            )
        else:
            await interaction.followup.send("截图失败...")

    async def _handle_user_pick(self, interaction: discord.Interaction, index: int):
        p = self.items[index]
        ok = await core.select_persona(p["avatar_id"])
        if not ok:
            await interaction.followup.send("切换用户设定失败。")
            return
        current = await core.get_current_persona()
        await interaction.followup.send(f"已切换用户设定为: **{current}** _(序号:{index})_")

    async def _on_exit(self, interaction: discord.Interaction):
        if not await self._check_access(interaction):
            return
        self.cog._clear_pending(interaction.user.id)
        await interaction.response.send_message("已退出输入窗口。", ephemeral=True)
        try:
            await interaction.message.delete()
        except Exception:
            pass

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        self.cog._clear_pending(self.user_id)
        if self._message_id:
            try:
                channel = self.cog.bot.get_channel(self.channel_id)
                if channel:
                    msg = await channel.fetch_message(self._message_id)
                    await msg.delete()
                    await channel.send(
                        f"<@{self.user_id}> 输入窗口已过期，请重新使用命令。",
                        delete_after=10,
                    )
            except Exception as e:
                print(f"[discord] 过期消息清理失败: {e}", flush=True)


class STCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._pending = {}

    def _set_pending(self, user_id: int, action: str, data, **kwargs):
        self._pending[user_id] = {
            "action": action,
            "data": data,
            "expires_at": time.time() + 60,
            **kwargs,
        }

    def _get_pending(self, user_id: int) -> dict | None:
        p = self._pending.get(user_id)
        if not p:
            return None
        if time.time() > p["expires_at"]:
            del self._pending[user_id]
            return None
        return p

    def _clear_pending(self, user_id: int):
        self._pending.pop(user_id, None)

    async def _check_whitelist(self, interaction: discord.Interaction) -> bool:
        if not admin.is_whitelisted(interaction.user.id, PLATFORM):
            await interaction.response.send_message(
                "管理员模式已开启，但你不在白名单中哦...", ephemeral=True
            )
            return False
        return True

    async def cog_app_command_error(self, interaction: discord.Interaction, error):
        if interaction.response.is_done():
            try:
                await interaction.followup.send("执行过程中遇到网络波动，请稍后重试...")
            except Exception:
                pass
            return
        try:
            await interaction.response.send_message(
                "执行过程中遇到错误，请稍后重试...", ephemeral=True
            )
        except Exception:
            pass
        print(f"[discord] 命令异常: {error}", flush=True)
        traceback.print_exception(type(error), error, error.__traceback__)

    # ── /st ──

    @app_commands.command(name="st", description="发送消息到酒馆并获取AI回复截图")
    @app_commands.describe(message="要发送的消息内容")
    async def cmd_st(self, interaction: discord.Interaction, message: str):
        if not await self._check_whitelist(interaction):
            return
        if not core.acquire_lock():
            await interaction.response.send_message(
                "有正在处理中的消息，请稍后再试...或使用 /stop 中止当前操作",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        try:
            result = await core.send_message(message)
            if result is None or not result.get("content"):
                await interaction.followup.send("消息发送失败或等待回复超时...")
                return

            path = result.get("screenshot_path")
            if path and os.path.isfile(path):
                await interaction.followup.send(
                    view=MessageActionView(self),
                    file=discord.File(path),
                )
            else:
                content = result["content"][:1900]
                view = MessageActionView(self)
                await interaction.followup.send(f"```\n{content}\n```", view=view)
        finally:
            core.release_lock()

    # ── /stop ──

    @app_commands.command(name="stop", description="停止当前正在生成的AI回复")
    async def cmd_stop(self, interaction: discord.Interaction):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()
        ok = await core.cancel_processing()
        core.release_lock()
        if ok:
            await interaction.followup.send("已中止当前生成。")
        else:
            await interaction.followup.send("没有正在进行的生成。")

    # ── /lastmsg ──

    @app_commands.command(name="lastmsg", description="截取酒馆最后一条消息")
    async def cmd_lastmsg(self, interaction: discord.Interaction):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()
        path = await core.capture_screenshot()
        if path and os.path.isfile(path):
            await interaction.followup.send(
                view=MessageActionView(self),
                file=discord.File(path),
            )
        else:
            await interaction.followup.send("截图失败，请稍后重试...")

    # ── /ss ──

    @app_commands.command(name="ss", description="全页截取酒馆当前界面")
    async def cmd_ss(self, interaction: discord.Interaction):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()
        path = await core.capture_full_screenshot()
        if path and os.path.isfile(path):
            await _safe_followup(interaction, file_path=path)
        else:
            await interaction.followup.send("截图失败，请稍后重试...")

    # ── /rf ──

    @app_commands.command(name="rf", description="刷新酒馆页面")
    async def cmd_rf(self, interaction: discord.Interaction):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()
        ok = await core.refresh_page()
        if not ok:
            await interaction.followup.send("页面刷新失败...")
            return
        path = await core.capture_full_screenshot()
        if path and os.path.isfile(path):
            await _safe_followup(interaction, content="页面已刷新:", file_path=path)
        else:
            await interaction.followup.send("页面已刷新，但截图失败。")

    # ── /del ──

    @app_commands.command(name="del", description="删除酒馆当前聊天最后N条消息")
    @app_commands.describe(n="删除条数（1或2）")
    async def cmd_del(self, interaction: discord.Interaction, n: int = 1):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()
        ok = await core.delete_messages(n)
        if not ok:
            await interaction.followup.send("删除消息失败。")
            return
        await asyncio.sleep(1)
        path = await core.capture_screenshot()
        if path and os.path.isfile(path):
            await interaction.followup.send(
                content=f"已删除最后 {n} 条消息:",
                view=MessageActionView(self),
                file=discord.File(path),
            )
        else:
            await interaction.followup.send(
                f"已删除最后 {n} 条消息。", view=MessageActionView(self)
            )

    # ── /left ──

    @app_commands.command(name="left", description="切换到上一个备选回复（左翻页）")
    async def cmd_left(self, interaction: discord.Interaction):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()
        ok = await core.swipe_left()
        if not ok:
            await interaction.followup.send("左翻页失败，没有更多备选回复或当前不在聊天中。")
            return
        path = await core.capture_screenshot()
        if path and os.path.isfile(path):
            await interaction.followup.send(
                view=MessageActionView(self),
                file=discord.File(path),
            )
        else:
            await interaction.followup.send("截图失败，请稍后重试...")

    # ── /right ──

    @app_commands.command(name="right", description="切换到下一个备选回复（右翻页）")
    async def cmd_right(self, interaction: discord.Interaction):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()
        if not core.acquire_lock():
            await interaction.followup.send("有正在处理中的消息，请稍后再试...")
            return

        try:
            result = await core.swipe_right()
            if result is None:
                await interaction.followup.send("右翻页失败，当前不在聊天中。")
                return

            if result == "generating":
                response = await core.wait_for_response()
                if not response:
                    await interaction.followup.send("等待LLM回复超时...")
                    return

            path = await core.capture_screenshot()
            if path and os.path.isfile(path):
                await interaction.followup.send(
                    view=MessageActionView(self),
                    file=discord.File(path),
                )
            else:
                await interaction.followup.send("截图失败，请稍后重试...")
        finally:
            core.release_lock()

    # ── /regenerate ──

    @app_commands.command(name="regenerate", description="重新生成AI回复")
    async def cmd_regenerate(self, interaction: discord.Interaction):
        if not await self._check_whitelist(interaction):
            return
        if not core.acquire_lock():
            await interaction.response.send_message(
                "有正在处理中的消息，请稍后再试...或使用 /stop 中止", ephemeral=True
            )
            return

        await interaction.response.defer()
        try:
            ok = await core.regenerate()
            if not ok:
                await interaction.followup.send("重新生成触发失败...")
                return

            response = await core.wait_for_response()
            if not response:
                await interaction.followup.send("等待LLM回复超时...")
                return

            path = await core.capture_screenshot()
            if path and os.path.isfile(path):
                await interaction.followup.send(
                    view=MessageActionView(self),
                    file=discord.File(path),
                )
            else:
                content = response.get("content", "")[:1900]
                view = MessageActionView(self)
                await interaction.followup.send(f"```\n{content}\n```", view=view)
        finally:
            core.release_lock()

    # ── /chat ──

    @app_commands.command(name="chat", description="查看最近聊天列表或切换到指定聊天")
    @app_commands.describe(index="聊天序号（不填则列出所有聊天）")
    async def cmd_chat(self, interaction: discord.Interaction, index: int = -1):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()

        pending = self._get_pending(interaction.user.id)

        if index >= 0 and pending and pending["action"] == "chat_pick_for_char":
            chats = pending["data"]
            char_name = pending.get("char_name", "")
            if index >= len(chats):
                await interaction.followup.send(f"序号超出范围，共 {len(chats)} 条聊天。")
                return
            chat = chats[index]
            file_name = chat.get("file_name", "")
            if not file_name:
                await interaction.followup.send("无法获取聊天文件名。")
                return
            ok = await core.open_chat(file_name)
            if not ok:
                await interaction.followup.send("切换聊天失败。")
                return
            self._clear_pending(interaction.user.id)
            await asyncio.sleep(2)
            path = await core.capture_screenshot()
            name = file_name.replace(".jsonl", "")
            if path and os.path.isfile(path):
                await _safe_followup(
                    interaction, content=f"已切换到: {name}", file_path=path,
                    view=MessageActionView(self),
                )
            else:
                await interaction.followup.send("截图失败...")
            return

        chats = await core.fetch_recent_chats()
        if not chats:
            await interaction.followup.send("获取聊天列表失败。")
            return

        if index >= 0:
            if pending and pending["action"] == "chat_pick":
                chats = pending["data"]

            if index >= len(chats):
                await interaction.followup.send(f"序号超出范围，共 {len(chats)} 条聊天。")
                return

            chat = chats[index]
            file_name = chat.get("file_name", "")
            if not file_name:
                await interaction.followup.send("无法获取聊天文件名。")
                return

            ok = await core.open_chat(file_name)
            if not ok:
                await interaction.followup.send("切换聊天失败。")
                return

            self._clear_pending(interaction.user.id)
            await asyncio.sleep(2)
            path = await core.capture_screenshot()
            if path and os.path.isfile(path):
                name = file_name.replace(".jsonl", "")
                await _safe_followup(
                    interaction, content=f"已切换到: {name}", file_path=path,
                    view=MessageActionView(self),
                )
            else:
                await interaction.followup.send("截图失败...")
            return

        self._set_pending(interaction.user.id, "chat_pick", chats)
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

        msg = _truncate("\n".join(lines))

        view = ListSelectView(self, chats, "chat_pick",
                              channel_id=interaction.channel_id,
                              user_id=interaction.user.id)
        sent = await interaction.followup.send(msg, view=view)
        view._message_id = sent.id

    # ── /char ──

    @app_commands.command(name="char", description="查看角色卡列表或选择角色")
    @app_commands.describe(index="角色序号（不填则列出所有角色）")
    async def cmd_char(self, interaction: discord.Interaction, index: int = -1):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()

        pending = self._get_pending(interaction.user.id)

        if index >= 0 and pending and pending["action"] == "char_pick":
            chars = pending["data"]
            if index >= len(chars):
                await interaction.followup.send(f"序号超出范围，共 {len(chars)} 个角色。")
                return

            char = chars[index]
            avatar = char.get("avatar", "")
            char_name = char.get("name", "?")

            chats = await core.fetch_character_chats(avatar)
            if not chats:
                await interaction.followup.send(f"角色 **{char_name}** 没有聊天记录。")
                self._clear_pending(interaction.user.id)
                return

            if len(chats) == 1:
                file_name = chats[0].get("file_name", "")
                if not file_name:
                    await interaction.followup.send("无法获取聊天文件名。")
                    self._clear_pending(interaction.user.id)
                    return
                ok = await core.open_chat(file_name)
                if not ok:
                    await interaction.followup.send("切换聊天失败。")
                    self._clear_pending(interaction.user.id)
                    return
                self._clear_pending(interaction.user.id)
                await asyncio.sleep(2)
                path = await core.capture_screenshot()
                if path and os.path.isfile(path):
                    await _safe_followup(
                        interaction, content=f"已切换到: {char_name}", file_path=path,
                        view=MessageActionView(self),
                    )
                else:
                    await interaction.followup.send("截图失败...")
            else:
                lines = [f"**{char_name} 的聊天记录 ({len(chats)}条)**"]
                for i, c in enumerate(chats[:20]):
                    fname = c.get("file_name", "?").replace(".jsonl", "")
                    items = c.get("chat_items", 0)
                    lines.append(f"`{i}` — {fname}  _(消息:{items})_")
                if len(chats) > 20:
                    lines.append(f"...还有 {len(chats) - 20} 条")
                lines.append("使用按钮选择聊天，或 `/chat <序号>` / `/exit` 退出")

                msg = _truncate("\n".join(lines))

                self._set_pending(
                    interaction.user.id, "chat_pick_for_char", chats,
                    char_name=char_name,
                )
                view = ListSelectView(
                    self, chats, "chat_pick_for_char",
                    channel_id=interaction.channel_id,
                    user_id=interaction.user.id,
                    char_name=char_name,
                )
                sent = await interaction.followup.send(msg, view=view)
                view._message_id = sent.id
            return

        chars = await core.fetch_characters()
        if not chars:
            await interaction.followup.send("获取角色卡列表失败。")
            return

        if index >= 0:
            if index >= len(chars):
                await interaction.followup.send(f"序号超出范围，共 {len(chars)} 个角色。")
                return

            char = chars[index]
            avatar = char.get("avatar", "")
            char_name = char.get("name", "?")

            chats = await core.fetch_character_chats(avatar)
            if not chats:
                await interaction.followup.send(f"角色 **{char_name}** 没有聊天记录。")
                return

            if len(chats) == 1:
                file_name = chats[0].get("file_name", "")
                if not file_name:
                    await interaction.followup.send("无法获取聊天文件名。")
                    return
                ok = await core.open_chat(file_name)
                if not ok:
                    await interaction.followup.send("切换聊天失败。")
                    return
                await asyncio.sleep(2)
                path = await core.capture_screenshot()
                if path and os.path.isfile(path):
                    await _safe_followup(
                        interaction, content=f"已切换到: {char_name}", file_path=path,
                        view=MessageActionView(self),
                    )
                else:
                    await interaction.followup.send("截图失败...")
            else:
                lines = [f"**{char_name} 的聊天记录 ({len(chats)}条)**"]
                for i, c in enumerate(chats[:20]):
                    fname = c.get("file_name", "?").replace(".jsonl", "")
                    items = c.get("chat_items", 0)
                    lines.append(f"`{i}` — {fname}  _(消息:{items})_")
                if len(chats) > 20:
                    lines.append(f"...还有 {len(chats) - 20} 条")
                lines.append("使用按钮选择聊天，或 `/chat <序号>` / `/exit` 退出")

                msg = _truncate("\n".join(lines))

                self._set_pending(
                    interaction.user.id, "chat_pick_for_char", chats,
                    char_name=char_name,
                )
                view = ListSelectView(
                    self, chats, "chat_pick_for_char",
                    channel_id=interaction.channel_id,
                    user_id=interaction.user.id,
                    char_name=char_name,
                )
                sent = await interaction.followup.send(msg, view=view)
                view._message_id = sent.id
            return

        self._set_pending(interaction.user.id, "char_pick", chars)
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

        msg = _truncate("\n".join(lines))

        view = ListSelectView(self, chars, "char_pick",
                              channel_id=interaction.channel_id,
                              user_id=interaction.user.id)
        sent = await interaction.followup.send(msg, view=view)
        view._message_id = sent.id

    # ── /user ──

    @app_commands.command(name="user", description="查看用户设定列表或选择用户设定")
    @app_commands.describe(index="用户设定序号（不填则列出所有用户设定）")
    async def cmd_user(self, interaction: discord.Interaction, index: int = -1):
        if not await self._check_whitelist(interaction):
            return
        await interaction.response.defer()

        pending = self._get_pending(interaction.user.id)

        if index >= 0 and pending and pending["action"] == "user_pick":
            personas = pending["data"]
            if index >= len(personas):
                await interaction.followup.send(f"序号超出范围，共 {len(personas)} 个用户设定。")
                return
            p = personas[index]
            ok = await core.select_persona(p["avatar_id"])
            if not ok:
                await interaction.followup.send("切换用户设定失败。")
                return
            self._clear_pending(interaction.user.id)
            current = await core.get_current_persona()
            await interaction.followup.send(f"已切换用户设定为: **{current}** _(序号:{index})_")
            return

        personas = await core.fetch_personas()
        if not personas:
            await interaction.followup.send("获取用户设定列表失败。")
            return

        if index >= 0:
            if index >= len(personas):
                await interaction.followup.send(f"序号超出范围，共 {len(personas)} 个用户设定。")
                return

            p = personas[index]
            ok = await core.select_persona(p["avatar_id"])
            if not ok:
                await interaction.followup.send("切换用户设定失败。")
                return

            current = await core.get_current_persona()
            await interaction.followup.send(f"已切换用户设定为: **{current}** _(序号:{index})_")
            return

        self._set_pending(interaction.user.id, "user_pick", personas)
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

        msg = _truncate("\n".join(lines))

        view = ListSelectView(self, personas, "user_pick",
                              channel_id=interaction.channel_id,
                              user_id=interaction.user.id)
        sent = await interaction.followup.send(msg, view=view)
        view._message_id = sent.id

    # ── /exit ──

    @app_commands.command(name="exit", description="退出当前输入窗口")
    async def cmd_exit(self, interaction: discord.Interaction):
        if not await self._check_whitelist(interaction):
            return
        self._clear_pending(interaction.user.id)
        await interaction.response.send_message("已退出输入窗口。", ephemeral=True)


async def setup(bot):
    await bot.add_cog(STCommands(bot))
