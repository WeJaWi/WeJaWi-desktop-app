import os
import tempfile
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from tools.captions import FFmpegRunner, which_ffmpeg, get_video_duration, _pick_encoder_args


class _DropList(QtWidgets.QListWidget):
    """QListWidget that also accepts drag-and-drop from the OS file manager."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            e.setDropAction(QtCore.Qt.CopyAction)
            e.accept()
            paths = [u.toLocalFile() for u in e.mimeData().urls()
                     if u.toLocalFile().lower().split(".")[-1]
                     in ("mp4", "mov", "mkv", "avi", "webm", "m4v")]
            self.filesDropped.emit(paths)
        else:
            super().dropEvent(e)

    filesDropped = QtCore.pyqtSignal(list)


class StitchUpPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._runner: Optional[FFmpegRunner] = None
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        root.addWidget(QtWidgets.QLabel("Stitch Up", objectName="PageTitle"))

        sub = QtWidgets.QLabel(
            "Drag clips into the list or use Add — reorder by dragging rows "
            "or with the arrow buttons. Stitch merges them into a single video."
        )
        sub.setWordWrap(True)
        sub.setObjectName("PageSubtitle")
        root.addWidget(sub)

        # ── main body ──────────────────────────────────────────────────────────
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # Left: clip list
        clips_box = QtWidgets.QGroupBox("Clips")
        clips_v = QtWidgets.QVBoxLayout(clips_box)
        clips_v.setSpacing(6)

        self.clip_list = _DropList()
        self.clip_list.filesDropped.connect(self._add_paths)
        clips_v.addWidget(self.clip_list, 1)

        list_btns = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("Add clips…")
        btn_add.clicked.connect(self.on_add)
        btn_remove = QtWidgets.QPushButton("Remove")
        btn_remove.clicked.connect(self.on_remove)
        btn_clear = QtWidgets.QPushButton("Clear all")
        btn_clear.clicked.connect(self.on_clear)
        for b in (btn_add, btn_remove, btn_clear):
            list_btns.addWidget(b)
        list_btns.addStretch(1)
        clips_v.addLayout(list_btns)
        body.addWidget(clips_box, 3)

        # Right: order + output settings
        right_w = QtWidgets.QWidget()
        right_v = QtWidgets.QVBoxLayout(right_w)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(10)

        order_box = QtWidgets.QGroupBox("Order")
        order_v = QtWidgets.QVBoxLayout(order_box)
        order_v.setSpacing(4)
        btn_up = QtWidgets.QPushButton("▲  Move up")
        btn_dn = QtWidgets.QPushButton("▼  Move down")
        btn_up.clicked.connect(lambda: self._move(-1))
        btn_dn.clicked.connect(lambda: self._move(1))
        order_v.addWidget(btn_up)
        order_v.addWidget(btn_dn)
        order_v.addStretch(1)
        right_v.addWidget(order_box)

        out_box = QtWidgets.QGroupBox("Output")
        out_form = QtWidgets.QFormLayout(out_box)
        out_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        out_form.setVerticalSpacing(8)

        out_row = QtWidgets.QHBoxLayout()
        self.out_edit = QtWidgets.QLineEdit("stitched.mp4")
        btn_out = QtWidgets.QPushButton("Pick…")
        btn_out.clicked.connect(self.on_pick_out)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(btn_out)
        out_wrap = QtWidgets.QWidget()
        out_wrap.setLayout(out_row)
        out_form.addRow("File:", out_wrap)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("Re-encode (works with any sources)", "encode")
        self.mode_combo.addItem("Fast copy (sources must share codec)", "copy")
        self.mode_combo.setCurrentIndex(0)
        out_form.addRow("Mode:", self.mode_combo)

        self.encoder_combo = QtWidgets.QComboBox()
        self.encoder_combo.addItem("Auto (GPU if available)", "auto")
        self.encoder_combo.addItem("NVIDIA NVENC", "nvenc")
        self.encoder_combo.addItem("AMD AMF", "amf")
        self.encoder_combo.addItem("CPU (libx264)", "cpu")
        out_form.addRow("Encoder:", self.encoder_combo)

        right_v.addWidget(out_box)
        right_v.addStretch(1)
        right_w.setMaximumWidth(320)
        body.addWidget(right_w, 1)

        # ── render strip ───────────────────────────────────────────────────────
        render_row = QtWidgets.QHBoxLayout()
        self.btn_render = QtWidgets.QPushButton("Stitch & render")
        self.btn_render.setMinimumHeight(36)
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_render.clicked.connect(self.on_render)
        self.btn_cancel.clicked.connect(self.on_cancel)
        render_row.addWidget(self.btn_render, 1)
        render_row.addWidget(self.btn_cancel)
        root.addLayout(render_row)

        self.pbar = QtWidgets.QProgressBar()
        self.pbar.setRange(0, 100)
        root.addWidget(self.pbar)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(130)
        root.addWidget(self.log)

    # ── helpers ────────────────────────────────────────────────────────────────

    def log_msg(self, s: str):
        self.log.appendPlainText(s)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _move(self, delta: int):
        row = self.clip_list.currentRow()
        new_row = row + delta
        if row < 0 or not (0 <= new_row < self.clip_list.count()):
            return
        item = self.clip_list.takeItem(row)
        self.clip_list.insertItem(new_row, item)
        self.clip_list.setCurrentRow(new_row)

    def _files(self) -> List[str]:
        return [
            self.clip_list.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.clip_list.count())
        ]

    def _add_paths(self, paths: List[str]):
        for p in paths:
            item = QtWidgets.QListWidgetItem()
            dur = get_video_duration(p)
            if dur is not None:
                mins, secs = int(dur // 60), int(dur % 60)
                label = f"{os.path.basename(p)}    [{mins}:{secs:02d}]"
            else:
                label = os.path.basename(p)
            item.setText(label)
            item.setData(QtCore.Qt.UserRole, p)
            item.setToolTip(p)
            self.clip_list.addItem(item)

    # ── actions ────────────────────────────────────────────────────────────────

    def on_add(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add clips", "",
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)",
        )
        self._add_paths(paths)

    def on_remove(self):
        for item in self.clip_list.selectedItems():
            self.clip_list.takeItem(self.clip_list.row(item))

    def on_clear(self):
        self.clip_list.clear()

    def on_pick_out(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save stitched video", "", "MP4 Video (*.mp4)"
        )
        if path:
            if not path.lower().endswith(".mp4"):
                path += ".mp4"
            self.out_edit.setText(path)

    def on_cancel(self):
        if self._runner:
            self._runner.cancel()

    def on_render(self):
        files = self._files()
        if len(files) < 2:
            QtWidgets.QMessageBox.warning(
                self, "Stitch Up", "Add at least 2 clips to stitch."
            )
            return
        if not which_ffmpeg():
            QtWidgets.QMessageBox.critical(
                self, "FFmpeg", "FFmpeg not found in PATH.\nInstall it with: brew install ffmpeg"
            )
            return

        out_path = self.out_edit.text().strip() or "stitched.mp4"
        tmpdir = tempfile.mkdtemp(prefix="wejawi_stitch_")
        list_path = os.path.join(tmpdir, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in files:
                escaped = p.replace("\\", "/").replace("'", "\\'")
                f.write(f"file '{escaped}'\n")

        mode = self.mode_combo.currentData() or "encode"
        total_dur = sum((get_video_duration(p) or 0.0) for p in files) or 1.0

        if mode == "copy":
            cmd = [
                which_ffmpeg(), "-hide_banner", "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                "-c", "copy",
                "-progress", "pipe:1", "-nostats",
                out_path,
            ]
            self.log_msg(f"Stitching {len(files)} clips (stream copy)…")
        else:
            enc_args, enc_name = _pick_encoder_args(
                self.encoder_combo.currentData() or "auto", self.log_msg
            )
            cmd = [
                which_ffmpeg(), "-hide_banner", "-y",
                "-f", "concat", "-safe", "0", "-i", list_path,
                *enc_args,
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-progress", "pipe:1", "-nostats",
                out_path,
            ]
            self.log_msg(f"Stitching {len(files)} clips (re-encode · {enc_name})…")

        self.btn_render.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.pbar.setValue(5)

        self._runner = FFmpegRunner(cmd, total_dur, self)
        self._runner.progressChanged.connect(self.pbar.setValue)
        self._runner.logLine.connect(self.log_msg)

        def _done(code: int):
            self._runner = None
            self.btn_render.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            if code == 0:
                self.pbar.setValue(100)
                self.log_msg("Done.")
                QtWidgets.QMessageBox.information(
                    self, "Stitch Up", f"Saved:\n{out_path}"
                )
            else:
                self.log_msg(
                    "Cancelled." if self.pbar.value() < 100 else "FFmpeg failed — check log."
                )

        self._runner.finished.connect(_done)
        self._runner.start()
