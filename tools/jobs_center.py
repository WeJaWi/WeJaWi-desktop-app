# tools/jobs_center.py
from __future__ import annotations
import os
import sys
from typing import Dict, Any
from PyQt5 import QtWidgets, QtCore

try:
    from core.jobs import JobManager
except Exception:
    from jobs import JobManager


def _basename(p: str) -> str:
    return os.path.basename(p) if p else "—"

class JobsCenterPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: Dict[str, int] = {}  # job_id -> row
        self._log_watchers: Dict[str, QtCore.QFileSystemWatcher] = {}
        self._current_job: str | None = None
        self._build()

        self.jm = JobManager.instance()
        self.jm.jobAdded.connect(self.on_job_added)
        self.jm.jobProgress.connect(self.on_job_progress)
        self.jm.jobLog.connect(self.on_job_log)
        self.jm.jobFinished.connect(self.on_job_finished)

    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel("🧰 Jobs Center")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        # table
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Job ID", "Tool", "Progress", "Exit", "Log file", "Output"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        root.addWidget(self.table, 2)

        # controls
        bar = QtWidgets.QHBoxLayout()
        self.btn_open_logs = QtWidgets.QPushButton("Open Logs Folder")
        self.btn_open_logs.clicked.connect(self._open_logs_folder)
        self.btn_cancel = QtWidgets.QPushButton("Cancel Selected")
        self.btn_cancel.clicked.connect(self._cancel_selected)
        bar.addWidget(self.btn_open_logs)
        bar.addStretch(1)
        bar.addWidget(self.btn_cancel)
        root.addLayout(bar)

        # log viewer
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True)
        root.addWidget(QtWidgets.QLabel("Live log"))
        root.addWidget(self.log, 3)

    def _open_logs_folder(self):
        jm = JobManager.instance()
        try:
            root = jm.logs_root()
        except Exception:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
        if sys.platform == "darwin":
            opener = "open"
        elif os.name == "nt":
            opener = "explorer"
        else:
            opener = "xdg-open"
        QtCore.QProcess.startDetached(opener, [root])

    def _cancel_selected(self):
        row = self.table.currentRow()
        if row < 0: return
        job_id = self.table.item(row, 0).text()
        JobManager.instance().cancel(job_id)

    def _on_row_selected(self):
        row = self.table.currentRow()
        if row < 0:
            self._current_job = None
            self.log.setPlainText("")
            return
        job_id = self.table.item(row, 0).text()
        self._current_job = job_id
        # Load current log file once
        path_item = self.table.item(row, 4)
        if path_item:
            path = path_item.data(QtCore.Qt.UserRole) or ""
            if path and os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.log.setPlainText(f.read())
                    self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
                except Exception:
                    pass

    # ---- JobManager signals ----
    @QtCore.pyqtSlot(str, dict)
    def on_job_added(self, job_id: str, meta: Dict[str, Any]):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._rows[job_id] = r
        tool = meta.get("tool") or meta.get("tag") or "process"
        out_json = meta.get("out_json", "")

        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(job_id))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(tool)))
        self.table.setItem(r, 2, QtWidgets.QTableWidgetItem("0%"))
        self.table.setItem(r, 3, QtWidgets.QTableWidgetItem("…"))
        log_item = QtWidgets.QTableWidgetItem(_basename(meta.get("log_path","")))
        log_item.setData(QtCore.Qt.UserRole, meta.get("log_path",""))
        self.table.setItem(r, 4, log_item)
        self.table.setItem(r, 5, QtWidgets.QTableWidgetItem(out_json or "—"))

    @QtCore.pyqtSlot(str, int)
    def on_job_progress(self, job_id: str, pct: int):
        r = self._rows.get(job_id, -1)
        if r >= 0:
            self.table.item(r, 2).setText(f"{pct}%")

    @QtCore.pyqtSlot(str, str)
    def on_job_log(self, job_id: str, line: str):
        if self._current_job == job_id:
            self.log.appendPlainText(line)
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    @QtCore.pyqtSlot(str, int)
    def on_job_finished(self, job_id: str, exit_code: int):
        r = self._rows.get(job_id, -1)
        if r >= 0:
            self.table.item(r, 3).setText(str(exit_code))
            # bump progress to 100% if not already
            if not self.table.item(r, 2).text().startswith("100"):
                self.table.item(r, 2).setText("100%")
