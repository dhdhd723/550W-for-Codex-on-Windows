"""Exercise the real native Controller with simulated official-window events.

This deliberately does not activate, close, or inspect the official app.
Simulation results are identified as such in the saved report.
"""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def scenario(name):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from launcher.app import Controller
    from launcher.config import Config
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    result = {"scenario": name, "scope": "real Qt Controller; simulated official readiness/focus", "observations": []}
    started = time.monotonic()
    with patch("launcher.app.Backend.start", lambda self: None), patch("launcher.app.Controller.focus_official", return_value=True):
        controller = Controller(app, Config(mode="brief", timeout_seconds=20))
        controller.window.resize(960, 600)
        controller.window.move(0, 0)
        def observe(label):
            result["observations"].append({"event": label, "elapsed_ms": round((time.monotonic()-started)*1000),
                                           "animation_done": controller.gate.animation_done,
                                           "ready": controller.gate.window_ready, "exiting": controller.gate.exiting,
                                           "failed": controller.gate.failed, "visible": controller.window.isVisible()})
        def after_loaded(payload):
            if payload.get("event") != "loaded":
                return
            observe("loaded")
            if name == "skip_wait":
                QTimer.singleShot(100, controller.skip)
                def still_waiting():
                    observe("waiting_after_skip")
                    assert controller.gate.animation_done and not controller.gate.exiting
                QTimer.singleShot(600, still_waiting)
                QTimer.singleShot(1200, lambda: controller.official_ready(None))
            elif name == "natural":
                controller.official_ready(None)
            elif name == "renderer_failure":
                QTimer.singleShot(100, lambda: controller.renderer_failed("SIMULATED renderer termination"))
                QTimer.singleShot(500, lambda: controller.official_ready(None))
            elif name == "timeout":
                controller.deadline.start(400)
                def failed_visible():
                    observe("timeout_prompt")
                    assert controller.gate.failed and not controller.window.isVisible()
                    assert controller.error.isVisible()
                    controller.close()
                QTimer.singleShot(700, failed_visible)
        controller.window.page.message.connect(after_loaded)
        def watchdog():
            result["watchdog"] = True
            controller.close()
        QTimer.singleShot(10000, watchdog)
        app.exec()
        observe("closed")
        result["status"] = "passed" if controller.closed and not result.get("watchdog") else "failed"
        if name != "timeout" and controller.gate.failed:
            result["status"] = "failed"
        if name != "timeout" and not controller.gate.exiting:
            result["status"] = "failed"
        if name == "timeout" and not controller.gate.failed:
            result["status"] = "failed"
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--scenario":
        return scenario(sys.argv[2])
    results = []
    for name in ("natural", "skip_wait", "renderer_failure", "timeout"):
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--scenario", name],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        if child.returncode:
            print(child.stdout)
            print(child.stderr)
            return child.returncode
        result = json.loads(child.stdout.strip().splitlines()[-1])
        results.append(result)
        print(f"PASS simulated native integration: {name}", flush=True)
    target = ROOT / "docs" / "test-results" / "native-integration-simulated.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
