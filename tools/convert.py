from PyQt5 import QtWidgets, QtCore, QtGui
import os
import threading

from core.conversion import (
    convert_video, convert_audio, convert_image,
    estimate_audio_size_seconds, estimate_video_size_seconds, rough_image_ratio,
    ffprobe_duration, VideoConvertOptions, AudioConvertOptions, ImageConvertOptions, find_ffmpeg
)

# ---------- Drag-and-drop file picker ----------
class DropZone(QtWidgets.QFrame):
    fileSelected = QtCore.pyqtSignal(str)

    def __init__(self, title="Drop file here or click to browse", filter_str="All files (*.*)", parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._filter = filter_str
        self._path: str = ""
        self.setObjectName("DropZone")
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(6)
        lab = QtWidgets.QLabel(title)
        lab.setAlignment(QtCore.Qt.AlignCenter)
        lab.setWordWrap(True)
        lab.setObjectName("DropZoneText")
        v.addStretch(1)
        v.addWidget(lab)
        v.addStretch(1)

    def mousePressEvent(self, _e):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose file", "", self._filter)
        if path:
            self._path = path
            self.fileSelected.emit(path)
            self.update()

    def dragEnterEvent(self, e: QtGui.QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QtGui.QDropEvent):
        urls = e.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if os.path.isfile(path):
            self._path = path
            self.fileSelected.emit(path)
            self.update()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if not self._path:
            return
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QPen(QtGui.QColor("#bbb")))
        p.setFont(QtGui.QFont("", 10))
        txt = os.path.basename(self._path)
        p.drawText(self.rect().adjusted(8, 8, -8, -8), QtCore.Qt.AlignBottom | QtCore.Qt.AlignLeft, txt)
        p.end()

    @property
    def path(self) -> str:
        return self._path


# ---------- MP4 → MP3 ----------
class Mp4ToMp3Card(QtWidgets.QGroupBox):
    convertRequested = QtCore.pyqtSignal(dict)  # {in, out, bitrate}

    def __init__(self, parent=None):
        super().__init__("MP4 → MP3", parent)
        self.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(self)
        v.setSpacing(8)

        self.drop = DropZone(filter_str="Video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;All files (*.*)")
        self.drop.fileSelected.connect(self._update_estimate)
        v.addWidget(self.drop, 1)

        form = QtWidgets.QFormLayout()
        self.bitrate = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.bitrate.setRange(32, 320)
        self.bitrate.setValue(192)
        self.bitrate.valueChanged.connect(self._update_estimate)
        form.addRow("Target bitrate (kbps)", self.bitrate)
        v.addLayout(form)

        self.est = QtWidgets.QLabel("ESTIMATED MP3 SIZE —")
        self.est.setObjectName("EstimateBox")
        v.addWidget(self.est)
        self.delta = QtWidgets.QLabel("≈ — vs. original")
        v.addWidget(self.delta)

        self.btn = QtWidgets.QPushButton("Convert")
        self.btn.clicked.connect(self._on_convert)
        v.addWidget(self.btn)

        self._duration = 0.0
        self._orig_size = 0

    def _fmt_mb(self, b): return f"{b/1048576.0:.2f} MB"

    def _update_estimate(self):
        p = self.drop.path
        if not p or not os.path.exists(p):
            self.est.setText("ESTIMATED MP3 SIZE —")
            self.delta.setText("≈ — vs. original")
            return
        self._duration = float(ffprobe_duration(p) or 0.0)
        self._orig_size = os.path.getsize(p)
        est_b = estimate_audio_size_seconds(self._duration, "mp3", self.bitrate.value())
        self.est.setText(f"ESTIMATED MP3 SIZE\n{self._fmt_mb(est_b)}")
        if self._orig_size > 0:
            d = est_b - self._orig_size
            pct = (d / self._orig_size) * 100.0
            sign = "-" if pct < 0 else "+"
            self.delta.setText(f"≈ {self._fmt_mb(abs(d))} ({sign}{abs(pct):.1f}%) vs. original")

    def _on_convert(self):
        if not self.drop.path:
            QtWidgets.QMessageBox.warning(self, "MP4 → MP3", "Choose a video file first.")
            return
        base, _ = os.path.splitext(self.drop.path)
        default = os.path.join(os.path.dirname(self.drop.path), os.path.basename(base) + ".mp3")
        out, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save MP3", default, "MP3 (*.mp3)")
        if not out:
            return
        self.convertRequested.emit({"in": self.drop.path, "out": out, "bitrate": self.bitrate.value()})


