"""Decode the supplied MP3 in the actual isolated Splash and test its lifecycle.

The page output is muted during tests. This verifies playback, not audibility
through a particular Windows speaker. No official client is started or changed.
"""
import json
import time
import unittest

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineScript

from launcher.app import Splash
from launcher.config import Config


class AudioWebEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.splash = Splash(Config(mode="full"))
        self.splash.resize(840, 525)
        self.splash.page.setAudioMuted(True)
        self.events = []
        self.errors = []
        self.splash.page.message.connect(self.events.append)
        self.splash.page.script_error.connect(self.errors.append)
        self.splash.show()

    def tearDown(self):
        self.splash.stop_audio()
        self.splash.close()
        self.splash.page.deleteLater()
        self.splash.view.deleteLater()
        self.splash.profile.deleteLater()
        self.splash.deleteLater()
        QTest.qWait(50)

    def evaluate(self, script):
        answers = []
        loop = QEventLoop()
        self.splash.page.runJavaScript(script, lambda value: (answers.append(value), loop.quit()))
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(4000)
        loop.exec()
        watchdog.stop()
        self.assertTrue(answers, "JavaScript callback timed out")
        return answers[0]

    def state(self):
        return json.loads(self.evaluate("JSON.stringify(window.launcher.getState())"))

    def event(self, name, timeout_ms=5000):
        until = time.monotonic() + timeout_ms / 1000
        while not any(event.get("event") == name for event in self.events):
            self.assertLess(time.monotonic(), until, f"Missing {name}: {self.events}, {self.errors}")
            QTest.qWait(50)
        return next(event for event in self.events if event.get("event") == name)

    def load(self):
        self.splash.load()
        self.event("loaded")

    def playing(self):
        self.load()
        started = self.event("audio_started")
        self.assertLess(started["elapsed_ms"], 1500)
        self.assertFalse(self.state()["logoVisible"], "Sound must start before the logo finishes drawing")
        QTest.qWait(500)
        state = self.state()
        self.assertEqual(state["audio"]["status"], "playing")
        self.assertGreater(state["audio"]["currentTime"], 0.2)
        self.assertGreater(state["audio"]["duration"], 13)
        self.assertLess(state["audio"]["duration"], 14)
        self.assertIsNone(state["audio"]["error"])

    def assert_stopped(self):
        sound = self.state()["audio"]
        self.assertTrue(sound["paused"])
        self.assertEqual(sound["currentTime"], 0)
        self.assertEqual(sound["status"], "stopped")
        self.assertFalse(sound["fadePending"])
        self.assertFalse(sound["deadlinePending"])

    def test_autoplay_and_normal_exit_fades_before_stop(self):
        self.playing()
        self.evaluate("window.launcher.finish()")
        QTest.qWait(250)
        sound = self.state()["audio"]
        self.assertEqual(sound["status"], "fading")
        self.assertGreater(sound["volume"], 0)
        self.assertLess(sound["volume"], 0.85)
        self.event("exit_done", 2000)
        self.assert_stopped()
        self.assertFalse(self.errors)

    def test_full_track_ends_at_ready_and_waiting_is_silent(self):
        self.playing()
        ready = self.event("system_ready", 24000)
        started = next(e for e in self.events if e["event"] == "audio_started")
        ended = self.event("audio_ended")
        self.assertGreater(ready["elapsed_ms"] - started["elapsed_ms"], 12500)
        self.assertGreaterEqual(ready["elapsed_ms"], ended["elapsed_ms"])
        self.assertLess(ready["elapsed_ms"] - ended["elapsed_ms"], 1500)
        wait_done = self.event("ready_audio_wait_done")
        self.assertLess(wait_done["duration_ms"], 1500, "The countdown must fill the final audio wait")
        self.assertTrue(self.evaluate("document.querySelector('#final').classList.contains('show')"))
        self.assert_stopped()
        self.event("animation_done", 24000)
        QTest.qWait(700)
        state = self.state()
        self.assertTrue(state["animationDone"])
        self.assertFalse(state["ready"])
        self.assertFalse(state["exiting"])
        self.assertEqual(state["audio"]["loops"], 0)
        self.assertFalse(any(e["event"] == "audio_loop" for e in self.events))
        self.assert_stopped()
        self.assertFalse(self.errors)

    def test_escape_stops_music_and_cancels_animation(self):
        self.playing()
        QTest.keyClick(self.splash.view.focusProxy() or self.splash.view, Qt.Key.Key_Escape)
        self.event("skip", 2000)
        self.assert_stopped()
        self.assertTrue(self.state()["skipped"])

    def test_click_stops_music(self):
        self.playing()
        QTest.mouseClick(self.splash.view.focusProxy() or self.splash.view, Qt.MouseButton.LeftButton)
        self.event("skip", 2000)
        self.assert_stopped()

    def test_error_and_dispose_leave_no_music(self):
        self.playing()
        self.evaluate("window.launcher.showError('模拟官方启动超时')")
        self.assert_stopped()
        self.evaluate("window.launcher.dispose()")
        self.assert_stopped()
        self.assertEqual(self.state()["timers"], {"pending": 0, "intervals": 0, "frames": 0})

    def test_audio_rejection_keeps_animation_operating(self):
        script = QWebEngineScript()
        script.setName("test-audio-rejection")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode("HTMLMediaElement.prototype.play = function() { return Promise.reject(new Error('test audio rejection')); };")
        self.splash.page.scripts().insert(script)
        self.load()
        self.event("audio_error")
        state = self.state()
        self.assertIsNone(state["error"])
        self.assertEqual(state["audio"]["error"], "test audio rejection")
        self.assertFalse(state["animationDone"])
        self.assertFalse(self.errors)
        self.evaluate("window.launcher.skip()")
        self.event("animation_done")

    def test_native_stop_releases_ready_barrier_without_reviving_final(self):
        # Lose the ended callback deliberately so the final audio barrier stays
        # pending regardless of machine timing; real playback still advances.
        script = QWebEngineScript()
        script.setName("test-lost-ended-event")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode("const listen = HTMLMediaElement.prototype.addEventListener; HTMLMediaElement.prototype.addEventListener = function(type, ...args) { if (type !== 'ended') return listen.call(this, type, ...args); };")
        self.splash.page.scripts().insert(script)
        self.playing()
        self.event("ready_audio_wait", 16000)
        self.assertFalse(self.state()["systemReady"])
        self.splash.stop_audio()
        QTest.qWait(400)
        self.assert_stopped()
        self.assertFalse(self.state()["systemReady"])
        self.assertFalse(self.evaluate("document.querySelector('#final').classList.contains('show')"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
