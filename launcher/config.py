from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from .edition import CURRENT


def data_dir() -> Path:
    # This is launcher-owned state, separate from .codex and the official package.
    # source-note: dhdhd723
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise RuntimeError("Windows LOCALAPPDATA is unavailable")
    folder = Path(base) / CURRENT.data_folder
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@dataclass(frozen=True)
class Config:
    enabled: bool = True
    mode: str = CURRENT.mode
    color: str = "amber"
    timeout_seconds: int = 90
    target_executable: str = ""
    sound: bool = CURRENT.sound

    @classmethod
    def parse(cls, raw: dict) -> "Config":
        if not isinstance(raw, dict):
            raise ValueError("配置必须是 JSON 对象")
        enabled = raw.get("enabled", True)
        mode = raw.get("mode", CURRENT.mode)
        color = raw.get("color", "amber")
        timeout = raw.get("timeout_seconds", 90)
        target = raw.get("target_executable", "")
        sound = raw.get("sound", CURRENT.sound)
        if type(enabled) is not bool:
            raise ValueError("enabled 必须是 true 或 false")
        if type(sound) is not bool:
            raise ValueError("sound 必须是 true 或 false")
        if mode not in ("brief", "full") or color not in ("amber", "green", "cyan", "white"):
            raise ValueError("动画模式或配色无效")
        if type(timeout) is not int or not 20 <= timeout <= 300:
            raise ValueError("超时应为 20–300 秒")
        if not isinstance(target, str):
            raise ValueError("target_executable 必须是路径字符串")
        return cls(enabled, mode, color, timeout, target, sound)


def load(path: Path | None = None) -> Config:
    path = path or data_dir() / "config.json"
    if not path.exists():
        return Config()
    return Config.parse(json.loads(path.read_text(encoding="utf-8-sig")))


def save(config: Config, path: Path | None = None) -> None:
    path = path or data_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)