# ---------- Video → Video ----------
class VideoCard(QtWidgets.QGroupBox):
    convertRequested = QtCore.pyqtSignal(dict)  # {in,out,fmt,v,a}

    def __init__(self, parent=None):
        super().__init__("Video Converter", parent)
        self.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(self)
        v.setSpacing(8)

        self.drop = DropZone(filter_str="Video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;All files (*.*)")
        self.drop.fileSelected.connect(self._update_estimate)
        v.addWidget(self.drop, 1)

        form = QtWidgets.QFormLayout()
        self.vbit = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.vbit.setRange(100, 20000); self.vbit.setValue(3000)
        self.abit = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.abit.setRange(32, 512); self.abit.setValue(128)
        self.format = QtWidgets.QComboBox(); self.format.addItems(["mp4", "mkv", "mov", "webm"])
        self.vbit.valueChanged.connect(self._update_estimate)
        self.abit.valueChanged.connect(self._update_estimate)
        self.format.currentIndexChanged.connect(self._update_estimate)
        form.addRow("Video bitrate (kbps)", self.vbit)
        form.addRow("Audio bitrate (kbps)", self.abit)
        form.addRow("Preset / Format", self.format)
        v.addLayout(form)

        self.est = QtWidgets.QLabel("ESTIMATED VIDEO SIZE —")
        self.est.setObjectName("EstimateBox")
        v.addWidget(self.est)
        self.delta = QtWidgets.QLabel("≈ — vs. original")
        v.addWidget(self.delta)

        self.btn = QtWidgets.QPushButton("Convert")
        self.btn.clicked.connect(self._on_convert)
        v.addWidget(self.btn)

        self._duration = 0.0
        self._orig_size = 0

    def _fmt_mb(self, b): return f"{b/1048576.0:.2f} MB"

    def _update_estimate(self):
        p = self.drop.path
        if not p or not os.path.exists(p):
            self.est.setText("ESTIMATED VIDEO SIZE —")
            self.delta.setText("≈ — vs. original")
            return
        self._duration = float(ffprobe_duration(p) or 0.0)
        self._orig_size = os.path.getsize(p)
        est_b = estimate_video_size_seconds(self._duration, self.vbit.value(), self.abit.value())
        self.est.setText(f"ESTIMATED VIDEO SIZE\n{self._fmt_mb(est_b)}")
        if self._orig_size > 0:
            d = est_b - self._orig_size
            pct = (d / self._orig_size) * 100.0
            sign = "-" if pct < 0 else "+"
            self.delta.setText(f"≈ {self._fmt_mb(abs(d))} ({sign}{abs(pct):.1f}%) vs. original")

    def _on_convert(self):
        if not self.drop.path:
            QtWidgets.QMessageBox.warning(self, "Video Converter", "Choose a video file first.")
            return
        base, _ = os.path.splitext(self.drop.path)
        default = os.path.join(os.path.dirname(self.drop.path), os.path.basename(base) + f".{self.format.currentText()}")
        out, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save video", default, f"{self.format.currentText().upper()} (*.{self.format.currentText()})")
        if not out:
            return
        self.convertRequested.emit({
            "in": self.drop.path, "out": out,
            "fmt": self.format.currentText(),
            "v": self.vbit.value(), "a": self.abit.value()
        })


