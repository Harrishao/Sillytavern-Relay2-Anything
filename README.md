# SillyTavern Relay2 Anything

统一的多平台 SillyTavern 消息中继，支持 **Telegram**、**Discord**、**NapCat (QQ)** 三平台同时运行，附带 Web 管理面板。

理论上其他支持 OneBot v11 框架的实现端也能兼容，并不局限于NapCat

## 项目结构

```
Sillytavern-Relay2-Anything/
├── main.py                 # 入口：加载配置、初始化浏览器、启动 Web 面板
├── config.yaml             # 统一配置文件（复制自 config.yaml.example）
├── config.yaml.example     # 配置模板
├── requirements.txt        # Python 依赖
├── core/                   # 平台无关的共享内核
│   ├── config.py           # YAML 配置加载/保存
│   ├── browser.py          # Playwright 浏览器管理
│   ├── api.py              # SillyTavern JS API 封装
│   ├── interaction.py      # 消息注入、等待回复、翻页、重新生成
│   ├── screenshot.py       # 消息截图 + 全页截图
│   ├── admin.py            # L1/L2 管理员 + 白名单系统
│   ├── render.py           # Markdown → 图片渲染（NapCat 用）
│   └── __init__.py         # 处理锁 acquire/release
├── platforms/              # 平台适配器
│   ├── telegram/
│   │   └── bot.py          # python-telegram-bot Application + 命令处理器
│   ├── discord/
│   │   ├── bot.py          # discord.py Bot + Cog 加载
│   │   ├── st_commands.py  # ST 命令 Cog + 交互按钮 View
│   │   └── admin_commands.py
│   └── napcat/
│       ├── server.py       # OneBot v11 WebSocket 服务器
│       ├── responder.py    # 命令解析 + 路由 + pending 状态
│       └── echo.py         # OneBot v11 消息/图片发送
├── web/                    # Web 管理面板 (FastAPI)
│   ├── server.py           # API + 平台生命周期管理 + 日志轮询
│   ├── templates/
│   │   └── index.html      # 单页管理面板
│   └── static/
│       └── style.css       # 暗色主题样式
└── screenshot/             # 截图输出目录
```

## 功能特性

- **多平台统一**：一套代码同时服务 Telegram / Discord / QQ（NapCat），共享 SillyTavern 浏览器实例
- **消息中继**：通过各平台发送消息到酒馆，截图返回 AI 回复
- **交互按钮**：左翻页/右翻页/重新生成，Discord 和 Telegram 支持按钮交互
- **列表操作**：角色卡/聊天列表/用户设定的浏览和切换
- **Markdown 渲染**：NapCat (QQ) 平台自动将列表渲染为暗色主题 PNG 图片
- **处理锁**：全局锁防止多个平台同时操作导致状态混乱
- **管理员系统**：L1 管理员（config 配置）+ L2 白名单（JSON 持久化），支持管理员模式切换
- **Web 管理面板**：
  - 各平台独立启停（运行时热切换，无需重启）
  - Token 输入框默认密码遮蔽，点击"显示"查看明文
  - 管理员 ID 标签化管理（添加/删除）
  - 实时日志轮询

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置

```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入各平台的 bot_token 和管理员 ID
```

### 3. 启动

```bash
python main.py
```

访问 `http://127.0.0.1:4396` 打开 Web 管理面板，也可在面板中直接修改配置和启停各平台。

## 配置说明

```yaml
st:                       # SillyTavern 连接
  url: "http://127.0.0.1:8000"
  headless: true          # 无头模式
  viewport_width: 600
  refresh_delay: 3
  chat_switch_delay: 2

telegram:
  enabled: false          # 启动时是否自动运行
  bot_token: ""           # @BotFather 获取
  admins: []              # Telegram 用户数字 ID
  admin_mode: false

discord:
  enabled: false
  bot_token: ""           # Discord Developer Portal 获取
  admins: []
  admin_mode: false

napcat:
  enabled: false
  host: "0.0.0.0"        # 监听地址
  port: 6199              # 监听端口（NapCat 反向 WS 连接此端口）
  admins: []
  admin_mode: false

web:
  host: "127.0.0.1"
  port: 4396
```

## 命令列表

所有平台均支持以下命令：

| 命令 | 说明 |
|------|------|
| `/st <消息>` | 发送消息到酒馆，获取 AI 回复截图 |
| `/stop` | 停止当前生成 |
| `/lastmsg` | 截取最后一条消息 |
| `/left` | 左翻页（上一条备选回复） |
| `/right` | 右翻页（下一条备选回复） |
| `/regenerate` | 重新生成 AI 回复 |
| `/chat [序号]` | 查看/切换聊天 |
| `/char [序号]` | 查看/选择角色卡 |
| `/user [序号]` | 查看/选择用户设定 |
| `/del [1\|2]` | 删除最后 N 条消息 |
| `/ss` | 全页截图 |
| `/rf` | 刷新酒馆页面 |
| `/exit` | 退出输入窗口 |
| `/admin` | （L1 管理员）切换管理员模式 |
| `/admin.add <ID>` | 加入白名单 |
| `/admin.del <ID>` | 移出白名单 |

QQ 端额外支持：
- `/regen`（等同于 `/regenerate`）
- `/msg`（等同于 `/chat`,因为QQ桌面端输入`/cha`会变成小表情）
- 管道串联命令：用 `|` 分隔，如 `/rf|/char 0|/chat 1` 刷新页面后，直接切换到第0个角色的第1个聊天

## 架构

```
 Telegram ──┐
 Discord  ──┼── processing lock ── Playwright Browser ── SillyTavern
 NapCat   ──┘
                 Web Panel (FastAPI)
```

- **core/** 提供平台无关的 ST 操作接口（所有函数均为 async）
- **platforms/** 各平台适配器监听用户消息，调用 core 完成操作并回传结果
- **web/server.py** 管理平台 Task 生命周期，支持运行时启停；日志通过轮询推送到前端
- **处理锁** (`core.acquire_lock/release_lock`) 确保同一时间只有一个平台操作浏览器

## 常见问题

**Q: 如何获取 Telegram Bot Token？**
A: 在 Telegram 找 @BotFather，发送 `/newbot` 创建。

**Q: 如何获取 Discord Bot Token？**
A: 在 [Discord Developer Portal](https://discord.com/developers/applications) 创建 Application → Bot，复制 Token。需要勾选 `applications.commands` 和 `bot` 权限。

**Q: NapCat 如何配置？**
A: NapCat 使用反向 WebSocket 连接到本项目的 `ws://host:port`。在 NapCat 的 OneBot 配置中设置反向 WS 地址指向本项目。
