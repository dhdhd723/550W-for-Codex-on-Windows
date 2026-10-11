import json
from pathlib import Path
import tempfile
import unittest

from launcher.config import Config, load, save
from launcher.state import Gate


class GateTests(unittest.TestCase):
    def test_skip_must_wait_for_official_window(self):
        gate = Gate(animation_done=True)
        self.assertFalse(gate.begin_exit())
        gate.window_ready = True
        self.assertTrue(gate.begin_exit())
        self.assertFalse(gate.begin_exit())

    def test_ready_window_must_wait_for_animation(self):
        gate = Gate(window_ready=True)
        self.assertFalse(gate.begin_exit())
        gate.animation_done = True
        self.assertTrue(gate.begin_exit())

    def test_lost_window_and_failure_prevent_exit(self):
        gate = Gate(animation_done=True, window_ready=True)
        gate.window_ready = False
        self.assertFalse(gate.begin_exit())
        gate.window_ready = True
        gate.failed = True
        self.assertFalse(gate.begin_exit())


class ConfigTests(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            config = Config(False, "full", "cyan", 120, "C:\\官方软件\\ChatGPT.exe")
            save(config, path)
            self.assertEqual(load(path), config)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_defaults_and_validation(self):
        self.assertEqual(Config.parse({}), Config())
        for raw in ({"enabled": "false"}, {"timeout_seconds": True}, {"timeout_seconds": 10},
                    {"mode": "bad"}, {"color": "red"}, {"target_executable": []}, []):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                Config.parse(raw)

    def test_corrupted_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text("broken", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load(path)
            self.assertEqual(path.read_text(), "broken")


if __name__ == "__main__":
    unittest.main()
