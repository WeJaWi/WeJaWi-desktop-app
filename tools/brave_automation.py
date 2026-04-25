from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

from PyQt5 import QtCore, QtWidgets

from core.logging_utils import get_logger

logger = get_logger(__name__)

import sys

BRAVE_CANDIDATES = [
    # macOS
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    # Linux
    "/usr/bin/brave-browser",
    "/usr/bin/brave",
    "/snap/bin/brave",
    # Windows
    os.path.join(os.environ.get("PROGRAMFILES", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "BraveSoftware", "Brave-Browser", "Application", "brave.exe"),
]


def _guess_brave_path() -> str:
    for candidate in BRAVE_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return candidate
    found = shutil.which("brave-browser") or shutil.which("brave")
    if found:
        return found
    return "brave.exe" if os.name == "nt" else "brave"


@dataclass
class ClickAction:
    x: int
    y: int
    delay: Optional[float]


class AutomationCancelled(RuntimeError):
    pass


class BraveAutomationThread(QtCore.QThread):
    done = QtCore.pyqtSignal(str, str)
    log = QtCore.pyqtSignal(str)

    def __init__(
        self,
        browser_path: str,
        target_url: str,
        actions: List[ClickAction],
        launch_wait: float,
        move_duration: float,
        default_delay: float,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.browser_path = browser_path.strip()
        self.target_url = target_url.strip()
        self.actions = actions
        self.launch_wait = max(0.0, float(launch_wait))
        self.move_duration = max(0.0, float(move_duration))
        self.default_delay = max(0.0, float(default_delay))
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def _wait_with_cancel(self, duration: float) -> None:
        deadline = time.monotonic() + max(0.0, duration)
        while time.monotonic() < deadline:
            if self._cancel.is_set():
                raise AutomationCancelled()
            time.sleep(0.05)

    def _resolve_executable(self) -> str:
        if not self.browser_path:
            resolved = shutil.which("brave-browser") or shutil.which("brave") or _guess_brave_path()
            if not resolved or not (os.path.isfile(resolved) or shutil.which(resolved)):
                raise FileNotFoundError("Brave executable not found. Provide the full path to the Brave binary.")
            return resolved
        if os.path.isabs(self.browser_path):
            if not os.path.isfile(self.browser_path):
                raise FileNotFoundError(f"Browser executable not found: {self.browser_path}")
            return self.browser_path
        resolved = shutil.which(self.browser_path)
        if not resolved:
            raise FileNotFoundError(f"Browser executable not found: {self.browser_path}")
        return resolved

    def run(self):
        try:
            try:
                import pyautogui  # type: ignore
            except Exception as exc:
                raise RuntimeError("pyautogui is required for Brave automation. Install it with 'pip install pyautogui'.") from exc

            pyautogui.FAILSAFE = True

            exe = self._resolve_executable()
            cmd = [exe]
            if self.target_url:
                cmd.extend(["--new-window", self.target_url])
            else:
                cmd.append("--new-window")

            self.log.emit(f"Launching Brave: {' '.join(cmd)}")
            logger.info("Launching Brave automation (cmd=%s)", cmd)
            proc = subprocess.Popen(cmd)

            if self.launch_wait > 0:
                self.log.emit(f"Waiting {self.launch_wait:.2f}s for the page to load")
                self._wait_with_cancel(self.launch_wait)

            for index, action in enumerate(self.actions, start=1):
                if self._cancel.is_set():
                    raise AutomationCancelled()
                self.log.emit(f"Step {index}: move to ({action.x}, {action.y})")
                pyautogui.moveTo(action.x, action.y, duration=self.move_duration)
                if self._cancel.is_set():
                    raise AutomationCancelled()
                pyautogui.click()
                delay = action.delay if action.delay is not None else self.default_delay
                if delay > 0:
                    self.log.emit(f"Waiting {delay:.2f}s")
                    self._wait_with_cancel(delay)

            self.done.emit("ok", "Automation completed.")
        except AutomationCancelled:
            self.done.emit("cancel", "Automation cancelled.")
        except Exception as exc:
            logger.exception("Brave automation failed")
            self.done.emit("err", str(exc))
        finally:
            self._cancel.clear()


def parse_click_pattern(raw: str) -> List[ClickAction]:
    actions: List[ClickAction] = []
    for idx, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [p.strip() for p in stripped.split(",")]
        if len(parts) < 2:
            raise ValueError(f"Line {idx}: expected 'x, y[, delay]' but got '{line}'.")
        try:
            x = int(float(parts[0]))
            y = int(float(parts[1]))
        except ValueError as exc:
            raise ValueError(f"Line {idx}: x and y must be numbers.") from exc
        delay: Optional[float] = None
        if len(parts) >= 3 and parts[2]:
            try:
                delay = float(parts[2])
            except ValueError as exc:
                raise ValueError(f"Line {idx}: delay must be a number.") from exc
        actions.append(ClickAction(x=x, y=y, delay=delay))
    if not actions:
        raise ValueError("Enter at least one click step.")
    return actions


DEFAULT_PATTERN = (
    "# x, y, optional delay after click in seconds\n"
    "# Example: \n"
    "620, 420, 1.5\n"
    "860, 520\n"
)


class BraveAutomationPage(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._thread: Optional[BraveAutomationThread] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Brave Browser Automation")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        intro = QtWidgets.QLabel(
            "Open Brave in a fresh window, load your automation target, and replay the recorded clicks.\n"
            "Install the 'pyautogui' package for mouse control. Move the pointer to the top-left corner to abort."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        root.addLayout(form)

        self.browser_edit = QtWidgets.QLineEdit(_guess_brave_path())
        pick_btn = QtWidgets.QPushButton("Browse...")
        pick_btn.clicked.connect(self._pick_browser)
        browser_row = QtWidgets.QHBoxLayout()
        browser_row.addWidget(self.browser_edit, 1)
        browser_row.addWidget(pick_btn)
        form.addRow("Brave executable:", browser_row)

        self.url_edit = QtWidgets.QLineEdit("https://")
        form.addRow("Target URL:", self.url_edit)

        self.launch_spin = QtWidgets.QDoubleSpinBox()
        self.launch_spin.setRange(0.0, 60.0)
        self.launch_spin.setDecimals(1)
        self.launch_spin.setSingleStep(0.5)
        self.launch_spin.setValue(4.0)
        self.launch_spin.setSuffix(" s")
        form.addRow("Startup wait:", self.launch_spin)

        self.move_spin = QtWidgets.QDoubleSpinBox()
        self.move_spin.setRange(0.0, 5.0)
        self.move_spin.setDecimals(2)
        self.move_spin.setSingleStep(0.05)
        self.move_spin.setValue(0.25)
        self.move_spin.setSuffix(" s")
        form.addRow("Mouse move duration:", self.move_spin)

        self.default_delay_spin = QtWidgets.QDoubleSpinBox()
        self.default_delay_spin.setRange(0.0, 10.0)
        self.default_delay_spin.setDecimals(2)
        self.default_delay_spin.setSingleStep(0.1)
        self.default_delay_spin.setValue(0.6)
        self.default_delay_spin.setSuffix(" s")
        form.addRow("Default delay:", self.default_delay_spin)

        root.addWidget(QtWidgets.QLabel("Click pattern:"))

        self.pattern_edit = QtWidgets.QPlainTextEdit(DEFAULT_PATTERN)
        self.pattern_edit.setPlaceholderText("x, y, optional delay")
        root.addWidget(self.pattern_edit, 1)

        controls = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Run automation")
        self.run_btn.clicked.connect(self._start)
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.stop_btn.clicked.connect(self._cancel)
        self.stop_btn.setEnabled(False)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        root.addWidget(self.log, 1)

    def _pick_browser(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Brave executable",
            "",
            "Executables (*.exe);;All files (*)"
        )
        if path:
            self.browser_edit.setText(path)

    def _append_log(self, message: str) -> None:
        self.log.appendPlainText(message)
        bar = self.log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _start(self) -> None:
        if self._thread:
            return
        try:
            actions = parse_click_pattern(self.pattern_edit.toPlainText())
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Click pattern", str(exc))
            return

        browser = self.browser_edit.text().strip()
        url = self.url_edit.text().strip()
        if not browser and not url:
            QtWidgets.QMessageBox.warning(self, "Brave", "Provide the Brave executable path or a URL to open.")
            return

        self._thread = BraveAutomationThread(
            browser_path=browser,
            target_url=url,
            actions=actions,
            launch_wait=self.launch_spin.value(),
            move_duration=self.move_spin.value(),
            default_delay=self.default_delay_spin.value(),
            parent=self,
        )
        self._thread.log.connect(self._append_log)
        self._thread.done.connect(self._on_done)

        self._append_log("Starting automation...")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._thread.start()

    def _cancel(self) -> None:
        if self._thread:
            self._append_log("Cancel requested.")
            self._thread.cancel()

    def _on_done(self, status: str, message: str) -> None:
        self._append_log(message)
        QtWidgets.QApplication.beep()
        if status == "err":
            QtWidgets.QMessageBox.critical(self, "Automation", message)
        elif status == "cancel":
            QtWidgets.QMessageBox.information(self, "Automation", "Automation cancelled.")
        else:
            QtWidgets.QMessageBox.information(self, "Automation", "Automation finished.")

        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self._thread:
            self._thread.wait(100)
            self._thread = None

    def on_app_close(self) -> None:
        if self._thread:
            self._thread.cancel()
            self._thread.wait(500)

