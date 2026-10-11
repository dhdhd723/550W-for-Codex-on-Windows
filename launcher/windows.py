"""Read-only Windows app discovery and public Win32 launch/window integration.

No injection, resource patching, process termination, or title-based identity.
The native APIs are deliberately behind a small adapter so policy is testable.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import logging
import ntpath
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
from typing import Iterable

log = logging.getLogger(__name__)
_EXTERNAL_SPAWN_LOCK = threading.Lock()


class _DllDirectoryApi:
    """Isolated binding: discovery can run before any GUI modules are imported."""
    def __init__(self):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.get = kernel32.GetDllDirectoryW
        self.get.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
        self.get.restype = wintypes.DWORD
        self.set = kernel32.SetDllDirectoryW
        self.set.argtypes = [wintypes.LPCWSTR]
        self.set.restype = wintypes.BOOL

    def current(self) -> str | None:
        buffer = ctypes.create_unicode_buffer(32768)
        ctypes.set_last_error(0)
        length = self.get(len(buffer), buffer)
        if length >= len(buffer):
            raise OSError("Windows DLL 搜索目录过长。")
        if not length and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.value or None

    def change(self, directory: str | None) -> None:
        if not self.set(directory):
            raise ctypes.WinError(ctypes.get_last_error())


def _dll_directory_api() -> _DllDirectoryApi:
    return _DllDirectoryApi()


def _inside_bundle(path: str, bundle: str) -> bool:
    try:
        normalized = _normal_path(os.path.expandvars(path.strip('"')))
        root = _normal_path(bundle)
        return ntpath.commonpath((normalized, root)) == root
    except (ValueError, OSError):
        return False


def _external_environment(environment: dict[str, str], bundle: str) -> dict[str, str]:
    """Sanitize an environment copy; the launcher's Qt environment stays intact."""
    clean = {}
    for key, value in environment.items():
        upper = key.upper()
        if upper.startswith(("QT_", "QTWEBENGINE", "QML_", "QML2_")):
            continue
        if upper == "PATH":
            value = ";".join(item for item in value.split(";") if item and not _inside_bundle(item, bundle))
        clean[key] = value
    return clean