# ---------- Audio → Audio ----------
class AudioCard(QtWidgets.QGroupBox):
    convertRequested = QtCore.pyqtSignal(dict)  # {in,out,fmt,bitrate}

    def __init__(self, parent=None):
        super().__init__("Audio Converter", parent)
        self.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(self)
        v.setSpacing(8)

        self.drop = DropZone(filter_str="Audio (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus);;All files (*.*)")
        self.drop.fileSelected.connect(self._update_estimate)
        v.addWidget(self.drop, 1)

        form = QtWidgets.QFormLayout()
        self.format = QtWidgets.QComboBox(); self.format.addItems(["mp3", "aac", "m4a", "wav", "flac", "ogg", "opus"])
        self.bitrate = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.bitrate.setRange(8, 512); self.bitrate.setValue(192)
        self.format.currentIndexChanged.connect(self._update_estimate)
        self.bitrate.valueChanged.connect(self._update_estimate)
        form.addRow("Target format", self.format)
        form.addRow("Target bitrate (kbps)", self.bitrate)
        v.addLayout(form)

        self.est = QtWidgets.QLabel("ESTIMATED AUDIO SIZE —")
        self.est.setObjectName("EstimateBox")
        v.addWidget(self.est)
        self.delta = QtWidgets.QLabel("≈ — vs. original")
        v.addWidget(self.delta)

        self.btn = QtWidgets.QPushButton("Convert")
        self.btn.clicked.connect(self._on_convert)
        v.addWidget(self.btn)

        self._duration = 0.0
        self._orig_size = 0

    def _fmt_mb(self, b): return f"{b/1048576.0:.2f} MB"

    def _update_estimate(self):
        p = self.drop.path
        if not p or not os.path.exists(p):
            self.est.setText("ESTIMATED AUDIO SIZE —")
            self.delta.setText("≈ — vs. original")
            return
        self._duration = float(ffprobe_duration(p) or 0.0)
        self._orig_size = os.path.getsize(p)
        est_b = estimate_audio_size_seconds(self._duration, self.format.currentText(), self.bitrate.value())
        self.est.setText(f"ESTIMATED AUDIO SIZE\n{self._fmt_mb(est_b)}")
        if self._orig_size > 0:
            d = est_b - self._orig_size
            pct = (d / self._orig_size) * 100.0
            sign = "-" if pct < 0 else "+"
            self.delta.setText(f"≈ {self._fmt_mb(abs(d))} ({sign}{abs(pct):.1f}%) vs. original")

    def _on_convert(self):
        if not self.drop.path:
            QtWidgets.QMessageBox.warning(self, "Audio Converter", "Choose an audio file first.")
            return
        base, _ = os.path.splitext(self.drop.path)
        default = os.path.join(os.path.dirname(self.drop.path), os.path.basename(base) + f".{self.format.currentText()}")
        out, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save audio", default, f"{self.format.currentText().upper()} (*.{self.format.currentText()})")
        if not out:
            return
        self.convertRequested.emit({
            "in": self.drop.path, "out": out,
            "fmt": self.format.currentText(), "bitrate": self.bitrate.value()
        })


# ---------- Image → Image ----------
class ImageCard(QtWidgets.QGroupBox):
    convertRequested = QtCore.pyqtSignal(dict)  # {in,out,fmt_to,quality}

    def __init__(self, parent=None):
        super().__init__("Image Converter", parent)
        self.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(self)
        v.setSpacing(8)

        self.drop = DropZone(filter_str="Images (*.jpg *.jpeg *.png *.bmp *.webp *.tiff);;All files (*.*)")
        self.drop.fileSelected.connect(self._update_estimate)
        v.addWidget(self.drop, 1)

        form = QtWidgets.QFormLayout()
        self.from_combo = QtWidgets.QComboBox(); self.from_combo.addItems(["png","jpg","webp","bmp","tiff"])
        self.to_combo = QtWidgets.QComboBox(); self.to_combo.addItems(["png","jpg","webp","bmp","tiff"])
        self.quality = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.quality.setRange(1, 95); self.quality.setValue(85)
        self.from_combo.currentIndexChanged.connect(self._update_estimate)
        self.to_combo.currentIndexChanged.connect(self._update_estimate)
        self.quality.valueChanged.connect(self._update_estimate)
        form.addRow("From", self.from_combo)
        form.addRow("To", self.to_combo)
        form.addRow("Quality (JPEG/WebP)", self.quality)
        v.addLayout(form)

        self.est = QtWidgets.QLabel("ESTIMATED IMAGE SIZE —")
        self.est.setObjectName("EstimateBox")
        v.addWidget(self.est)
        self.delta = QtWidgets.QLabel("≈ — vs. original")
        v.addWidget(self.delta)

        self.btn = QtWidgets.QPushButton("Convert")
        self.btn.clicked.connect(self._on_convert)
        v.addWidget(self.btn)

        self._orig_size = 0

    def _fmt_mb(self, b): return f"{b/1048576.0:.2f} MB"

    def _update_estimate(self):
        p = self.drop.path
        if p:
            self._orig_size = os.path.getsize(p) if os.path.exists(p) else 0
            ext = os.path.splitext(p)[1].lower().lstrip(".")
            idx = self.from_combo.findText(ext)
            if idx >= 0:
                self.from_combo.setCurrentIndex(idx)
        if not p or self._orig_size <= 0:
            self.est.setText("ESTIMATED IMAGE SIZE —")
            self.delta.setText("≈ — vs. original")
            return
        ratio = rough_image_ratio(self.from_combo.currentText(), self.to_combo.currentText())
        est_b = int(max(1024, self._orig_size * ratio))
        self.est.setText(f"ESTIMATED IMAGE SIZE\n{self._fmt_mb(est_b)}")
        if self._orig_size > 0:
            d = est_b - self._orig_size
            pct = (d / self._orig_size) * 100.0
            sign = "-" if pct < 0 else "+"
            self.delta.setText(f"≈ {self._fmt_mb(abs(d))} ({sign}{abs(pct):.1f}%) vs. original")

    def _on_convert(self):
        if not self.drop.path:
            QtWidgets.QMessageBox.warning(self, "Image Converter", "Choose an image file first.")
            return
        base, _ = os.path.splitext(self.drop.path)
        ext = self.to_combo.currentText()
        default = os.path.join(os.path.dirname(self.drop.path), os.path.basename(base) + f".{ext}")
        out, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save image", default, f"{ext.upper()} (*.{ext})")
        if not out:
            return
        self.convertRequested.emit({
            "in": self.drop.path, "out": out,
            "fmt_to": ext, "quality": self.quality.value()
        })


