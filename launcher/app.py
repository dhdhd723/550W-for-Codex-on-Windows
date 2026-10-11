from __future__ import annotations

from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time

from PySide6.QtCore import (QEasingCurve, QEvent, QLockFile, QObject, QPropertyAnimation,
                            QTimer, Qt, QUrl, QUrlQuery, Signal)
from PySide6.QtGui import QColor, QCursor, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
from PySide6.QtWebEngineWidgets import QWebEngineView

from .config import Config, data_dir, save
from .edition import CURRENT
from .state import Gate
from .windows import discover_targets, find_ready_window, focus_window, launch_target


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


class LocalOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        # No remote fonts, telemetry, downloaded scripts or Codex authentication.
        if info.requestUrl().scheme() not in ("file", "data", "qrc", "about"):
            info.block(True)
        elif info.requestUrl().scheme() == "file":
            requested = Path(info.requestUrl().toLocalFile()).resolve()
            if not requested.is_relative_to((resource_root() / "web").resolve()):
                info.block(True)


class AnimationPage(QWebEnginePage):
    message = Signal(dict)
    script_error = Signal(str)

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith("LAUNCHER:"):
            try:
                payload = json.loads(message[len("LAUNCHER:"):])
                if isinstance(payload, dict):
                    self.message.emit(payload)
            except (ValueError, TypeError):
                logging.warning("invalid_animation_message %s", message[:200])
        elif level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            logging.error("animation_js_error line=%s %s", line, message)
            self.script_error.emit(message)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return url.scheme() in ("file", "about")