def _spawn_external(args, **kwargs) -> subprocess.Popen:
    """Create an external child without PyInstaller's inherited Qt/DLL routing.

    SetDllDirectory is process-global. The lock serializes our own child creates,
    but cannot synchronize Qt's internal helper launches. The change is therefore
    restricted to Popen/CreateProcess, restored immediately in finally, and never
    held during communicate/wait. Caller PATH and Qt variables are not modified.
    See PyInstaller's documented Windows external-program launch guidance.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if os.name != "nt" or not getattr(sys, "frozen", False) or not bundle:
        return subprocess.Popen(args, **kwargs)
    supplied = kwargs.pop("env", None)
    kwargs["env"] = _external_environment(dict(os.environ if supplied is None else supplied), str(bundle))
    with _EXTERNAL_SPAWN_LOCK:
        api = _dll_directory_api()
        previous = api.current()
        api.change(None)
        try:
            return subprocess.Popen(args, **kwargs)
        finally:
            api.change(previous)


@dataclass(frozen=True)
class AppTarget:
    kind: str
    value: str
    process_paths: tuple[str, ...] = ()
    display_name: str = "OpenAI Codex"
    package_family: str = ""


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    process_path: str
    rect: tuple[int, int, int, int]
    minimized: bool = False


class DiscoveryError(RuntimeError):
    """The installed app could not safely be discovered."""


def _normal_path(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path.replace("/", "\\")))


def _is_main_executable(path: str) -> bool:
    normalized = _normal_path(path)
    return (ntpath.basename(normalized) in {"chatgpt.exe", "codex.exe"}
            and "\\resources\\" not in normalized
            and "\\node_modules\\" not in normalized)


def _is_gui_executable(path: str) -> bool:
    """PE optional-header subsystem 2 means GUI; reject CLI/aliases/non-PE."""
    try:
        with open(path, "rb") as stream:
            if stream.read(2) != b"MZ":
                return False
            stream.seek(0x3C)
            pe_offset = struct.unpack("<I", stream.read(4))[0]
            if pe_offset > 16 * 1024 * 1024:
                return False
            stream.seek(pe_offset)
            if stream.read(4) != b"PE\0\0":
                return False
            stream.seek(pe_offset + 24)
            magic = struct.unpack("<H", stream.read(2))[0]
            if magic not in (0x10B, 0x20B):
                return False
            # Subsystem offset is 68 in both PE32 and PE32+ optional headers.
            stream.seek(pe_offset + 24 + 68)
            return struct.unpack("<H", stream.read(2))[0] == 2
    except (OSError, struct.error):
        return False


_DISCOVERY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$startApps = @(Get-StartApps | Where-Object { $_.AppID -match '^OpenAI\..*Codex.*!' })
$packages = @(Get-AppxPackage | Where-Object { $_.Name -match '^OpenAI\..*Codex' })
$results = @()
foreach ($package in $packages) {
    $manifest = Get-AppxPackageManifest -Package $package
    foreach ($application in @($manifest.Package.Applications.Application)) {
        $relative = [string]$application.Executable
        if ($relative -notmatch '(^|[/\\])(ChatGPT|Codex)\.exe$' -or $relative -match '(^|[/\\])resources[/\\]') { continue }
        $aumid = $package.PackageFamilyName + '!' + $application.Id
        $startEntry = $startApps | Where-Object { $_.AppID -eq $aumid } | Select-Object -First 1
        $label = if ($startEntry) { $startEntry.Name } else { 'OpenAI Codex' }
        $results += [pscustomobject]@{
            kind = 'aumid'; value = $aumid; display_name = $label
            package_family = $package.PackageFamilyName
            process_paths = @(Join-Path -Path $package.InstallLocation -ChildPath $relative)
        }
    }
}
ConvertTo-Json -InputObject @($results) -Depth 5 -Compress
"""


def _run_discovery() -> list[dict]:
    if os.name != "nt":
        return []
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    powershell = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    try:
        process = _spawn_external(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", _DISCOVERY_SCRIPT],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            # Only this read-only discovery helper is ours; never kill Codex.
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, process.args, stdout, stderr)
        payload = json.loads(stdout.strip().lstrip("\ufeff") or "[]")
        return payload if isinstance(payload, list) else [payload]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise DiscoveryError("无法读取 Windows 应用注册信息；可在设置中指定 Codex 桌面版 EXE。") from exc


def _targets_from_records(records: Iterable[dict]) -> list[AppTarget]:
    targets: list[AppTarget] = []
    seen: set[str] = set()
    for item in records:
        value = str(item.get("value", ""))
        family = str(item.get("package_family", ""))
        paths = tuple(str(p) for p in item.get("process_paths", ()) if _is_main_executable(str(p)))
        if (not family.lower().startswith("openai.") or "codex" not in family.lower()
                or not value.startswith(family + "!") or not paths or value in seen):
            continue
        seen.add(value)
        targets.append(AppTarget("aumid", value, paths, str(item.get("display_name") or "OpenAI Codex"), family))
    # The stable main App entry precedes any future auxiliary GUI application.
    return sorted(targets, key=lambda target: (not target.value.endswith("!App"), target.value))


def discover_targets(executable: str | None = None) -> list[AppTarget]:
    """Current-user package registration, or an explicitly selected GUI .exe.

    Package identity rather than the misleading Start-menu label selects Codex.
    A specified executable overrides package discovery and must be PE GUI.
    """
    if executable:
        path = str(Path(os.path.expandvars(executable)).expanduser().resolve())
        if not Path(path).is_file() or Path(path).suffix.lower() != ".exe":
            raise DiscoveryError("指定的 Codex 桌面版 EXE 不存在。")
        if not _is_gui_executable(path):
            raise DiscoveryError("指定文件不是 Windows GUI 程序；请勿选择 Codex CLI 或应用执行别名。")
        return [AppTarget("exe", path, (path,), "OpenAI Codex（指定 EXE）")]
    # Read the actual registered entry point rather than infer GUI from its name.
    targets = _targets_from_records(_run_discovery())
    return [target for target in targets if any(_is_gui_executable(path) for path in target.process_paths)]


