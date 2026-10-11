"""Native mute safety and actual Qt WebEngine MP3 decode/autoplay checks.

Only launcher-owned windows are used. The tests never launch or focus Codex.
Playback/decoder state is verified; speaker loudness is not asserted.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings

from launcher import app as launcher_app
from launcher.app import Controller, Splash
from launcher.config import Config
from launcher.state import Gate


class NativeAudioPolicyTests(unittest.TestCase):
    def fake_controller(self):
        return SimpleNamespace(closed=False, preview=False, loaded=True, gate=Gate(),
                               window=Mock(), deadline=Mock(), stop_backend=Mock(),
                               maybe_exit=Mock(), app=Mock(), focus_official=Mock(return_value=True),
                               close=Mock())

    def test_skip_mutes_before_js_and_waiting(self):
        controller = self.fake_controller()
        Controller.skip(controller)
        self.assertTrue(controller.gate.animation_done)
        self.assertEqual(controller.window.mock_calls[0], call.stop_audio())
        controller.window.stop_audio.assert_called_once_with()
        controller.window.js.assert_called_once_with("skip")
        controller.maybe_exit.assert_called_once_with()

    def test_renderer_failure_mutes_even_while_waiting_for_official_app(self):
        controller = self.fake_controller()
        Controller.renderer_failed(controller, "test renderer error")
        controller.window.stop_audio.assert_called_once_with()
        controller.window.show_notice.assert_called_once_with("test renderer error")
        controller.maybe_exit.assert_called_once_with()

    def test_normal_exit_preserves_js_audio_fade_until_handoff(self):
        controller = self.fake_controller()
        controller.gate = Gate(animation_done=True, window_ready=True)
        controller.fade_background = Mock()
        with patch.object(launcher_app, "QTimer"):
            Controller.maybe_exit(controller)
        controller.window.js.assert_called_once_with("finish")
        controller.window.stop_audio.assert_not_called()
        Controller.handoff_complete(controller)
        controller.window.stop_audio.assert_called_once_with()
        controller.close.assert_called_once_with()

    def test_explicit_close_mutes_before_hiding_and_quitting(self):
        controller = self.fake_controller()
        Controller.close(controller)
        self.assertTrue(controller.closed)
        controller.window.stop_audio.assert_called_once_with()
        controller.window.hide.assert_called_once_with()
        controller.app.quit.assert_called_once_with()

    def test_start_failure_stops_audio_before_showing_error_dialog(self):
        controller = self.fake_controller()
        with patch.object(launcher_app, "QMessageBox"), patch.object(launcher_app, "QTimer"), \
                patch.object(launcher_app, "data_dir", return_value=Path("test-owned-logs")):
            Controller.fail(controller, "test startup timeout")
        self.assertTrue(controller.gate.failed)
        controller.stop_backend.assert_called_once_with()
        controller.deadline.stop.assert_called_once_with()
        self.assertEqual(controller.window.mock_calls[:2], [call.stop_audio(), call.hide()])


class WebEngineMp3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.splash = Splash(Config(mode="full"))
        self.splash.resize(800, 600)
        self.splash.show()
        self.loaded = False
        self.splash.view.loadFinished.connect(self._loaded)
        # Decoder checks stay quiet; HTML media itself remains unmuted. Native
        # page mute does not replace the required autoplay setting assertion.
        self.assertFalse(self.splash.page.isAudioMuted())
        self.splash.page.setAudioMuted(True)
        self.splash.load()
        self.wait_until(lambda: self.loaded, 8000)

    def _loaded(self, ok):
        self.loaded = bool(ok)

    def tearDown(self):
        self.splash.stop_audio()
        self.splash.hide()
        # Release page before its off-the-record profile to avoid profile warnings.
        self.splash.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.splash.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def wait_until(self, predicate, timeout_ms):
        elapsed = 0
        while elapsed < timeout_ms and not predicate():
            QTest.qWait(50)
            elapsed += 50
        self.assertTrue(predicate(), f"Condition not reached within {timeout_ms} ms")

    def evaluate(self, source):
        values = []
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(5000)
        self.splash.page.runJavaScript(source, lambda result: (values.append(result), loop.quit()))
        loop.exec()
        timer.stop()
        self.assertTrue(values, "JavaScript evaluation timed out")
        return values[0]

    def test_user_mp3_decodes_and_plays_without_dom_user_gesture(self):
        self.assertFalse(self.splash.page.settings().testAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture))
        self.assertTrue((Path(__file__).resolve().parents[1] / "web" / "audio" / "boot.mp3").is_file())
        support = self.evaluate("new Audio().canPlayType('audio/mpeg')")
        self.assertIn(support, ("maybe", "probably"), "This Qt WebEngine build does not report MP3 support")
        self.evaluate("""(() => {
            window.__mp3Probe = new Audio('audio/boot.mp3');
            window.__mp3Probe.loop = true;
            window.__mp3Probe.volume = 0.01;
            window.__mp3Probe.muted = false;
            window.__mp3ProbeState = {started: false, error: ''};
            window.__mp3Probe.play().then(() => window.__mp3ProbeState.started = true)
                .catch(error => window.__mp3ProbeState.error = error.name + ': ' + error.message);
        })()""")
        self.wait_until(lambda: self.evaluate("window.__mp3ProbeState.started || !!window.__mp3ProbeState.error"), 8000)
        QTest.qWait(600)
        state = json.loads(self.evaluate("JSON.stringify({promise: window.__mp3ProbeState, time: window.__mp3Probe.currentTime, duration: window.__mp3Probe.duration, paused: window.__mp3Probe.paused, mediaError: window.__mp3Probe.error && window.__mp3Probe.error.code})"))
        self.assertEqual(state["promise"]["error"], "")
        self.assertTrue(state["promise"]["started"])
        self.assertGreater(state["duration"], 0)
        self.assertGreater(state["time"], 0.1)
        self.assertFalse(state["paused"])
        self.assertIsNone(state["mediaError"])
        self.evaluate("window.__mp3Probe.pause();window.__mp3Probe.currentTime=0;")

    def test_emergency_native_mute_is_synchronous(self):
        self.splash.page.setAudioMuted(False)
        self.splash.stop_audio()
        self.assertTrue(self.splash.page.isAudioMuted())

    def test_missing_mp3_does_not_emit_native_renderer_failure(self):
        errors = []
        self.splash.page.script_error.connect(errors.append)
        script = QWebEngineScript()
        script.setName("test-only-missing-audio")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode("""(() => {
            const BaseAudio = window.Audio;
            window.Audio = function() { return new BaseAudio('audio/missing-test.mp3'); };
            window.Audio.prototype = BaseAudio.prototype;
        })();""")
        self.splash.page.scripts().insert(script)
        self.loaded = False
        self.splash.load()
        self.wait_until(lambda: self.loaded, 8000)
        self.wait_until(lambda: self.evaluate("!!window.launcher.getState().audio.error"), 8000)
        state = json.loads(self.evaluate("JSON.stringify(window.launcher.getState())"))
        self.assertIsNone(state["error"])
        self.assertEqual(state["audio"]["status"], "stopped")
        self.assertTrue(state["audio"]["paused"])
        self.assertFalse(errors, f"Missing MP3 wrongly became native renderer failure: {errors}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