class Splash(QWidget):
    def __init__(self, config: Config):
        super().__init__()
        self.setWindowTitle(CURRENT.name)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setStyleSheet("background:#050403;")
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.view = QWebEngineView(self)
        layout.addWidget(self.view)
        self.profile = QWebEngineProfile(self)  # Off-the-record; no persistent browser data.
        self.interceptor = LocalOnly(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.page = AnimationPage(self.profile, self.view)
        self.page.setBackgroundColor(QColor("#050403"))
        self.view.setPage(self.page)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        # CSS/JS siblings are local files too; the interceptor confines file reads to web/.
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        # Local soundtrack starts with the animation; no extra click is required.
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.page.setAudioMuted(not config.sound)
        self.notice = QLabel(self)
        self.notice.setWordWrap(True)
        self.notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notice.setStyleSheet("color:#e8a020;background:#050403;font:14px Consolas,'Microsoft YaHei';padding:12px;")
        self.notice.hide()
        self.url = QUrl.fromLocalFile(str(resource_root() / "web" / "index.html"))
        query = QUrlQuery()
        query.addQueryItem("mode", config.mode)
        query.addQueryItem("color", config.color)
        query.addQueryItem("sound", "on" if config.sound else "off")
        self.url.setQuery(query)
        # Screen coordinates are logical pixels; Qt handles the device pixel ratio.
        QApplication.instance().screenRemoved.connect(self.screen_removed)

    def load(self):
        self.view.load(self.url)

    def screen_removed(self, screen):
        remaining = QApplication.primaryScreen()
        if remaining:
            self.setGeometry(remaining.geometry())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.notice.setGeometry(20, max(0, self.height() - 100), max(1, self.width() - 40), 80)

    def show_notice(self, text):
        self.notice.setText(text)
        self.notice.show()
        self.notice.raise_()

    def js(self, method, *args):
        values = ",".join(json.dumps(arg, ensure_ascii=True) for arg in args)
        self.page.runJavaScript(f"window.launcher && window.launcher.{method}({values});")

    def stop_audio(self):
        # Native mute is immediate even if the renderer or its script has failed.
        # JS cleanup releases the media element when the renderer still responds.
        self.page.setAudioMuted(True)
        self.page.runJavaScript("if (window.launcher && typeof window.launcher.stopAudio === 'function') window.launcher.stopAudio();")


class BackendSignals(QObject):
    selected = Signal(str)
    ready = Signal(object)
    lost = Signal()
    failed = Signal(str)


class Backend:
    """Only read/activate the official app. Never hide, terminate or patch it."""
    def __init__(self, config: Config, signals: BackendSignals):
        self.config = config
        self.signals = signals
        self.stop = threading.Event()
        self.target = None
        self.window = None

    def start(self):
        threading.Thread(target=self.work, name="official-window-probe", daemon=True).start()

    def work(self):
        try:
            targets = discover_targets(self.config.target_executable or None)
            if self.stop.is_set():
                return
            if not targets:
                raise RuntimeError("未找到官方桌面应用。请安装官方应用，或在设置中指定其 GUI EXE（不能指定 Codex CLI）。")
            self.target = targets[0]
            self.signals.selected.emit(self.target.display_name)
            initial = find_ready_window(self.target, exclude_pid=os.getpid())
            if self.stop.is_set():
                return
            if not initial:
                logging.info("official_launch target=%s", self.target.value)
                launch_target(self.target)
            else:
                logging.info("official_already_running hwnd=%s", initial.hwnd)
            candidate, since, ready_handle = None, 0.0, None
            while not self.stop.is_set():
                window = find_ready_window(self.target, exclude_pid=os.getpid())
                now = time.monotonic()
                if window:
                    identity = (window.hwnd, window.pid)
                    if candidate != identity:
                        candidate, since = identity, now
                        self.window = None
                        if ready_handle is not None:
                            ready_handle = None
                            self.signals.lost.emit()
                    if now - since >= 0.35:
                        self.window = window
                        if ready_handle != identity:
                            ready_handle = identity
                            logging.info("official_window_ready hwnd=%s title=%s", window.hwnd, window.title)
                            self.signals.ready.emit(window)
                else:
                    candidate = None
                    self.window = None
                    if ready_handle is not None:
                        ready_handle = None
                        self.signals.lost.emit()
                self.stop.wait(0.2)
        except Exception as error:
            logging.exception("official_backend_error")
            if not self.stop.is_set():
                self.signals.failed.emit(str(error))


class Controller(QObject):
    def __init__(self, app: QApplication, config: Config, preview=False):
        super().__init__()
        self.app, self.config, self.preview = app, config, preview
        self.gate = Gate(animation_done=not config.enabled, window_ready=preview)
        self.window = Splash(config) if config.enabled else None
        self.loaded = False
        self.closed = False
        self.backend = None
        self.signals = BackendSignals(self)
        self.signals.ready.connect(self.official_ready)
        self.signals.lost.connect(self.official_lost)
        self.signals.failed.connect(self.fail)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(lambda: self.fail(f"官方应用在 {config.timeout_seconds} 秒内没有出现可响应主窗口。可从开始菜单自行打开应用。"))
        app.installEventFilter(self)
        if self.window:
            self.window.page.message.connect(self.animation_message)
            self.window.page.script_error.connect(self.renderer_failed)
            self.window.page.renderProcessTerminated.connect(lambda status, code: self.renderer_failed(f"动画渲染进程退出（{code}）"))
            self.window.view.loadFinished.connect(self.load_finished)
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
            self.window.load()
            QTimer.singleShot(10000, self.check_loaded)
        if preview:
            if not config.enabled:
                QTimer.singleShot(0, self.close)
        else:
            self.backend = Backend(config, self.signals)
            self.deadline.start(config.timeout_seconds * 1000)
            # Let the native background reach the screen before discovery/activation.
            QTimer.singleShot(0, self.backend.start)
        app.aboutToQuit.connect(self.stop_backend)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape and not self.gate.failed:
                self.skip()
                return True
            if event.key() == Qt.Key.Key_Q and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.close()
                return True
        if self.window and watched is self.window and event.type() == QEvent.Type.Close:
            self.close()
        return False

    def load_finished(self, ok):
        if not ok:
            self.renderer_failed("动画页面加载失败")

    def check_loaded(self):
        if self.window and not self.loaded and not self.closed:
            self.renderer_failed("动画页面未能初始化；将直接等待官方应用")

    def animation_message(self, payload):
        if self.closed or self.gate.failed:
            return
        event = payload.get("event")
        logging.info("animation_event %s", event)
        if event == "loaded":
            self.loaded = True
            if self.gate.window_ready:
                self.window.js("setReady")
            if self.gate.animation_done:
                self.window.js("skip")
            # A JS timeline failure must not leave a permanent topmost overlay.
            duration = 22000 if self.config.mode == "full" else 8000
            QTimer.singleShot(duration, self.animation_watchdog)
        elif event in ("animation_done", "skip"):
            self.gate.animation_done = True
            self.maybe_exit()
        elif event in ("error", "animation_error"):
            self.renderer_failed(payload.get("message", "动画脚本失败"))
        elif event == "close_requested":
            self.close()

    def animation_watchdog(self):
        if not self.gate.animation_done and not self.closed:
            self.renderer_failed("动画超过预期时长；继续进入官方应用")

    def skip(self):
        if self.closed or self.gate.exiting:
            return
        logging.info("animation_skip_native")
        self.gate.animation_done = True
        if self.window:
            self.window.stop_audio()
        if self.window and self.loaded:
            self.window.js("skip")
        self.maybe_exit()

    def official_ready(self, window):
        if self.closed or self.gate.failed:
            return
        self.gate.window_ready = True
        if self.window and self.loaded:
            self.window.js("setReady")
        self.maybe_exit()

    def official_lost(self):
        if not self.gate.exiting:
            self.gate.window_ready = False
        logging.info("official_window_lost")

    def renderer_failed(self, message):
        if self.closed or self.gate.exiting:
            return
        logging.warning("animation_fail_open %s", message)
        self.gate.animation_done = True
        if self.window:
            self.window.stop_audio()
            self.window.show_notice(message)
        if self.preview:
            self.fail(message)
        else:
            self.maybe_exit()

    def maybe_exit(self):
        if self.closed or self.gate.failed:
            return
        if self.gate.animation_done and not self.gate.window_ready and self.window:
            if self.loaded:
                self.window.js("setWaiting", "正在等待官方应用…")
            self.window.show_notice("正在等待官方应用…  Ctrl+Q 可关闭启动器")
        if not self.gate.begin_exit():
            return
        self.deadline.stop()
        logging.info("handoff_begin")
        if self.window:
            self.window.notice.hide()
            if self.loaded:
                self.window.js("finish")
            # Original two-phase handoff: 200 ms content, then 420 ms native opacity.
            QTimer.singleShot(200, self.fade_background)
        else:
            self.handoff_complete()

    def fade_background(self):
        if self.closed or self.gate.failed:
            return
        self.focus_official()
        self.fade = QPropertyAnimation(self.window, b"windowOpacity", self)
        self.fade.setDuration(420)
        self.fade.setStartValue(1.0)
        self.fade.setEndValue(0.0)
        self.fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.fade.finished.connect(self.handoff_complete)
        self.fade.start()

    def focus_official(self):
        if self.preview or not self.backend or not self.backend.target:
            return True
        try:
            current = find_ready_window(self.backend.target, exclude_pid=os.getpid())
            if current:
                focused = focus_window(current.hwnd)
                logging.info("official_focus result=%s hwnd=%s", focused, current.hwnd)
                return focused
        except Exception:
            logging.exception("official_focus_error")
        return False

    def handoff_complete(self):
        if self.closed or self.gate.failed:
            return
        if self.window:
            self.window.stop_audio()
            self.window.hide()
        if not self.focus_official():
            # Windows may deny foreground stealing. Never fake readiness or force input.
            self.fail("官方应用已响应，但 Windows 未允许切换焦点，或窗口已关闭。请点击任务栏中的官方应用。")
            return
        logging.info("handoff_complete")
        self.close()

    def fail(self, message):
        if self.closed or self.gate.failed:
            return
        logging.error("safe_failure %s", message)
        self.gate.failed = True
        self.deadline.stop()
        self.stop_backend()
        if self.window:
            self.window.stop_audio()
            self.window.hide()
        self.error = QMessageBox(QMessageBox.Icon.Warning, CURRENT.name, message)
        self.error.setInformativeText(f"启动动画已安全关闭。\n日志：{data_dir() / 'launcher.log'}\n此提示将在 8 秒后关闭。")
        self.error.setStandardButtons(QMessageBox.StandardButton.Close)
        self.error.finished.connect(self.close)
        self.error.show()
        QTimer.singleShot(8000, self.close)

    def activate(self):
        if self.window and not self.closed and not self.gate.exiting and not self.gate.failed:
            self.window.raise_()
            self.window.activateWindow()
        logging.info("duplicate_activation")

    def stop_backend(self):
        if self.backend:
            self.backend.stop.set()

    def close(self, *_):
        if self.closed:
            return
        self.closed = True
        self.deadline.stop()
        self.stop_backend()
        if self.window:
            self.window.stop_audio()
            self.window.hide()
        self.app.quit()


class Settings(QDialog):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle(CURRENT.name + " 设置")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled = QCheckBox("显示开屏动画")
        self.enabled.setChecked(config.enabled)
        self.mode = QComboBox()
        self.mode.addItem("简易（约 4 秒）", "brief")
        self.mode.addItem("完整（约 16 秒）", "full")
        self.mode.setCurrentIndex(self.mode.findData(config.mode))
        self.mode.setEnabled(not CURRENT.fixed_mode)
        self.sound = QCheckBox("播放启动声音")
        self.sound.setChecked(config.sound)
        self.sound.setEnabled(not CURRENT.fixed_mode)
        self.color = QComboBox()
        for label, value in (("琥珀", "amber"), ("绿色", "green"), ("青色", "cyan"), ("白色", "white")):
            self.color.addItem(label, value)
        self.color.setCurrentIndex(self.color.findData(config.color))
        self.timeout = QSpinBox()
        self.timeout.setRange(20, 300)
        self.timeout.setSuffix(" 秒")
        self.timeout.setValue(config.timeout_seconds)
        self.target = QLineEdit(config.target_executable)
        self.target.setPlaceholderText("留空：自动检测官方 Windows 应用包")
        form.addRow(self.enabled)
        form.addRow("模式", self.mode)
        form.addRow(self.sound)
        form.addRow("配色", self.color)
        form.addRow("启动等待上限", self.timeout)
        form.addRow("官方 GUI EXE", self.target)
        layout.addLayout(form)
        choose = QPushButton("选择官方桌面应用 EXE…")
        choose.clicked.connect(self.choose_target)
        layout.addWidget(choose)
        note = QLabel("设置只影响此快捷方式。启动器不修改官方文件。\n原作中的固件与节点日志属于动画演示。\nEsc / 点击跳过动画；等待时 Ctrl+Q 关闭启动器。")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.commit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_target(self):
        selected, _ = QFileDialog.getOpenFileName(self, "选择官方桌面 GUI EXE", "", "Windows executable (*.exe)")
        if selected:
            self.target.setText(selected)

    def commit(self):
        try:
            config = Config(self.enabled.isChecked(), self.mode.currentData(), self.color.currentData(),
                            self.timeout.value(), self.target.text().strip(), self.sound.isChecked())
            if config.target_executable:
                discover_targets(config.target_executable)
            save(config)
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, "无法保存设置", str(error))


