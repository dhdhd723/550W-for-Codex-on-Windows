"""Render actual launcher Splash widgets and save only their own pixels.

No Backend is constructed and the official Codex app is never inspected,
started, hidden, or activated. Outputs document source animation verification.
Run from the project root: python scripts/capture-animation.py
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6 import __version__ as qt_version
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from launcher.app import Splash
from launcher.config import Config


def wait_ms(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def evaluate(page, script):
    loop = QEventLoop()
    answer = []
    page.runJavaScript(script, lambda value: (answer.append(value), loop.quit()))
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(5000)
    loop.exec()
    timeout.stop()
    if not answer:
        raise RuntimeError("JavaScript callback timeout")
    return answer[0]


def capture(app, mode, color, width=1280, height=800):
    splash = Splash(Config(mode=mode, color=color))
    splash.resize(width, height)
    # Child view rendering honors the actual display's device-pixel ratio.
    splash.move(0, 0)
    events, errors = [], []
    splash.page.message.connect(events.append)
    splash.page.script_error.connect(errors.append)
    splash.show()
    splash.load()
    until = time.monotonic() + 10
    while not any(e["event"] == "loaded" for e in events):
        if time.monotonic() > until:
            raise RuntimeError(f"actual Splash failed to load: {errors}")
        wait_ms(100)
    evaluate(splash.page, "window.launcher.setReady()")
    wait_ms(2700)
    scale_suffix = "-scale-" + os.environ["QT_SCALE_FACTOR"] if os.environ.get("QT_SCALE_FACTOR") else ""
    filename = f"{mode}-{color}-{width}x{height}-logo{scale_suffix}.png"
    if not splash.view.grab().save(str(ROOT / "docs" / "screenshots" / filename)):
        raise RuntimeError("QWidget grab save failed")
    if mode == "full":
        wait_ms(4700)
        filename = f"full-{color}-{width}x{height}-hud{scale_suffix}.png"
        splash.view.grab().save(str(ROOT / "docs" / "screenshots" / filename))
    until = time.monotonic() + 25
    while not any(e["event"] == "animation_done" for e in events):
        if time.monotonic() > until:
            raise RuntimeError(f"actual Splash failed to complete: {events}, {errors}")
        wait_ms(100)
    wait_ms(100)
    if mode == "full":
        splash.view.grab().save(str(ROOT / "docs" / "screenshots" / f"full-{color}-{width}x{height}-ready{scale_suffix}.png"))
    state = json.loads(evaluate(splash.page, "JSON.stringify(window.launcher.getState())"))
    if errors or state["error"]:
        raise RuntimeError(f"animation script failure: {errors}, {state}")
    if state["exiting"]:
        raise RuntimeError("animation incorrectly exited before native finish")
    evaluate(splash.page, "window.launcher.finish()")
    until = time.monotonic() + 3
    while not any(e["event"] == "exit_done" for e in events):
        if time.monotonic() > until:
            raise RuntimeError("fade exit callback missing")
        wait_ms(100)
    final_state = json.loads(evaluate(splash.page, "JSON.stringify(window.launcher.getState())"))
    result = {"mode": mode, "color": color, "logical_viewport": [width, height],
              "device_pixel_ratio": splash.view.devicePixelRatioF(), "events": events,
              "phase_timings": state["phases"], "remaining_timers": final_state["timers"],
              "script_errors": errors, "status": "passed"}
    splash.close()
    splash.page.deleteLater()
    splash.view.deleteLater()
    splash.profile.deleteLater()
    splash.deleteLater()
    wait_ms(100)
    return result


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    (ROOT / "docs" / "screenshots").mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "test-results").mkdir(parents=True, exist_ok=True)
    report = {"platform": platform.platform(), "PySide6": qt_version,
              "QT_SCALE_FACTOR": os.environ.get("QT_SCALE_FACTOR", "system default"),
              "scope": "Actual launcher.app.Splash only; no official-app operations",
              "captures": []}
    cases = [("brief", "amber", 1280, 800)] + [("full", color, 1280, 800) for color in ["amber", "green", "cyan", "white"]]
    # A narrow logical viewport exercises the original popup minimum-width fix.
    if "--narrow" in sys.argv:
        cases = [("full", "amber", 640, 400)]
    if "--brief-only" in sys.argv:
        cases = [("brief", "amber", 1280, 800)]
    for mode, color, width, height in cases:
        result = capture(app, mode, color, width, height)
        report["captures"].append(result)
        done = next(e for e in result["events"] if e["event"] == "animation_done")
        print(f"PASS actual Splash: {mode} {color} {width}x{height}, {done['elapsed_ms']} ms, DPR {result['device_pixel_ratio']}", flush=True)
    suffix = "narrow" if "--narrow" in sys.argv else "brief" if "--brief-only" in sys.argv else "full"
    factor = os.environ.get("QT_SCALE_FACTOR", "system")
    output = ROOT / "docs" / "test-results" / f"animation-captures-{suffix}-scale-{factor}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
