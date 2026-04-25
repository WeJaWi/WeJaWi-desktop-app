import os
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import List, Tuple

from PyQt5 import QtWidgets, QtCore


def _device_choices() -> List[Tuple[str, str]]:
    """Return (label, value) pairs for the device dropdown, tailored per OS."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return [
            ("Auto (prefer Metal/ANE)", "auto"),
            ("Metal / Neural Engine (M-series)", "mlx"),
            ("CPU only", "cpu"),
        ]
    if sys.platform == "darwin":
        return [("Auto", "auto"), ("CPU only", "cpu")]
    if os.name == "nt":
        return [
            ("Auto (prefer GPU)", "auto"),
            ("Force CUDA", "cuda"),
            ("DirectML (AMD/Intel)", "dml"),
            ("CPU only", "cpu"),
        ]
    return [
        ("Auto (prefer CUDA)", "auto"),
        ("Force CUDA", "cuda"),
        ("CPU only", "cpu"),
    ]

from .captions import (
    LANG_CHOICES,
    STT_MODEL_CHOICES,
    Segment,
    STTProcessRunner,
    get_video_duration,
    which_ffmpeg,
)


def _format_srt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_sec = total_ms // 1000
    s = total_sec % 60
    total_min = total_sec // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_sec = total_ms // 1000
    s = total_sec % 60
    total_min = total_sec // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _segments_to_srt(segments: List[Segment]) -> str:
    lines: List[str] = []
    for idx, seg in enumerate(segments, 1):
        lines.append(str(idx))
        lines.append(f"{_format_srt_time(seg.start)} --> {_format_srt_time(seg.end)}")
        lines.append(seg.text or "")
        lines.append("")
    return "\n".join(lines).strip()


def _segments_to_vtt(segments: List[Segment]) -> str:
    lines: List[str] = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_format_vtt_time(seg.start)} --> {_format_vtt_time(seg.end)}")
        lines.append(seg.text or "")
        lines.append("")
    return "\n".join(lines).strip()


def _segments_to_plain(segments: List[Segment]) -> str:
    return "\n".join(seg.text.strip() for seg in segments if seg.text).strip()


class TranscribePage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TranscribePage")

        self._runner: STTProcessRunner | None = None
        self._segments: List[Segment] = []
        self._tmp_dir: str | None = None
        self._tmp_audio: str | None = None

        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Transcribe")
        title.setObjectName("PageTitle")
        subtitle = QtWidgets.QLabel(
            "Generate transcripts from video or audio using Whisper (faster-whisper / openai-whisper)."
        )
        subtitle.setStyleSheet("color:#666666;")

        root.addWidget(title)
        root.addWidget(subtitle)

        file_row = QtWidgets.QHBoxLayout()
        file_row.setSpacing(8)
        file_row.addWidget(QtWidgets.QLabel("Media file:"))
        self.source_edit = QtWidgets.QLineEdit()
        self.source_edit.setPlaceholderText("Pick a video or audio file")
        file_row.addWidget(self.source_edit, 1)
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_source)
        file_row.addWidget(browse_btn)
        root.addLayout(file_row)

        options = QtWidgets.QGridLayout()
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(8)

        self.lang_combo = QtWidgets.QComboBox()
        for label, code in LANG_CHOICES:
            self.lang_combo.addItem(label, code)
        options.addWidget(QtWidgets.QLabel("Language:"), 0, 0)
        options.addWidget(self.lang_combo, 0, 1)

        self.model_combo = QtWidgets.QComboBox()
        for label, code in STT_MODEL_CHOICES:
            self.model_combo.addItem(label, code)
        options.addWidget(QtWidgets.QLabel("Model:"), 0, 2)
        options.addWidget(self.model_combo, 0, 3)

        self.device_combo = QtWidgets.QComboBox()
        for label, value in _device_choices():
            self.device_combo.addItem(label, value)
        options.addWidget(QtWidgets.QLabel("Device:"), 1, 0)
        options.addWidget(self.device_combo, 1, 1)

        self.duration_label = QtWidgets.QLabel("Duration: --:--")
        self.duration_label.setStyleSheet("color:#666666;")
        options.addWidget(self.duration_label, 1, 2, 1, 2)

        root.addLayout(options)

        self.preview_format = QtWidgets.QComboBox()
        self.preview_format.addItems(["SRT", "VTT", "Plain text"])
        self.preview_format.currentIndexChanged.connect(self._update_preview)

        format_row = QtWidgets.QHBoxLayout()
        format_row.addWidget(QtWidgets.QLabel("Preview as:"))
        format_row.addWidget(self.preview_format)
        format_row.addStretch(1)
        root.addLayout(format_row)

        self.pbar = QtWidgets.QProgressBar()
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        root.addWidget(self.pbar)

        self.preview_edit = QtWidgets.QPlainTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setPlaceholderText("Transcript will appear here after transcription runs.")

        self.log_edit = QtWidgets.QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(500)
        self.log_edit.setPlaceholderText("Logs")

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        splitter.addWidget(self.preview_edit)
        splitter.addWidget(self.log_edit)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_run = QtWidgets.QPushButton("Transcribe")
        self.btn_run.clicked.connect(self._handle_run)
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._handle_cancel)
        self.btn_save = QtWidgets.QPushButton("Save as...")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._handle_save)
        self.btn_copy = QtWidgets.QPushButton("Copy to clipboard")
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._handle_copy)
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_copy)
        root.addLayout(btn_row)

        note = QtWidgets.QLabel("Requires FFmpeg in PATH. Models are downloaded on first run.")
        note.setStyleSheet("color:#888888; font-size:11px;")
        root.addWidget(note)

    def _browse_source(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select media",
            "",
            "Media files (*.mp4 *.mov *.mkv *.mp3 *.wav *.m4a *.aac *.flac);;All files (*)",
        )
        if path:
            self.source_edit.setText(path)
            dur = get_video_duration(path)
            if dur:
                minutes = int(dur // 60)
                seconds = int(dur % 60)
                self.duration_label.setText(f"Duration: {minutes:02d}:{seconds:02d}")
            else:
                self.duration_label.setText("Duration: --:--")

    def _log(self, msg: str):
        if not msg:
            return
        self.log_edit.appendPlainText(msg)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_busy(self, busy: bool):
        if busy:
            self.pbar.setRange(0, 0)
        else:
            self.pbar.setRange(0, 100)
            self.pbar.setValue(0)

    def _cleanup_tmp(self):
        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        self._tmp_dir = None
        self._tmp_audio = None

    def _handle_run(self):
        if self._runner is not None:
            return
        path = self.source_edit.text().strip()
        if not path:
            QtWidgets.QMessageBox.warning(self, "Transcribe", "Pick a media file first.")
            return
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, "Transcribe", "File does not exist.")
            return
        ffm = which_ffmpeg()
        if not ffm:
            QtWidgets.QMessageBox.critical(self, "FFmpeg", "FFmpeg was not found in PATH.")
            return

        self.preview_edit.clear()
        self.log_edit.clear()
        self.btn_save.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self._segments = []

        try:
            tmp_dir = tempfile.mkdtemp(prefix="wejawi_transcribe_")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Temp directory", f"Failed to create temp directory:\n{e}")
            return

        tmp_wav = os.path.join(tmp_dir, "audio_16k.wav")
        cmd = [
            ffm,
            "-hide_banner",
            "-y",
            "-i",
            path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            tmp_wav,
        ]
        self._log("Extracting audio (mono 16 kHz)...")
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0 or not os.path.isfile(tmp_wav):
            if proc.stdout:
                self._log(proc.stdout.strip())
            if proc.stderr:
                self._log(proc.stderr.strip())
            shutil.rmtree(tmp_dir, ignore_errors=True)
            QtWidgets.QMessageBox.critical(self, "FFmpeg", "Failed to extract audio. See log for details.")
            return

        lang_code = self.lang_combo.currentData()
        model_code = self.model_combo.currentData()
        device_pref = self.device_combo.currentData()

        self._tmp_dir = tmp_dir
        self._tmp_audio = tmp_wav

        self._runner = STTProcessRunner(tmp_wav, lang_code, model_code, device_pref, self)
        self._runner.logLine.connect(self._log)
        self._runner.finished.connect(self._handle_finished)

        self._set_busy(True)
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self._log(f"Transcribing with model '{model_code}' ({device_pref}). This may take a while...")
        self._runner.start()

    def _handle_cancel(self):
        if self._runner:
            self._runner.cancel()
            self._log("Transcription cancelled.")
        self._set_busy(False)
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._cleanup_tmp()
        self._runner = None

    def _handle_finished(self, result):
        self._set_busy(False)
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._runner = None
        self._cleanup_tmp()

        if not result:
            self._log("No transcript produced.")
            QtWidgets.QMessageBox.information(self, "Transcribe", "No transcript was produced.")
            return

        self._segments = list(result)
        self.pbar.setValue(100)
        self._log(f"Transcription finished with {len(self._segments)} segment(s).")
        self.btn_save.setEnabled(True)
        self.btn_copy.setEnabled(True)
        self._update_preview()

    def _handle_save(self):
        if not self._segments:
            QtWidgets.QMessageBox.information(self, "Transcribe", "Run transcription first.")
            return
        filters = "SubRip Subtitle (*.srt);;WebVTT Subtitle (*.vtt);;Plain text (*.txt)"
        path, selected = QtWidgets.QFileDialog.getSaveFileName(self, "Save transcript", "", filters)
        if not path:
            return
        if selected.startswith("SubRip") or path.lower().endswith(".srt"):
            if not path.lower().endswith(".srt"):
                path += ".srt"
            data = _segments_to_srt(self._segments)
        elif selected.startswith("WebVTT") or path.lower().endswith(".vtt"):
            if not path.lower().endswith(".vtt"):
                path += ".vtt"
            data = _segments_to_vtt(self._segments)
        else:
            if not path.lower().endswith(".txt"):
                path += ".txt"
            data = _segments_to_plain(self._segments)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(data + "\n")
            self._log(f"Saved transcript to {path}")
            QtWidgets.QMessageBox.information(self, "Transcribe", f"Saved transcript:\n{path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save", f"Failed to save file:\n{e}")

    def _handle_copy(self):
        if not self._segments:
            return
        mode = self.preview_format.currentText()
        if mode == "SRT":
            data = _segments_to_srt(self._segments)
        elif mode == "VTT":
            data = _segments_to_vtt(self._segments)
        else:
            data = _segments_to_plain(self._segments)
        QtWidgets.QApplication.clipboard().setText(data)
        self._log("Transcript copied to clipboard.")

    def _update_preview(self):
        if not self._segments:
            self.preview_edit.clear()
            return
        mode = self.preview_format.currentText()
        if mode == "SRT":
            text = _segments_to_srt(self._segments)
        elif mode == "VTT":
            text = _segments_to_vtt(self._segments)
        else:
            text = _segments_to_plain(self._segments)
        self.preview_edit.setPlainText(text)
