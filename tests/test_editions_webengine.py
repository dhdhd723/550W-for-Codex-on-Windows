"""Exercise the silent brief edition in the real isolated native Splash.

The request recorder observes every browser request, including attempted media
loads. These tests create launcher-owned windows and never start official Codex.
"""
import unittest

from PySide6.QtCore import QUrlQuery, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from launcher.app import LocalOnly, Splash
from launcher.config import Config
from tests import test_animation_webengine as animation_tests


class RecordingLocalOnly(LocalOnly):
    def __init__(self, parent):
        super().__init__(parent)
        self.requests = []

    def interceptRequest(self, info):
        self.requests.append(info.requestUrl().toString())
        super().interceptRequest(info)


class SilentBriefEditionTests(unittest.TestCase):
    # Reuse the existing bounded WebEngine helpers without inheriting its tests.
    evaluate = animation_tests.AnimationTests.evaluate
    state = animation_tests.AnimationTests.state

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.splash = Splash(Config(mode="brief", sound=False))
        self.splash.resize(840, 525)
        self.page = self.splash.page
        self.events = []
        self.errors = []
        self.page.message.connect(self.events.append)
        self.page.script_error.connect(self.errors.append)
        self.recorder = RecordingLocalOnly(self.splash.profile)
        self.splash.profile.setUrlRequestInterceptor(self.recorder)
        self.splash.show()

    def tearDown(self):
        self.splash.stop_audio()
        self.splash.close()
        self.splash.page.deleteLater()
        self.splash.view.deleteLater()
        self.splash.profile.deleteLater()
        self.splash.deleteLater()
        QTest.qWait(50)

    def event(self, name, timeout_ms=8000):
        # AnimationPage exposes the same console events through its native signal.
        import time
        until = time.monotonic() + timeout_ms / 1000
        while not any(event.get("event") == name for event in self.events):
            self.assertLess(time.monotonic(), until,
                            f"Missing {name}: {self.events}; errors={self.errors}")
            QTest.qWait(25)
        return next(event for event in self.events if event.get("event") == name)

    def load(self):
        self.assertTrue(self.page.isAudioMuted(), "Native page must be muted before loading")
        query = QUrlQuery(self.splash.url)
        self.assertEqual(query.queryItemValue("mode"), "brief")
        self.assertEqual(query.queryItemValue("sound"), "off")
        self.splash.load()
        loaded = self.event("loaded")
        self.assertEqual(loaded["mode"], "simple")
        self.assertFalse(loaded["audio_enabled"])

    def assert_silent(self):
        state = self.state()
        audio = state["audio"]
        self.assertFalse(audio["enabled"])
        self.assertEqual(audio["status"], "disabled")
        self.assertTrue(audio["paused"])
        self.assertEqual(audio["currentTime"], 0)
        self.assertIsNone(audio["duration"])
        self.assertIsNone(audio["error"])
        self.assertFalse(audio["fadePending"])
        self.assertFalse(audio["deadlinePending"])
        self.assertTrue(self.page.isAudioMuted())
        media_requests = [url for url in self.recorder.requests
                          if "/audio/" in url.lower() or ".mp3" in url.lower()]
        self.assertFalse(media_requests, f"Silent edition requested media: {media_requests}")
        names = [event["event"] for event in self.events]
        self.assertFalse([name for name in names
                          if name.startswith("audio_") or name.startswith("ready_audio_wait")])
        self.assertFalse(self.errors)

    def test_brief_natural_completion_never_requests_audio_or_shows_terminal(self):
        self.load()
        self.assert_silent()
        completed = self.event("animation_done")
        self.assertFalse(completed["skipped"])
        self.assertGreater(completed["elapsed_ms"], 3500)
        self.assertLess(completed["elapsed_ms"], 6500)
        self.assertTrue(self.state()["logoVisible"])
        self.assertEqual(self.evaluate("document.querySelector('#logo').getAttribute('aria-label')"), "550W")
        self.assertEqual(self.evaluate("document.querySelectorAll('#logo path').length"), 6)
        self.assertFalse(self.evaluate("document.querySelector('#final').classList.contains('show')"))
        self.assertFalse(self.evaluate("document.querySelector('#app').classList.contains('visible')"))
        self.assertEqual(self.state()["phases"], [])
        self.assertFalse(self.state()["systemReady"])
        self.assertFalse(self.state()["exiting"])
        self.assert_silent()
        self.assertTrue(any(url.endswith("/animation.js") for url in self.recorder.requests),
                        "Request recorder must observe the actual animation assets")

    def test_native_mute_then_escape_cancels_silent_animation_without_revival(self):
        self.load()
        QTest.qWait(200)
        self.splash.stop_audio()
        QTest.keyClick(self.splash.view.focusProxy() or self.splash.view, Qt.Key.Key_Escape)
        self.event("skip", 2000)
        completed = self.event("animation_done", 2000)
        self.assertTrue(completed["skipped"])
        self.assertTrue(self.state()["skipped"])
        self.assertEqual(self.state()["timers"], {"pending": 0, "intervals": 0, "frames": 0})
        QTest.qWait(4100)
        self.assertFalse(self.state()["logoVisible"])
        self.assertFalse(self.state()["systemReady"])
        self.assertFalse(self.evaluate("document.querySelector('#final').classList.contains('show')"))
        self.assertEqual(sum(event["event"] == "animation_done" for event in self.events), 1)
        self.assert_silent()


if __name__ == "__main__":
    unittest.main(verbosity=2)
