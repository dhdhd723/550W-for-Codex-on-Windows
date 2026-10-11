"""Backend cancellation and HWND replacement races, without any UI operation."""
import unittest
from unittest.mock import patch

from launcher.app import Backend, BackendSignals
from launcher.config import Config
from launcher.windows import AppTarget, WindowInfo

TARGET = AppTarget("exe", "C:\\App\\ChatGPT.exe", ("C:\\App\\ChatGPT.exe",))
ONE = WindowInfo(1, 101, "ChatGPT", TARGET.value, (0, 0, 900, 700))
TWO = WindowInfo(2, 102, "ChatGPT", TARGET.value, (0, 0, 900, 700))


class LoopStop:
    def __init__(self, count):
        self.remaining = count
        self.stopped = False
    def is_set(self):
        return self.stopped
    def set(self):
        self.stopped = True
    def wait(self, duration):
        self.remaining -= 1
        if self.remaining <= 0:
            self.stopped = True


class BackendLifecycleTests(unittest.TestCase):
    def make(self):
        signals = BackendSignals()
        backend = Backend(Config(), signals)
        return backend, signals

    def test_cancel_during_discovery_never_starts_official_app(self):
        backend, signals = self.make()
        def discovery(_):
            backend.stop.set()
            return [TARGET]
        with patch("launcher.app.discover_targets", side_effect=discovery), patch("launcher.app.launch_target") as launch:
            backend.work()
            launch.assert_not_called()

    def test_cancel_after_initial_probe_never_starts_official_app(self):
        backend, signals = self.make()
        def probe(*args, **kwargs):
            backend.stop.set()
            return None
        with patch("launcher.app.discover_targets", return_value=[TARGET]), patch("launcher.app.find_ready_window", side_effect=probe), patch("launcher.app.launch_target") as launch:
            backend.work()
            launch.assert_not_called()

    def test_window_replacement_revokes_ready_until_stable(self):
        backend, signals = self.make()
        events = []
        signals.ready.connect(lambda window: events.append(("ready", window.hwnd)))
        signals.lost.connect(lambda: events.append(("lost", None)))
        backend.stop = LoopStop(6)
        # Initial probe, then three stable observations per HWND.
        with patch("launcher.app.discover_targets", return_value=[TARGET]), patch("launcher.app.launch_target") as launch, patch("launcher.app.find_ready_window", side_effect=[ONE, ONE, ONE, ONE, TWO, TWO, TWO]), patch("launcher.app.time.monotonic", side_effect=[0, .2, .4, .6, .8, 1.0]):
            backend.work()
        launch.assert_not_called()
        self.assertEqual(events, [("ready", 1), ("lost", None), ("ready", 2)])

    def test_missing_initial_window_launches_once_and_waits_for_stability(self):
        backend, signals = self.make()
        events = []
        signals.ready.connect(lambda window: events.append(window.hwnd))
        backend.stop = LoopStop(3)
        with patch("launcher.app.discover_targets", return_value=[TARGET]), patch("launcher.app.launch_target") as launch, patch("launcher.app.find_ready_window", side_effect=[None, ONE, ONE, ONE]), patch("launcher.app.time.monotonic", side_effect=[0, .2, .4]):
            backend.work()
        launch.assert_called_once_with(TARGET)
        self.assertEqual(events, [1])


if __name__ == "__main__":
    unittest.main()
