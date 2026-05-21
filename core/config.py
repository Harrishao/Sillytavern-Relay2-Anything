"""
统一配置管理 — YAML 格式
"""
import os
import yaml
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshot")
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")


@dataclass
class STConfig:
    url: str = "http://127.0.0.1:8000"
    headless: bool = True
    viewport_width: int = 600
    refresh_delay: int = 3
    chat_switch_delay: int = 2


@dataclass
class PlatformConfig:
    enabled: bool = False
    admins: list = field(default_factory=list)
    admin_mode: bool = False


@dataclass
class TelegramConfig(PlatformConfig):
    bot_token: str = ""


@dataclass
class DiscordConfig(PlatformConfig):
    bot_token: str = ""


@dataclass
class NapcatConfig(PlatformConfig):
    host: str = "0.0.0.0"
    port: int = 6199


@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 5000


@dataclass
class Config:
    st: STConfig = field(default_factory=STConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    napcat: NapcatConfig = field(default_factory=NapcatConfig)
    web: WebConfig = field(default_factory=WebConfig)


def _parse_platform(raw: dict, cls):
    """从原始 YAML dict 解析平台配置"""
    if raw is None:
        return cls()
    kwargs = {}
    for f in cls.__dataclass_fields__:
        if f in raw:
            kwargs[f] = raw[f]
    return cls(**kwargs)


def load_config(path: str = None) -> Config:
    """加载 YAML 配置文件"""
    path = path or CONFIG_PATH
    if not os.path.isfile(path):
        print(f"[core] 未找到 {path}，使用默认配置并自动生成")
        default_cfg = Config()
        save_config(default_cfg, path)
        return default_cfg

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return Config(
        st=STConfig(**raw.get("st", {})),
        telegram=_parse_platform(raw.get("telegram"), TelegramConfig),
        discord=_parse_platform(raw.get("discord"), DiscordConfig),
        napcat=_parse_platform(raw.get("napcat"), NapcatConfig),
        web=WebConfig(**raw.get("web", {})),
    )


def save_config(config: Config, path: str = None) -> bool:
    """保存配置到 YAML 文件"""
    path = path or CONFIG_PATH
    try:
        data = {
            "st": config.st.__dict__,
            "telegram": config.telegram.__dict__,
            "discord": config.discord.__dict__,
            "napcat": config.napcat.__dict__,
            "web": config.web.__dict__,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        return True
    except Exception as e:
        print(f"[core] 保存配置失败: {e}")
        return False


# 全局配置实例
config: Config = load_config()


def reload_config():
    global config
    config = load_config()
    return config
