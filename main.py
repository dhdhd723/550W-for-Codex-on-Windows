from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

from launcher.config import data_dir, load
from launcher.edition import CURRENT


def main() -> int:
    parser = argparse.ArgumentParser(description=CURRENT.name + " — 独立开屏启动器")
    parser.add_argument("--preview", action="store_true", help="只预览动画，不启动官方应用")
    parser.add_argument("--settings", action="store_true", help="设置模式、配色和启动入口")
    parser.add_argument("--diagnose", action="store_true", help="只读检测，写出 diagnostics.json")
    parser.add_argument("--mode", choices=("brief", "full"))
    parser.add_argument("--color", choices=("amber", "green", "cyan", "white"))
    parser.add_argument("--no-animation", action="store_true")
    parser.add_argument("--target", help="手动指定官方桌面 GUI EXE；不能指定 codex CLI")
    parser.add_argument("--timeout", type=int, help="启动等待上限，20–300 秒")
    args = parser.parse_args()
    folder = None
    try:
        folder = data_dir()
        handler = RotatingFileHandler(folder / "launcher.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
        logging.info("launcher_start preview=%s settings=%s", args.preview, args.settings)
        config = load()
        config = replace(config, **{k: v for k, v in {
            "mode": args.mode, "color": args.color, "target_executable": args.target,
            "timeout_seconds": args.timeout,
        }.items() if v is not None})
        if args.no_animation:
            config = replace(config, enabled=False)
        # Validate overrides too.
        config = type(config).parse(asdict(config))
        if CURRENT.fixed_mode:
            config = replace(config, mode=CURRENT.mode, sound=CURRENT.sound)
        if args.diagnose:
            from launcher.windows import discover_targets, find_ready_window
            targets = discover_targets(config.target_executable or None)
            result = {"configuration": asdict(config), "targets": [asdict(t) for t in targets],
                      "windows": [asdict(w) if (w := find_ready_window(t, exclude_pid=os.getpid())) else None for t in targets],
                      "readiness": "Win32 responsive main-window proxy, not authenticated/agent readiness"}
            content = json.dumps(result, ensure_ascii=False, indent=2)
            destination = folder / "diagnostics.json"
            destination.write_text(content + "\n", encoding="utf-8")
            if sys.stdout is not None:
                print(content)
            else:
                native_message(f"检测结果已保存：\n{destination}", 0x40)
            return 0
        from launcher.app import run
        return run(config, preview=args.preview, settings=args.settings)
    except Exception as error:
        logging.exception("launcher_failed")
        if sys.stderr is not None:
            print(str(error), file=sys.stderr)
        if sys.platform == "win32":
            log_location = str(folder / "launcher.log") if folder else "日志目录不可用"
            native_message(f"启动器未能启动：{error}\n\n日志：{log_location}", 0x10)
        return 1


def native_message(message: str, icon: int):
    import ctypes
    from ctypes import wintypes
    function = ctypes.windll.user32.MessageBoxW
    function.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    function.restype = ctypes.c_int
    function(None, message, CURRENT.name, icon)


if __name__ == "__main__":
    raise SystemExit(main())
