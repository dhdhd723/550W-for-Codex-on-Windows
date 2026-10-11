"""Real Qt WebEngine animation contract tests (no Codex interaction).

Run: python -m unittest tests.test_animation_webengine -v
The test creates its own animation view. It neither patches nor starts Codex.
"""
import json
from pathlib import Path
import time
import unittest

from PySide6.QtCore import QEventLoop, QTimer, QUrl, QUrlQuery, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

ROOT = Path(__file__).resolve().parents[1]


class ConsolePage(QWebEnginePage):
    event_received = Signal(dict)

    def __init__(self, parent):
        super().__init__(parent)
        self.events = []
        self.errors = []

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith("LAUNCHER:"):
            event = json.loads(message[9:])
            self.events.append(event)
            self.event_received.emit(event)
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.errors.append({"message": message, "line": line})


class AnimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = QWebEngineView()
        self.view.resize(1280, 800)
        self.page = ConsolePage(self.view)
        self.view.setPage(self.page)
        self.view.show()
        self.addCleanup(self.view.close)
        self.addCleanup(self.view.deleteLater)

    def evaluate(self, code):
        loop = QEventLoop()
        result = []
        self.page.runJavaScript(code, lambda value: (result.append(value), loop.quit()))
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(5000)
        loop.exec()
        watchdog.stop()
        self.assertTrue(result, "JavaScript evaluation timed out")
        return result[0]

    def event(self, event_name, timeout_ms=8000):
        present = [e for e in self.page.events if e.get("event") == event_name]
        if present:
            return present[-1]
        loop = QEventLoop()
        def receive(event):
            if event.get("event") == event_name:
                loop.quit()
        self.page.event_received.connect(receive)
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(timeout_ms)
        loop.exec()
        watchdog.stop()
        self.page.event_received.disconnect(receive)
        found = [e for e in self.page.events if e.get("event") == event_name]
        self.assertTrue(found, f"Missing {event_name}; events={self.page.events}, errors={self.page.errors}")
        return found[-1]

    def load(self, mode="simple", scheme="amber"):
        url = QUrl.fromLocalFile(str(ROOT / "web" / "index.html"))
        query = QUrlQuery()
        query.addQueryItem("mode", mode)
        query.addQueryItem("scheme", scheme)
        url.setQuery(query)
        self.view.setUrl(url)
        event = self.event("loaded")
        self.assertEqual(event["mode"], mode)
        self.assertEqual(event["scheme"], scheme)

    def state(self):
        return json.loads(self.evaluate("JSON.stringify(window.launcher.getState())"))

    def test_simple_natural_end_waits_then_fades(self):
        self.load()
        completed = self.event("animation_done")
        self.assertFalse(completed["skipped"])
        self.assertGreater(completed["elapsed_ms"], 3500)
        self.assertLess(completed["elapsed_ms"], 6000)
        self.assertFalse(self.state()["exiting"])
        self.assertFalse(self.evaluate("document.querySelector('#launcher-status').hidden"))
        self.evaluate("window.launcher.setReady();window.launcher.finish();")
        self.event("exit_done", 2000)
        self.assertTrue(self.state()["exiting"])
        self.assertEqual(self.state()["timers"], {"pending": 0, "intervals": 0, "frames": 0})

    def test_full_original_phases_and_47_nodes(self):
        self.load("full")
        self.evaluate("window.launcher.setReady()")
        complete = self.event("animation_done", 25000)
        self.assertGreater(complete["elapsed_ms"], 15500)
        self.assertLess(complete["elapsed_ms"], 22000)
        state = self.state()
        self.assertEqual([p["phase"] for p in state["phases"]],
                         ["BOOT", "AUTH", "LINK", "TUNNEL", "ISOLATE", "REWRITE", "VERIFY", "DISARM", "COMPLETE"])
        self.assertEqual(self.evaluate("document.querySelectorAll('.uav.done').length"), 47)
        self.assertEqual(self.evaluate("document.querySelector('#final').textContent"), "SYSTEM IS REWRITTEN")
        self.assertTrue(self.evaluate("document.querySelector('#final').classList.contains('show')"))
        # Check the actual text Range, not just the panel: fixed left:50%
        # shrink-to-fit used to leave a half-width panel with clipped letters.
        # One full run then resizing also covers the narrow-screen CSS boundary.
        for width in [1280, 1920, 700, 640]:
            with self.subTest(final_viewport=width):
                # A fixed logical size also exercises 1920px on displays whose
                # current desktop scaling would otherwise clamp a titled view.
                self.view.setFixedSize(width, 800)
                QTest.qWait(100)
                final = json.loads(self.evaluate("""JSON.stringify((() => {
                    const e = document.querySelector('#final'), r = e.getBoundingClientRect();
                    const s = getComputedStyle(e), range = document.createRange();
                    range.selectNodeContents(e);
                    const text = range.getBoundingClientRect();
                    return {clip:s.clipPath, opacity:s.opacity, x:r.x, right:r.right,
                        width:r.width, viewport:innerWidth, textX:text.x,
                        textRight:text.right, textWidth:text.width};
                })())"""))
                self.assertEqual(final['viewport'], width)
                self.assertEqual(final['clip'], 'inset(0px)', 'Final banner must fully expand before handoff')
                self.assertEqual(final['opacity'], '1')
                self.assertGreater(final['textWidth'], 0)
                self.assertGreaterEqual(final['x'], -1)
                self.assertLessEqual(final['right'], final['viewport'] + 1)
                self.assertGreaterEqual(final['textX'], final['x'])
                self.assertLessEqual(final['textRight'], final['right'])
                self.assertGreaterEqual(final['textX'], 0)
                self.assertLessEqual(final['textRight'], final['viewport'])
        display = self.evaluate("document.querySelector('#app').innerText")
        self.assertNotIn('CODEX', display.upper())
        self.assertIn('550W CORE TERMINAL', display)
        self.assertIn('[550W]', display)
        self.assertIn('550W-ROOT', display)
        self.assertFalse(state["exiting"], "Completion must await the native launcher's finish command")
        self.assertFalse(self.page.errors)
        self.evaluate("window.launcher.finish()")
        self.event("exit_done", 2000)

    def test_real_escape_input_cancels_all_timers(self):
        self.load("full")
        QTest.qWait(200)
        QTest.keyClick(self.view.focusProxy() or self.view, Qt.Key.Key_Escape)
        self.event("skip", 2000)
        self.event("animation_done", 2000)
        state = self.state()
        self.assertTrue(state["skipped"])
        self.assertEqual(state["timers"], {"pending": 0, "intervals": 0, "frames": 0})

    def test_skip_during_hud_cancels_popup_and_panel_intervals(self):
        self.load("full")
        QTest.qWait(6200)
        self.assertGreater(len(self.state()["phases"]), 0)
        self.evaluate("window.launcher.skip()")
        self.event("animation_done", 2000)
        self.assertEqual(self.state()["timers"], {"pending": 0, "intervals": 0, "frames": 0})
        QTest.qWait(300)
        self.assertFalse(self.page.errors)

    def test_real_click_skips(self):
        self.load("full")
        QTest.qWait(200)
        QTest.mouseClick(self.view.focusProxy() or self.view, Qt.MouseButton.LeftButton)
        self.event("skip", 2000)
        self.assertTrue(self.state()["skipped"])

    def test_schemes_keep_svg_and_palette(self):
        expected = {"amber": "#e8a020", "green": "#4ad46a", "cyan": "#3fc8dc", "white": "#c9c9c9"}
        for scheme, color in expected.items():
            with self.subTest(scheme=scheme):
                self.page.events.clear()
                self.load("simple", scheme)
                self.assertEqual(self.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--amber').trim()"), color)
                self.assertEqual(self.evaluate("document.querySelectorAll('#logo path').length"), 6)
                self.assertEqual(self.evaluate("document.querySelector('#logo').getAttribute('aria-label')"), "550W")
                self.evaluate("window.launcher.skip()")
        self.assertFalse(self.page.errors)

    def test_failure_is_visible_and_escape_closes(self):
        self.load()
        self.evaluate("window.launcher.showError('测试：Codex 启动超时')")
        self.assertEqual(self.state()["error"], "测试：Codex 启动超时")
        self.assertFalse(self.evaluate("document.querySelector('#launcher-close').hidden"))
        QTest.keyClick(self.view.focusProxy() or self.view, Qt.Key.Key_Escape)
        self.event("close_requested", 2000)
        self.event("exit_done", 2000)

    def test_native_ready_does_not_automatically_end_animation(self):
        self.load()
        self.evaluate("window.launcher.setReady()")
        state = self.state()
        self.assertTrue(state["ready"])
        self.assertFalse(state["animationDone"])
        self.assertFalse(state["exiting"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