def run(config: Config, preview=False, settings=False):
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(CURRENT.name)
    app.setWindowIcon(QIcon(str(resource_root() / "assets" / "launcher.ico")))
    if settings:
        return 0 if Settings(config).exec() == QDialog.DialogCode.Accepted else 0
    app.setQuitOnLastWindowClosed(False)
    server = None
    lock = None
    if not preview:
        lock = QLockFile(str(data_dir() / "launcher.lock"))
        lock.setStaleLockTime(0)  # PID liveness still allows recovery after a crash.
        name = "Codex550CLauncher-" + str(data_dir()).replace("\\", "_").replace(":", "_")
        if not lock.tryLock(0):
            socket = QLocalSocket()
            socket.connectToServer(name)
            if socket.waitForConnected(1000):
                socket.write(b"activate\n")
                socket.waitForBytesWritten(1000)
                socket.disconnectFromServer()
            logging.info("duplicate_launch_ignored")
            return 0
        server = QLocalServer()
        QLocalServer.removeServer(name)
        if not server.listen(name):
            logging.warning("activation_pipe_unavailable %s", server.errorString())
    controller = Controller(app, config, preview=preview)
    if server:
        def incoming():
            while server.hasPendingConnections():
                socket = server.nextPendingConnection()
                controller.activate()
                socket.disconnectFromServer()
                socket.deleteLater()
        server.newConnection.connect(incoming)
    code = app.exec()
    if server:
        server.close()
    if lock:
        lock.unlock()
    return code