def launch_target(target: AppTarget) -> None:
    """Launch through Windows shell registration, never a hard-coded package path."""
    if os.name != "nt":
        raise OSError("Codex 550C Launcher 只支持 Windows。")
    if target.kind == "aumid":
        if (not target.package_family or not target.value.startswith(target.package_family + "!")
                or any(char in target.value for char in '\"\r\n/\\')):
            raise ValueError("无效的 Windows 应用标识。")
        explorer = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe")
        _spawn_external([explorer, "shell:AppsFolder\\" + target.value],
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    elif target.kind == "exe":
        if not _is_gui_executable(target.value):
            raise DiscoveryError("Codex EXE 不可用或不是 GUI 程序。")
        _spawn_external([target.value], cwd=str(Path(target.value).parent))
    else:
        raise ValueError("不支持的启动目标类型。")


class _Native:
    """Pointer-width-correct Windows API declarations for 32/64-bit Python."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows native APIs are unavailable")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        self.enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.c_ssize_t)
        declarations = (
            (self.user32, "EnumWindows", [self.enum_proc, ctypes.c_ssize_t], wintypes.BOOL),
            (self.user32, "IsWindow", [wintypes.HWND], wintypes.BOOL),
            (self.user32, "IsWindowVisible", [wintypes.HWND], wintypes.BOOL),
            (self.user32, "IsWindowEnabled", [wintypes.HWND], wintypes.BOOL),
            (self.user32, "IsIconic", [wintypes.HWND], wintypes.BOOL),
            (self.user32, "GetWindow", [wintypes.HWND, wintypes.UINT], wintypes.HWND),
            (self.user32, "GetWindowRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            (self.user32, "GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            (self.user32, "GetWindowTextW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            (self.user32, "GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int),
            (self.user32, "SendMessageTimeoutW", [wintypes.HWND, wintypes.UINT, ctypes.c_size_t,
                 ctypes.c_ssize_t, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)], ctypes.c_ssize_t),
            (self.user32, "ShowWindowAsync", [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
            (self.user32, "SetForegroundWindow", [wintypes.HWND], wintypes.BOOL),
            (self.user32, "GetForegroundWindow", [], wintypes.HWND),
            (self.kernel32, "OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel32, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel32, "QueryFullProcessImageNameW", [wintypes.HANDLE, wintypes.DWORD,
                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.kernel32, "GetPackageFamilyName", [wintypes.HANDLE, ctypes.POINTER(wintypes.UINT),
                wintypes.LPWSTR], wintypes.LONG),
            (self.dwmapi, "DwmGetWindowAttribute", [wintypes.HWND, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD], wintypes.LONG),
        )
        for library, name, args, result in declarations:
            function = getattr(library, name)
            function.argtypes, function.restype = args, result
        self.hung_check = getattr(self.user32, "IsHungAppWindow", None)
        if self.hung_check:
            self.hung_check.argtypes = [wintypes.HWND]
            self.hung_check.restype = wintypes.BOOL

    def windows(self) -> list[int]:
        handles: list[int] = []
        @self.enum_proc
        def callback(hwnd, _):
            handles.append(int(hwnd))
            return True
        if not self.user32.EnumWindows(callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return handles

    def basic(self, hwnd: int) -> tuple[int, str, tuple[int, int, int, int], bool] | None:
        if (not self.user32.IsWindow(hwnd) or not self.user32.IsWindowVisible(hwnd)
                or not self.user32.IsWindowEnabled(hwnd) or self.user32.GetWindow(hwnd, 4)):
            return None
        cloaked = wintypes.DWORD()
        # A window on an inactive virtual desktop must not be mistaken for visible.
        if (self.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0
                and cloaked.value):
            return None
        minimized = bool(self.user32.IsIconic(hwnd))
        rect = wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        bounds = (rect.left, rect.top, rect.right, rect.bottom)
        # Minimized windows have deliberately tiny rects; permit them to restore.
        if not minimized and (rect.right - rect.left < 300 or rect.bottom - rect.top < 200):
            return None
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        length = self.user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(min(length + 1, 4096))
        self.user32.GetWindowTextW(hwnd, title, len(title))
        return pid.value, title.value, bounds, minimized

    def identity(self, pid: int) -> tuple[str, str]:
        handle = self.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return "", ""
        try:
            length = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(length.value)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
                return "", ""
            family_length = wintypes.UINT()
            family = ""
            result = self.kernel32.GetPackageFamilyName(handle, ctypes.byref(family_length), None)
            if result == 122 and 0 < family_length.value <= 1024:
                buffer = ctypes.create_unicode_buffer(family_length.value)
                if self.kernel32.GetPackageFamilyName(handle, ctypes.byref(family_length), buffer) == 0:
                    family = buffer.value
            return path.value, family
        finally:
            self.kernel32.CloseHandle(handle)

    def responsive(self, hwnd: int) -> bool:
        if self.hung_check and self.hung_check(hwnd):
            return False
        result = ctypes.c_size_t()
        # Only one identified window receives a harmless WM_NULL; no broadcast.
        return bool(self.user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x2 | 0x20, 100, ctypes.byref(result)))

    def focus(self, hwnd: int) -> bool:
        if not self.user32.IsWindow(hwnd):
            return False
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindowAsync(hwnd, 9)  # SW_RESTORE
        else:
            self.user32.ShowWindowAsync(hwnd, 5)  # SW_SHOW
        self.user32.SetForegroundWindow(hwnd)
        # Return observed focus, not the requested action. Windows may decline.
        return self.user32.GetForegroundWindow() == hwnd


_NATIVE: _Native | None = None


def _native() -> _Native:
    global _NATIVE
    if _NATIVE is None:
        _NATIVE = _Native()
    return _NATIVE


def _matches_identity(target: AppTarget, process_path: str, package_family: str) -> bool:
    if not process_path:
        return False
    path = _normal_path(process_path)
    known_paths = {_normal_path(value) for value in target.process_paths}
    if path in known_paths:
        return True
    # If Windows updates the package during launcher startup, family remains stable.
    # Entry-point basename must also match; helpers/CLI within the package fail.
    return bool(target.kind == "aumid" and target.package_family
                and package_family.casefold() == target.package_family.casefold()
                and _is_main_executable(path)
                and ntpath.basename(path) in {ntpath.basename(value) for value in known_paths})


def find_ready_window(target: AppTarget, exclude_pid: int | None = None) -> WindowInfo | None:
    """A responsive main native window, not proof of login/backend readiness.

    Caller should require repeated observations before handing off. Existing,
    minimized windows are accepted; titles are retained for diagnostics only.
    """
    native = _native()
    candidates: list[WindowInfo] = []
    identities: dict[int, tuple[str, str]] = {}
    for hwnd in native.windows():
        basic = native.basic(hwnd)
        if basic is None:
            continue
        pid, title, rect, minimized = basic
        if pid == exclude_pid:
            continue
        if pid not in identities:
            identities[pid] = native.identity(pid)
        process_path, family = identities[pid]
        if not _matches_identity(target, process_path, family):
            continue
        if native.responsive(hwnd):
            candidates.append(WindowInfo(hwnd, pid, title, process_path, rect, minimized))
    if not candidates:
        return None
    # Foreground/topmost order from EnumWindows is preserved for equal-size windows.
    return max(candidates, key=lambda window: (not window.minimized,
               max(0, window.rect[2] - window.rect[0]) * max(0, window.rect[3] - window.rect[1])))


def focus_window(hwnd: int) -> bool:
    """Restore/show and request focus. Never synthesize input to bypass Windows."""
    try:
        return _native().focus(hwnd)
    except OSError:
        log.exception("Unable to focus Codex window")
        return False
