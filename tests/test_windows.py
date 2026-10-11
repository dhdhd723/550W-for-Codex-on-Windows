"""Policy tests use mock Win32 results; no app launch or focus is performed."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from launcher import windows


FAMILY = "OpenAI.Codex_2p2nqsd0c76g0"
APP_PATH = r"C:\Program Files\WindowsApps\OpenAI.Codex_1_x64__id\app\ChatGPT.exe"
TARGET = windows.AppTarget("aumid", FAMILY + "!App", (APP_PATH,), "ChatGPT", FAMILY)


class FakeNative:
    def __init__(self, rows):
        self.rows = rows
        self.identity_calls = []
        self.responsive_calls = []

    def windows(self):
        return list(self.rows)

    def basic(self, hwnd):
        row = self.rows[hwnd]
        if not row.get("valid", True):
            return None
        return row["pid"], row.get("title", "ChatGPT"), row.get("rect", (0, 0, 1280, 800)), row.get("minimized", False)

    def identity(self, pid):
        self.identity_calls.append(pid)
        row = next(row for row in self.rows.values() if row["pid"] == pid)
        return row.get("path", APP_PATH), row.get("family", FAMILY)

    def responsive(self, hwnd):
        self.responsive_calls.append(hwnd)
        return self.rows[hwnd].get("responsive", True)


class WindowsPolicyTests(unittest.TestCase):
    def native_for_basic(self, *, visible=True, enabled=True, owner=0,
                         minimized=False, cloaked=False, rect=(0, 0, 1280, 800)):
        native = windows._Native.__new__(windows._Native)
        native.user32, native.dwmapi = Mock(), Mock()
        native.user32.IsWindow.return_value = True
        native.user32.IsWindowVisible.return_value = visible
        native.user32.IsWindowEnabled.return_value = enabled
        native.user32.GetWindow.return_value = owner
        native.user32.IsIconic.return_value = minimized
        def set_cloaked(hwnd, attribute, buffer, size):
            buffer._obj.value = int(cloaked)
            return 0
        def set_rect(hwnd, buffer):
            buffer._obj.left, buffer._obj.top, buffer._obj.right, buffer._obj.bottom = rect
            return True
        def set_pid(hwnd, buffer):
            buffer._obj.value = 100
            return 200
        def set_title(hwnd, buffer, length):
            buffer.value = "ChatGPT"
            return 7
        native.dwmapi.DwmGetWindowAttribute.side_effect = set_cloaked
        native.user32.GetWindowRect.side_effect = set_rect
        native.user32.GetWindowThreadProcessId.side_effect = set_pid
        native.user32.GetWindowTextLengthW.return_value = 7
        native.user32.GetWindowTextW.side_effect = set_title
        return native

    def test_native_rejects_hidden_disabled_owned_or_cloaked_windows(self):
        for kwargs in ({"visible": False}, {"enabled": False}, {"owner": 123}, {"cloaked": True}):
            with self.subTest(kwargs=kwargs):
                self.assertIsNone(self.native_for_basic(**kwargs).basic(1000))

    def test_native_size_check_exempts_minimized_main_window(self):
        rect = (-32000, -32000, -31840, -31980)
        self.assertIsNone(self.native_for_basic(rect=rect).basic(1000))
        result = self.native_for_basic(rect=rect, minimized=True).basic(1000)
        self.assertEqual(result, (100, "ChatGPT", rect, True))

    def test_native_focus_restore_and_denial_are_observed(self):
        native = windows._Native.__new__(windows._Native)
        native.user32 = Mock()
        native.user32.IsWindow.return_value = True
        native.user32.IsIconic.return_value = True
        native.user32.SetForegroundWindow.return_value = True
        native.user32.GetForegroundWindow.return_value = 999
        self.assertFalse(native.focus(123))
        native.user32.ShowWindowAsync.assert_called_once_with(123, 9)
        native.user32.GetForegroundWindow.return_value = 123
        self.assertTrue(native.focus(123))

    def test_discovery_verifies_actual_gui_subsystem(self):
        records = [{"value": FAMILY + "!App", "package_family": FAMILY, "process_paths": [APP_PATH]}]
        for expected in (True, False):
            with patch.object(windows, "_run_discovery", return_value=records), \
                    patch.object(windows, "_is_gui_executable", return_value=expected):
                self.assertEqual(bool(windows.discover_targets()), expected)

    def test_manifest_records_do_not_use_start_menu_label_for_identity(self):
        targets = windows._targets_from_records([{
            "value": FAMILY + "!App", "package_family": FAMILY,
            "process_paths": [APP_PATH], "display_name": "ChatGPT",
        }])
        self.assertEqual(targets, [TARGET])

    def test_manifest_cli_helpers_and_other_publishers_are_excluded(self):
        records = [
            {"value": FAMILY + "!Runner", "package_family": FAMILY,
             "process_paths": [r"C:\package\app\resources\codex-command-runner.exe"]},
            {"value": FAMILY + "!CLI", "package_family": FAMILY,
             "process_paths": [r"C:\package\app\resources\codex.exe"]},
            {"value": "Acme.Codex_id!App", "package_family": "Acme.Codex_id",
             "process_paths": [APP_PATH]},
        ]
        self.assertEqual(windows._targets_from_records(records), [])

    def test_main_app_prioritized_and_duplicates_removed(self):
        record = {"package_family": FAMILY, "process_paths": [APP_PATH]}
        records = [dict(record, value=FAMILY + "!B"), dict(record, value=FAMILY + "!App"),
                   dict(record, value=FAMILY + "!App")]
        self.assertEqual([target.value for target in windows._targets_from_records(records)],
                         [FAMILY + "!App", FAMILY + "!B"])

    def test_full_path_match_is_case_insensitive(self):
        self.assertTrue(windows._matches_identity(TARGET, APP_PATH.upper(), ""))

    def test_family_match_allows_updated_main_exe_path(self):
        path = APP_PATH.replace("_1_x64", "_2_x64")
        self.assertTrue(windows._matches_identity(TARGET, path, FAMILY))

    def test_family_match_never_accepts_cli_or_different_executable(self):
        for path in (r"C:\app\resources\codex.exe", r"C:\app\codex.exe", r"C:\QtWebEngineProcess.exe"):
            self.assertFalse(windows._matches_identity(TARGET, path, FAMILY))
        self.assertFalse(windows._matches_identity(TARGET, r"C:\Fake\ChatGPT.exe", "Acme.Fake"))

    def test_explicit_exe_requires_exact_path_not_family_or_title(self):
        target = windows.AppTarget("exe", r"C:\Codex\ChatGPT.exe", (r"C:\Codex\ChatGPT.exe",))
        self.assertFalse(windows._matches_identity(target, APP_PATH, FAMILY))
        self.assertTrue(windows._matches_identity(target, r"c:\codex\chatgpt.exe", ""))

    def test_ready_window_ignores_same_title_impostor_and_self(self):
        native = FakeNative({
            1: {"pid": 100, "path": r"C:\other\ChatGPT.exe", "family": "", "title": "Codex"},
            2: {"pid": 999, "path": APP_PATH},
            3: {"pid": 101, "path": APP_PATH, "title": "A document - Codex"},
        })
        with patch.object(windows, "_native", return_value=native):
            result = windows.find_ready_window(TARGET, exclude_pid=999)
        self.assertEqual(result.hwnd, 3)
        self.assertEqual(native.responsive_calls, [3])
        self.assertNotIn(999, native.identity_calls)

    def test_unresponsive_or_native_rejected_windows_are_not_ready(self):
        native = FakeNative({1: {"pid": 1, "responsive": False}, 2: {"pid": 2, "valid": False}})
        with patch.object(windows, "_native", return_value=native):
            self.assertIsNone(windows.find_ready_window(TARGET))

    def test_minimized_existing_window_is_detected(self):
        native = FakeNative({5: {"pid": 5, "minimized": True, "rect": (-32000, -32000, -31840, -31980)}})
        with patch.object(windows, "_native", return_value=native):
            result = windows.find_ready_window(TARGET)
        self.assertTrue(result.minimized)
        self.assertEqual(result.hwnd, 5)

    def test_larger_visible_window_precedes_minimized_or_small_window(self):
        native = FakeNative({
            1: {"pid": 1, "minimized": True},
            2: {"pid": 1, "rect": (0, 0, 800, 600)},
            3: {"pid": 1, "rect": (-1920, 0, 0, 1080)},
        })
        with patch.object(windows, "_native", return_value=native):
            result = windows.find_ready_window(TARGET)
        self.assertEqual(result.hwnd, 3)
        self.assertEqual(native.identity_calls, [1])

    def test_pe_gui_and_console_subsystems(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "Codex.exe"
            content = bytearray(512)
            content[:2] = b"MZ"
            struct.pack_into("<I", content, 0x3C, 128)
            content[128:132] = b"PE\0\0"
            struct.pack_into("<H", content, 152, 0x20B)
            struct.pack_into("<H", content, 220, 2)
            file.write_bytes(content)
            self.assertTrue(windows._is_gui_executable(str(file)))
            struct.pack_into("<H", content, 220, 3)
            file.write_bytes(content)
            self.assertFalse(windows._is_gui_executable(str(file)))
            file.write_text("not an executable")
            self.assertFalse(windows._is_gui_executable(str(file)))

    def test_explicit_console_exe_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "codex.exe"
            file.write_bytes(b"CLI")
            with self.assertRaises(windows.DiscoveryError):
                windows.discover_targets(str(file))

    def test_aumid_launch_uses_shell_registration_and_argument_array(self):
        with patch.object(windows.os, "name", "nt"), patch.object(windows.subprocess, "Popen") as popen:
            windows.launch_target(TARGET)
        arguments = popen.call_args.args[0]
        self.assertEqual(arguments[1], "shell:AppsFolder\\" + FAMILY + "!App")
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_focus_reports_observed_native_result(self):
        for expected in (True, False):
            with patch.object(windows, "_native") as native:
                native.return_value.focus.return_value = expected
                self.assertEqual(windows.focus_window(123), expected)
                native.return_value.focus.assert_called_once_with(123)


class ExternalSpawnTests(unittest.TestCase):
    def test_child_environment_removed_bundle_and_qt_only(self):
        original = {
            "Path": r'C:\Bundle\PySide6;"C:\Bundle\shiboken6";C:\Bundle2;C:\Windows\System32',
            "QT_PLUGIN_PATH": r"C:\Bundle\PySide6\plugins",
            "QTWEBENGINEPROCESS_PATH": r"C:\Bundle\PySide6\QtWebEngineProcess.exe",
            "QML2_IMPORT_PATH": r"C:\Bundle\PySide6\qml",
            "QML_IMPORT_PATH": r"C:\Bundle\PySide6\qml",
            "USER_SETTING": "keep me",
        }
        clean = windows._external_environment(original, r"C:\Bundle")
        self.assertEqual(clean, {"Path": r"C:\Bundle2;C:\Windows\System32", "USER_SETTING": "keep me"})
        self.assertIn("QT_PLUGIN_PATH", original)
        self.assertIn(r"C:\Bundle\PySide6", original["Path"])

    def test_frozen_spawn_restores_dll_directory_without_mutating_caller(self):
        original = {"PATH": r"C:\Bundle\PySide6;C:\Windows\System32", "QT_PLUGIN_PATH": "own plugins"}
        api = Mock()
        api.current.return_value = r"C:\Bundle"
        with patch.object(windows.sys, "frozen", True, create=True), \
                patch.object(windows.sys, "_MEIPASS", r"C:\Bundle", create=True), \
                patch.object(windows, "_dll_directory_api", return_value=api), \
                patch.object(windows.subprocess, "Popen") as popen:
            result = windows._spawn_external(["external.exe"], env=original, cwd="target")
        self.assertIs(result, popen.return_value)
        self.assertEqual(popen.call_args.kwargs["env"], {"PATH": r"C:\Windows\System32"})
        self.assertEqual(popen.call_args.kwargs["cwd"], "target")
        self.assertEqual([call.args for call in api.change.call_args_list], [(None,), (r"C:\Bundle",)])
        self.assertEqual(original["QT_PLUGIN_PATH"], "own plugins")

    def test_frozen_popen_failure_still_restores_dll_directory(self):
        api = Mock()
        api.current.return_value = r"C:\Bundle"
        with patch.object(windows.sys, "frozen", True, create=True), \
                patch.object(windows.sys, "_MEIPASS", r"C:\Bundle", create=True), \
                patch.object(windows, "_dll_directory_api", return_value=api), \
                patch.object(windows.subprocess, "Popen", side_effect=OSError("create failed")):
            with self.assertRaisesRegex(OSError, "create failed"):
                windows._spawn_external(["external.exe"], env={})
        self.assertEqual([call.args for call in api.change.call_args_list], [(None,), (r"C:\Bundle",)])

    def test_unfrozen_spawn_uses_unchanged_environment(self):
        environment = {"PATH": r"C:\Bundle\PySide6", "QT_PLUGIN_PATH": "user plugins"}
        with patch.object(windows.sys, "frozen", False, create=True), \
                patch.object(windows, "_dll_directory_api") as api, \
                patch.object(windows.subprocess, "Popen") as popen:
            windows._spawn_external(["external.exe"], env=environment)
        api.assert_not_called()
        self.assertIs(popen.call_args.kwargs["env"], environment)

    def test_discovery_wait_occurs_after_dll_directory_restore(self):
        api = Mock()
        api.current.return_value = r"C:\Bundle"
        process = Mock(returncode=0)
        def communicate(**kwargs):
            self.assertEqual(kwargs, {"timeout": 15})
            self.assertEqual([call.args for call in api.change.call_args_list], [(None,), (r"C:\Bundle",)])
            return "[]", ""
        process.communicate.side_effect = communicate
        with patch.object(windows.sys, "frozen", True, create=True), \
                patch.object(windows.sys, "_MEIPASS", r"C:\Bundle", create=True), \
                patch.object(windows, "_dll_directory_api", return_value=api), \
                patch.object(windows.subprocess, "Popen", return_value=process):
            self.assertEqual(windows._run_discovery(), [])
        process.kill.assert_not_called()

    def test_discovery_timeout_kills_only_owned_powershell(self):
        process = Mock(returncode=0)
        process.communicate.side_effect = [windows.subprocess.TimeoutExpired("PowerShell", 15), ("", "")]
        with patch.object(windows, "_spawn_external", return_value=process):
            with self.assertRaises(windows.DiscoveryError):
                windows._run_discovery()
        process.kill.assert_called_once_with()
        self.assertEqual(process.communicate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