# ---------- Page ----------
class ConvertPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ConvertPage")
        self._threads = []
        self._build_ui()

        if not find_ffmpeg():
            QtWidgets.QMessageBox.information(self, "FFmpeg", "FFmpeg not found on PATH. Video/Audio conversion requires it.")

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Convert")
        title.setObjectName("PageTitleDark")
        root.addWidget(title)

        # Estimator at the top
        root.addWidget(self._build_estimator_card())

        # 4 cards in a grid (one row, four columns)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)

        self.card_mp3 = Mp4ToMp3Card()
        self.card_video = VideoCard()
        self.card_audio = AudioCard()
        self.card_image = ImageCard()

        grid.addWidget(self.card_mp3,   0, 0)
        grid.addWidget(self.card_video, 0, 1)
        grid.addWidget(self.card_audio, 0, 2)
        grid.addWidget(self.card_image, 0, 3)

        self.card_mp3.convertRequested.connect(self._run_mp3)
        self.card_video.convertRequested.connect(self._run_video)
        self.card_audio.convertRequested.connect(self._run_audio)
        self.card_image.convertRequested.connect(self._run_image)

        wrap = QtWidgets.QWidget()
        wrap.setLayout(grid)
        root.addWidget(wrap)

        # Optional log (hidden until needed)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setVisible(False)

    # ---- Estimator card (same layout as ref) ----
    def _build_estimator_card(self):
        card = QtWidgets.QGroupBox("Size Difference Estimator")
        card.setObjectName("EstimatorCard")
        v = QtWidgets.QVBoxLayout(card)
        v.setSpacing(8)

        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Original size (MB)"), 0, 0)
        self.est_size = QtWidgets.QLineEdit(); self.est_size.setPlaceholderText("e.g., 100"); grid.addWidget(self.est_size, 1, 0)
        grid.addWidget(QtWidgets.QLabel("Duration (mm:ss or minutes)"), 0, 1)
        self.est_dur = QtWidgets.QLineEdit(); self.est_dur.setPlaceholderText("e.g., 5:00 or 5"); grid.addWidget(self.est_dur, 1, 1)
        tip = QtWidgets.QLabel("Tip: Video size ≈ (video kbps + audio kbps) × duration."); tip.setStyleSheet("color:#888;")
        grid.addWidget(tip, 2, 0, 1, 2)
        v.addLayout(grid)

        self.est_tabs = QtWidgets.QTabWidget()
        self.est_tabs.addTab(self._build_tab_mp4mp3(), "MP4→MP3")
        self.est_tabs.addTab(self._build_tab_video(), "Video")
        self.est_tabs.addTab(self._build_tab_audio(), "Audio")
        self.est_tabs.addTab(self._build_tab_image(), "Image")
        self.est_tabs.currentChanged.connect(self._update_estimator)
        v.addWidget(self.est_tabs)

        rules = QtWidgets.QGroupBox("Rules of thumb")
        rlay = QtWidgets.QVBoxLayout(rules)
        lab = QtWidgets.QLabel("• Audio size ≈ bitrate × duration (128 kbps ≈ ~1 MB/min)\n"
                               "• Video size ≈ (video + audio) kbps × duration\n"
                               "• Image: JPG for photos; PNG for graphics/text; WebP often smaller at similar quality.")
        lab.setWordWrap(True)
        rlay.addWidget(lab)
        v.addWidget(rules)

        self.est_size.textChanged.connect(self._update_estimator)
        self.est_dur.textChanged.connect(self._update_estimator)

        return card

    def _build_tab_mp4mp3(self):
        w = QtWidgets.QWidget(); f = QtWidgets.QFormLayout(w)
        self.est_mp3_bitrate = QtWidgets.QSpinBox(); self.est_mp3_bitrate.setRange(32,320); self.est_mp3_bitrate.setValue(192)
        self.est_out_mp4mp3 = QtWidgets.QLineEdit(); self.est_out_mp4mp3.setReadOnly(True)
        f.addRow("MP3 bitrate (kbps):", self.est_mp3_bitrate)
        f.addRow("Est. output:", self.est_out_mp4mp3)
        self.est_mp3_bitrate.valueChanged.connect(self._update_estimator)
        return w

    def _build_tab_video(self):
        w = QtWidgets.QWidget(); f = QtWidgets.QFormLayout(w)
        self.est_v_vbitrate = QtWidgets.QSpinBox(); self.est_v_vbitrate.setRange(100, 20000); self.est_v_vbitrate.setValue(3000)
        self.est_v_abitrate = QtWidgets.QSpinBox(); self.est_v_abitrate.setRange(32, 512); self.est_v_abitrate.setValue(128)
        self.est_out_video = QtWidgets.QLineEdit(); self.est_out_video.setReadOnly(True)
        f.addRow("Video bitrate (kbps):", self.est_v_vbitrate)
        f.addRow("Audio bitrate (kbps):", self.est_v_abitrate)
        f.addRow("Est. output:", self.est_out_video)
        self.est_v_vbitrate.valueChanged.connect(self._update_estimator)
        self.est_v_abitrate.valueChanged.connect(self._update_estimator)
        return w

    def _build_tab_audio(self):
        w = QtWidgets.QWidget(); f = QtWidgets.QFormLayout(w)
        self.est_a_target = QtWidgets.QComboBox(); self.est_a_target.addItems(["mp3","aac","m4a","wav","flac","ogg","opus"])
        self.est_a_bitrate = QtWidgets.QSpinBox(); self.est_a_bitrate.setRange(8,512); self.est_a_bitrate.setValue(192)
        self.est_out_audio = QtWidgets.QLineEdit(); self.est_out_audio.setReadOnly(True)
        f.addRow("Target format:", self.est_a_target)
        f.addRow("Bitrate (kbps):", self.est_a_bitrate)
        f.addRow("Est. output:", self.est_out_audio)
        self.est_a_target.currentIndexChanged.connect(self._update_estimator)
        self.est_a_bitrate.valueChanged.connect(self._update_estimator)
        return w

    def _build_tab_image(self):
        w = QtWidgets.QWidget(); f = QtWidgets.QFormLayout(w)
        self.est_i_from = QtWidgets.QComboBox(); self.est_i_from.addItems(["png","jpg","webp","bmp","tiff"])
        self.est_i_to = QtWidgets.QComboBox(); self.est_i_to.addItems(["png","jpg","webp","bmp","tiff"])
        self.est_out_image = QtWidgets.QLineEdit(); self.est_out_image.setReadOnly(True)
        f.addRow("From:", self.est_i_from)
        f.addRow("To:", self.est_i_to)
        f.addRow("Est. output:", self.est_out_image)
        self.est_i_from.currentIndexChanged.connect(self._update_estimator)
        self.est_i_to.currentIndexChanged.connect(self._update_estimator)
        return w

    def _get_float(self, s: str):
        s = (s or "").strip().lower().replace(",", ".")
        if not s: return None
        try: return float(s)
        except Exception: return None

    def _parse_duration(self, s: str):
        s = (s or "").strip()
        if not s: return None
        try:
            if ":" in s:
                parts = s.split(":")
                if len(parts) == 2:  return max(0.0, float(parts[0])*60 + float(parts[1]))
                if len(parts) == 3:  return max(0.0, float(parts[0])*3600 + float(parts[1])*60 + float(parts[2]))
            else:
                return max(0.0, float(s) * 60.0)
        except Exception:
            return None

    def _set_est_output(self, line: QtWidgets.QLineEdit, out_mb, orig_mb):
        if out_mb is None: line.setText("n/a"); return
        if orig_mb is not None and orig_mb > 0:
            change = (out_mb - orig_mb) / orig_mb * 100.0
            sign = "-" if change < 0 else "+"
            line.setText(f"{out_mb:.2f} MB ({sign}{abs(change):.1f}%)")
        else:
            line.setText(f"{out_mb:.2f} MB")

    def _update_estimator(self):
        orig_mb = self._get_float(self.est_size.text())
        dur_s = self._parse_duration(self.est_dur.text())
        tab = self.est_tabs.currentIndex()

        if tab == 0 and dur_s is not None:
            size_b = estimate_audio_size_seconds(dur_s, "mp3", self.est_mp3_bitrate.value())
            self._set_est_output(self.est_out_mp4mp3, size_b/(1024*1024), orig_mb)
        elif tab == 1 and dur_s is not None:
            size_b = estimate_video_size_seconds(dur_s, self.est_v_vbitrate.value(), self.est_v_abitrate.value())
            self._set_est_output(self.est_out_video, size_b/(1024*1024), orig_mb)
        elif tab == 2 and dur_s is not None:
            size_b = estimate_audio_size_seconds(dur_s, self.est_a_target.currentText(), self.est_a_bitrate.value())
            self._set_est_output(self.est_out_audio, size_b/(1024*1024), orig_mb)
        elif tab == 3 and orig_mb is not None:
            ratio = rough_image_ratio(self.est_i_from.currentText(), self.est_i_to.currentText())
            self._set_est_output(self.est_out_image, max(0.01, orig_mb * ratio), orig_mb)

    # ---- run conversions (threaded) ----
    def _run_mp3(self, payload: dict):
        self._log(f"MP4 → MP3: {os.path.basename(payload['in'])} → {payload['out']}")
        def work():
            opts = AudioConvertOptions(target_ext="mp3", bitrate_kbps=int(payload["bitrate"]))
            ok, msg = convert_audio(payload["in"], os.path.splitext(payload["out"])[0], opts)
            self._log(("✔ " if ok else "✖ ") + msg)
            QtWidgets.QMessageBox.information(self, "MP4 → MP3", msg if ok else f"Failed: {msg}")
        t = threading.Thread(target=work, daemon=True); t.start(); self._threads.append(t)

    def _run_video(self, payload: dict):
        self._log(f"Video: {os.path.basename(payload['in'])} → {payload['out']}")
        def work():
            opts = VideoConvertOptions(target_ext=payload["fmt"], v_bitrate_kbps=int(payload["v"]), a_bitrate_kbps=int(payload["a"]))
            ok, msg = convert_video(payload["in"], os.path.splitext(payload["out"])[0], opts)
            self._log(("✔ " if ok else "✖ ") + msg)
            QtWidgets.QMessageBox.information(self, "Video Convert", msg if ok else f"Failed: {msg}")
        t = threading.Thread(target=work, daemon=True); t.start(); self._threads.append(t)

    def _run_audio(self, payload: dict):
        self._log(f"Audio: {os.path.basename(payload['in'])} → {payload['out']}")
        def work():
            opts = AudioConvertOptions(target_ext=payload["fmt"], bitrate_kbps=int(payload["bitrate"]))
            ok, msg = convert_audio(payload["in"], os.path.splitext(payload["out"])[0], opts)
            self._log(("✔ " if ok else "✖ ") + msg)
            QtWidgets.QMessageBox.information(self, "Audio Convert", msg if ok else f"Failed: {msg}")
        t = threading.Thread(target=work, daemon=True); t.start(); self._threads.append(t)

    def _run_image(self, payload: dict):
        self._log(f"Image: {os.path.basename(payload['in'])} → {payload['out']}")
        def work():
            opts = ImageConvertOptions(target_ext=payload["fmt_to"], jpeg_quality=int(payload["quality"]))
            ok, msg = convert_image(payload["in"], os.path.splitext(payload["out"])[0], opts)
            self._log(("✔ " if ok else "✖ ") + msg)
            QtWidgets.QMessageBox.information(self, "Image Convert", msg if ok else f"Failed: {msg}")
        t = threading.Thread(target=work, daemon=True); t.start(); self._threads.append(t)

    def _log(self, s: str):
        if not self.log.isVisible():
            self.log.setVisible(True)
            self.layout().addWidget(self.log)
        self.log.appendPlainText(s)
