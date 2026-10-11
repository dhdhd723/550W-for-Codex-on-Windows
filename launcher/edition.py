"""Portable edition policy; contains no machine-specific configuration."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys


@dataclass(frozen=True)
class Edition:
    name: str = "550W Launcher"
    mode: str = "full"
    sound: bool = True
    data_folder: str = "550WLauncher"
    fixed_mode: bool = False

    @classmethod
    def parse(cls, raw: dict) -> "Edition":
        if not isinstance(raw, dict):
            raise ValueError("版本信息无效")
        result = cls(**raw)
        if result.name not in ("550W Launcher", "550W简洁版", "550W完整版"):
            raise ValueError("版本名称无效")
        if result.mode not in ("brief", "full"):
            raise ValueError("版本模式无效")
        if type(result.sound) is not bool or type(result.fixed_mode) is not bool:
            raise ValueError("版本声音设置无效")
        if not isinstance(result.data_folder, str) or not re.fullmatch(r"550W[A-Za-z0-9-]{0,32}", result.data_folder):
            raise ValueError("版本数据目录无效")
        if result.name == "550W简洁版" and (result.mode != "brief" or result.sound is not False):
            raise ValueError("简洁版必须为无声标识模式")
        return result


def read_edition(path: Path | None = None) -> Edition:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    path = path or root / "edition.json"
    if not path.exists():
        return Edition()
    return Edition.parse(json.loads(path.read_text(encoding="utf-8-sig")))


CURRENT = read_edition()
