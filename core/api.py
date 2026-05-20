"""
SillyTavern API 交互模块
通过浏览器 JS 上下文调用 ST 内部 API
"""
from .browser import get_page, dismiss_toasts
from .config import config


async def fetch_characters() -> list:
    page = get_page()
    try:
        data = await page.evaluate(
            """async () => {
                const ctx = window.SillyTavern.getContext();
                const headers = ctx.getRequestHeaders();
                const resp = await fetch('/api/characters/all', {
                    method: 'POST', headers: headers, body: JSON.stringify({}),
                });
                if (!resp.ok) return [];
                return await resp.json();
            }"""
        )
        print(f"[core] 获取到 {len(data)} 个角色卡", flush=True)
        return data
    except Exception as e:
        print(f"[core] 获取角色卡列表失败: {e}", flush=True)
        return []


async def fetch_recent_chats() -> list:
    page = get_page()
    try:
        data = await page.evaluate(
            """async () => {
                const ctx = window.SillyTavern.getContext();
                const headers = ctx.getRequestHeaders();
                const resp = await fetch('/api/chats/recent', {
                    method: 'POST', headers: headers, body: JSON.stringify({}),
                });
                if (!resp.ok) return [];
                return await resp.json();
            }"""
        )
        print(f"[core] 获取到 {len(data)} 条最近聊天", flush=True)
        return data
    except Exception as e:
        print(f"[core] 获取最近聊天失败: {e}", flush=True)
        return []


async def fetch_character_chats(avatar_url: str) -> list:
    page = get_page()
    try:
        data = await page.evaluate(
            """async (avatar_url) => {
                const ctx = window.SillyTavern.getContext();
                const headers = ctx.getRequestHeaders();
                const resp = await fetch('/api/characters/chats', {
                    method: 'POST', headers: headers,
                    body: JSON.stringify({avatar_url: avatar_url}),
                });
                if (!resp.ok) return [];
                return await resp.json();
            }""",
            avatar_url,
        )
        print(f"[core] 获取到角色({avatar_url})的 {len(data)} 条聊天记录", flush=True)
        return data
    except Exception as e:
        print(f"[core] 获取角色聊天记录失败: {e}", flush=True)
        return []


async def open_chat(file_name: str) -> bool:
    page = get_page()
    try:
        clean_file = file_name.replace(".jsonl", "")
        await page.evaluate(
            """async (file_name) => {
                const ctx = window.SillyTavern.getContext();
                await ctx.getCharacters();
                const cleanName = file_name.replace('.jsonl', '');
                const dashIdx = cleanName.lastIndexOf(' - ');
                let chId = -1;
                if (dashIdx > 0) {
                    const charName = cleanName.substring(0, dashIdx);
                    for (let i = 0; i < ctx.characters.length; i++) {
                        if (ctx.characters[i] && ctx.characters[i].chat === cleanName) {
                            chId = i; break;
                        }
                    }
                    if (chId === -1) {
                        for (let i = 0; i < ctx.characters.length; i++) {
                            if (ctx.characters[i] && ctx.characters[i].name === charName) {
                                chId = i; break;
                            }
                        }
                    }
                }
                if (chId === -1) throw new Error('找不到对应角色: ' + file_name);
                await ctx.selectCharacterById(chId, {switchMenu: true});
                await ctx.openCharacterChat(cleanName);
                return true;
            }""",
            clean_file,
        )
        await page.wait_for_timeout(config.st.chat_switch_delay * 1000)
        await dismiss_toasts()
        print(f"[core] 已打开聊天: {file_name}", flush=True)
        return True
    except Exception as e:
        print(f"[core] 打开聊天失败: {e}", flush=True)
        return False


async def delete_messages(n: int = 1) -> bool:
    if n not in (1, 2):
        n = 1
    page = get_page()
    try:
        await page.evaluate(
            """async (n) => {
                const ctx = window.SillyTavern.getContext();
                await ctx.executeSlashCommands(`/del ${n}`);
            }""",
            n,
        )
        await page.wait_for_timeout(500)
        print(f"[core] 已删除最后 {n} 条消息", flush=True)
        return True
    except Exception as e:
        print(f"[core] 删除消息失败: {e}", flush=True)
        return False


async def delete_chat(file_name: str) -> bool:
    page = get_page()
    try:
        clean_file = file_name.replace(".jsonl", "")
        await page.evaluate(
            """async (file_name) => {
                const ctx = window.SillyTavern.getContext();
                const headers = ctx.getRequestHeaders();
                const dashIdx = file_name.lastIndexOf(' - ');
                if (dashIdx < 0) throw new Error('Invalid file name');
                const charName = file_name.substring(0, dashIdx);
                let avatar = '';
                for (let i = 0; i < ctx.characters.length; i++) {
                    if (ctx.characters[i] && ctx.characters[i].name === charName) {
                        avatar = ctx.characters[i].avatar;
                        break;
                    }
                }
                const resp = await fetch('/api/chats/delete', {
                    method: 'POST', headers: headers,
                    body: JSON.stringify({
                        ch_name: charName, file_name: file_name, avatar_url: avatar,
                    }),
                });
                if (!resp.ok) throw new Error('Delete failed: ' + resp.status);
                return true;
            }""",
            clean_file,
        )
        await page.wait_for_timeout(500)
        print(f"[core] 已删除聊天: {clean_file}", flush=True)
        return True
    except Exception as e:
        print(f"[core] 删除聊天失败: {e}", flush=True)
        return False


async def fetch_personas() -> list:
    page = get_page()
    try:
        data = await page.evaluate(
            """() => {
                const containers = document.querySelectorAll('#user_avatar_block .avatar-container');
                if (!containers.length) return [];
                const result = [];
                containers.forEach(c => {
                    const nameEl = c.querySelector('.ch_name');
                    const descEl = c.querySelector('.ch_description');
                    result.push({
                        avatar_id: c.getAttribute('data-avatar-id') || '',
                        name: nameEl ? nameEl.textContent.trim() : '',
                        description: descEl ? descEl.textContent.trim().substring(0, 200) : '',
                    });
                });
                return result;
            }"""
        )
        print(f"[core] 获取到 {len(data)} 个用户设定", flush=True)
        return data
    except Exception as e:
        print(f"[core] 获取用户设定列表失败: {e}", flush=True)
        return []


async def select_persona(avatar_id: str) -> bool:
    page = get_page()
    try:
        result = await page.evaluate(
            """(avatar_id) => {
                const container = document.querySelector(`#user_avatar_block .avatar-container[data-avatar-id="${avatar_id}"]`);
                if (!container) return false;
                container.click();
                return true;
            }""",
            avatar_id,
        )
        if result:
            print(f"[core] 已选择用户设定: {avatar_id}", flush=True)
        else:
            print(f"[core] 未找到用户设定: {avatar_id}", flush=True)
        return bool(result)
    except Exception as e:
        print(f"[core] 选择用户设定失败: {e}", flush=True)
        return False


async def get_current_persona() -> str:
    page = get_page()
    try:
        name = await page.evaluate(
            "() => window.SillyTavern.getContext().name1 || ''"
        )
        return name
    except Exception as e:
        print(f"[core] 获取当前用户设定失败: {e}", flush=True)
        return ""
