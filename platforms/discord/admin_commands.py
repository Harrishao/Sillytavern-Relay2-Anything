"""Discord 管理员命令 Cog"""
import discord
from discord import app_commands
from discord.ext import commands

from core import admin

PLATFORM = "discord"


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="admin", description="切换管理员模式")
    async def cmd_admin(self, interaction: discord.Interaction):
        if not admin.is_l1_admin(interaction.user.id, PLATFORM):
            await interaction.response.send_message("你没有权限执行此操作。", ephemeral=True)
            return

        new_state = admin.toggle_admin_mode(PLATFORM)
        state_str = "开启" if new_state else "关闭"
        await interaction.response.send_message(f"已{state_str}管理员模式。")

    @app_commands.command(name="admin_add", description="将用户加入白名单")
    @app_commands.describe(user="要加入白名单的用户")
    async def cmd_admin_add(self, interaction: discord.Interaction, user: discord.User):
        if not admin.is_l1_admin(interaction.user.id, PLATFORM):
            await interaction.response.send_message("你没有权限执行此操作。", ephemeral=True)
            return

        admin.add_whitelist(user.id)
        await interaction.response.send_message(f"已将 {user.mention} (ID: {user.id}) 加入白名单。")

    @app_commands.command(name="admin_del", description="将用户移出白名单")
    @app_commands.describe(user="要移出白名单的用户")
    async def cmd_admin_del(self, interaction: discord.Interaction, user: discord.User):
        if not admin.is_l1_admin(interaction.user.id, PLATFORM):
            await interaction.response.send_message("你没有权限执行此操作。", ephemeral=True)
            return

        admin.remove_whitelist(user.id)
        await interaction.response.send_message(f"已将 {user.mention} (ID: {user.id}) 移出白名单。")


async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
