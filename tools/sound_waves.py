# tools/sound_waves.py

# Sound Waves tool with live preview (drag/resize), presets, background render + JSON logs.

# PyQt5 + FFmpeg only.

from __future__ import annotations

import os, shutil, subprocess, tempfile

from typing import Optional, Tuple

from PyQt5 import QtWidgets, QtCore, QtGui

from core.jobs import JobManager

from core.logging_utils import get_logger

from tools.wave_preview import WavePreviewWidget

logger = get_logger(__name__)

_SMOOTHING_PRESETS = [0.0, 0.5, 1.0, 2.0, 3.5, 5.0, 8.0]
_SMOOTHING_LABELS = [
    "Raw detail",
    "0.5x (sharper)",
    "Default",
    "2x smoother",
    "3.5x smoother",
    "5x smoother",
    "8x smoother",
]

def _ff_escape_commas(s: str) -> str:

    """Inside -filter_complex expressions (geq/lut), commas/colons must be escaped."""
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(":", "\\:")
def _rounded_bar_mask_expr(period: int, bar_px: int, height: int, round_px: int) -> str:
    period = max(1, int(period))
    bar_px = max(1, int(bar_px))
    height = max(1, int(height))
    r = float(max(0, round_px))
    r = max(0.0, min(r, bar_px / 2.0, height / 2.0))
    if r <= 0.0:
        return f"if(lt(mod(X,{period}),{bar_px}),255,0)"

    center_x = (bar_px - 1) / 2.0
    center_y = (height - 1) / 2.0
    wx = max(0.0, (bar_px / 2.0) - r)
    wy = max(0.0, (height / 2.0) - r)

    x_rel = f"mod(X,{period})"
    dx = f"abs({x_rel}-{center_x:.4f})"
    dy = f"abs(Y-{center_y:.4f})"
    mx = f"max({dx}-{wx:.4f},0)"
    my = f"max({dy}-{wy:.4f},0)"
    inside = (
        f"if(lte({dx},{wx:.4f}),255,"
        f"if(lte({dy},{wy:.4f}),255,"
        f"if(lte(pow({mx},2)+pow({my},2),{r*r:.4f}),255,0)))"
    )
    return f"if(lt({x_rel},{bar_px}),{inside},0)"

def _ffmpeg_color_arg(color: str) -> str:
    """FFmpeg filters do not accept leading # (treated as comment). Force 0xRRGGBB."""
    if not color:
        return '0xffffff'
    c = color.strip()
    if c.startswith('#') and len(c) == 7:
        return '0x' + c[1:]
    if c.lower().startswith('0x') and len(c) == 8:
        return '0x' + c[2:]
    return c


# ---------------------- FFmpeg helpers ----------------------

def which_ffmpeg() -> Optional[str]:

    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return shutil.which(exe)
def which_ffprobe() -> Optional[str]:

    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    return shutil.which(exe)
def _run(cmd):

    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
def ffprobe_size(path: str) -> Optional[Tuple[int,int]]:

    fp = which_ffprobe()
    if not fp: return None
    r = _run([fp, "-v", "error", "-select_streams", "v:0",
              "-show_entries", "stream=width,height",
              "-of", "csv=p=0:s=x", path])
    if r.returncode != 0: return None
    out = r.stdout.strip()
    if "x" in out:
        try:
            w, h = out.split("x")
            return int(w), int(h)
        except Exception:
            return None
    return None
def ffprobe_duration(path: str) -> Optional[float]:

    fp = which_ffprobe()
    if not fp: return None
    r = _run([fp, "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", path])
    if r.returncode != 0: return None
    try: return float(r.stdout.strip())
    except Exception: return None
def ffprobe_fps(path: str) -> Optional[float]:

    fp = which_ffprobe()
    if not fp: return None
    r = _run([fp, "-v", "error", "-select_streams", "v:0",
              "-show_entries", "stream=avg_frame_rate",
              "-of", "default=noprint_wrappers=1:nokey=1", path])
    if r.returncode != 0: return None
    val = r.stdout.strip()
    if not val: return None
    try:
        if "/" in val:
            num, den = val.split("/", 1)
            num_f = float(num)
            den_f = float(den)
            if den_f == 0: return None
            return num_f / den_f
        return float(val)
    except Exception:
        return None
def ffprobe_channels(path: str) -> Optional[int]:

    fp = which_ffprobe()
    if not fp: return None
    r = _run([fp, "-v", "error", "-select_streams", "a:0",
              "-show_entries", "stream=channels",
              "-of", "default=noprint_wrappers=1:nokey=1", path])
    if r.returncode != 0: return None
    try: return int(r.stdout.strip())
    except Exception: return None

# ---- Encoder selection ----

_FFMPEG_ENCODERS_CACHE = None

def _ffmpeg_list_encoders() -> str:

    global _FFMPEG_ENCODERS_CACHE
    if _FFMPEG_ENCODERS_CACHE is not None: return _FFMPEG_ENCODERS_CACHE
    ffm = which_ffmpeg()
    if not ffm: return ""
    r = _run([ffm, "-hide_banner", "-encoders"])
    _FFMPEG_ENCODERS_CACHE = r.stdout if r.returncode == 0 else ""
    return _FFMPEG_ENCODERS_CACHE or ""
def _has_encoder(name: str) -> bool:

    enc = _ffmpeg_list_encoders()
    return f" {name} " in enc or enc.strip().endswith(name)
def _pick_encoder_args(pref: str, log_cb):

    if pref == "nvenc":
        if _has_encoder("h264_nvenc"):
            return (["-c:v", "h264_nvenc", "-preset", "p5"], "NVIDIA NVENC (h264_nvenc)")
        log_cb("NVENC not available; falling back to CPU.")
        return (["-c:v", "libx264", "-preset", "medium"], "CPU x264")
    if pref == "amf":
        if _has_encoder("h264_amf"):
            return (["-c:v", "h264_amf"], "AMD AMF (h264_amf)")
        log_cb("AMF not available; falling back to CPU.")
        return (["-c:v", "libx264", "-preset", "medium"], "CPU x264")
    if pref == "cpu":
        return (["-c:v", "libx264", "-preset", "medium"], "CPU x264")
    if _has_encoder("h264_nvenc"):
        return (["-c:v", "h264_nvenc", "-preset", "p5"], "NVIDIA NVENC (h264_nvenc)")
    if _has_encoder("h264_amf"):
        return (["-c:v", "h264_amf"], "AMD AMF (h264_amf)")
    return (["-c:v", "libx264", "-preset", "medium"], "CPU x264")
# Note: Using -filter_complex directly instead of deprecated -filter_complex_script

# ---------------------- Page UI ----------------------

class SoundWavesPage(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SoundWavesPage")
        self._video_size = (1280, 720)
        self._duration = 1.0
        self._fps = 30.0
        self._audio_channels = None
        logger.info("Initialising SoundWavesPage")
        self._build_ui()
    # ---- UI helpers ----
    def _apply_color_btn_style(self, btn: QtWidgets.QPushButton):
        hexcol = btn.property("color") or "#00FFCC"
        q = QtGui.QColor(hexcol)
        txtcol = "#000000" if q.lightness() > 128 else "#FFFFFF"
        btn.setStyleSheet(
            f"border:1px solid #dfe1ee; border-radius:8px; padding:8px; background:{hexcol}; color:{txtcol};"
        )
    def _smoothing_multiplier(self, index: int) -> float:
        if 0 <= index < len(_SMOOTHING_PRESETS):
            return _SMOOTHING_PRESETS[index]
        return _SMOOTHING_PRESETS[2]
    def _update_smoothing_label(self, index: int):
        if hasattr(self, 'smoothing_label'):
            if 0 <= index < len(_SMOOTHING_LABELS):
                self.smoothing_label.setText(_SMOOTHING_LABELS[index])
            else:
                self.smoothing_label.setText(_SMOOTHING_LABELS[2])
    def _on_smoothing_changed(self, value: int):
        self._update_smoothing_label(value)
        self._apply_preview_style()
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        title = QtWidgets.QLabel("📈 Sound Waves")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        # File pickers
        fp_row = QtWidgets.QHBoxLayout()
        self.in_edit = QtWidgets.QLineEdit()
        b_in = QtWidgets.QPushButton("Browse video…"); b_in.clicked.connect(self._pick_input)
        self.out_edit = QtWidgets.QLineEdit("output_waves.mp4")
        b_out = QtWidgets.QPushButton("Save as…"); b_out.clicked.connect(self._pick_output)
        fp_row.addWidget(QtWidgets.QLabel("Input:")); fp_row.addWidget(self.in_edit, 1); fp_row.addWidget(b_in)
        fp_row.addSpacing(12)
        fp_row.addWidget(QtWidgets.QLabel("Output:")); fp_row.addWidget(self.out_edit, 1); fp_row.addWidget(b_out)
        root.addLayout(fp_row)
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Horizontal)
        root.addWidget(splitter, 1)
        # Left: style + numeric controls
        left = QtWidgets.QWidget(); lform = QtWidgets.QFormLayout(left)
        self.style = QtWidgets.QComboBox()
        self.style.addItem("Sticks (classic)", "sticks")       # showwaves:p2p
        self.style.addItem("Sticks (rounded)", "rounded")      # showwaves:p2p + rounded preview
        self.style.addItem("Line (smooth)", "line")            # showwaves:line
        self.style.addItem("Spectrum bars", "spectrum")        # showfreqs:bar
        self.style.currentIndexChanged.connect(self._style_changed)
        lform.addRow("Style preset:", self.style)
        self.barw = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.barw.setRange(2, 40); self.barw.setValue(8)
        lform.addRow("Bar width (px):", self.barw)
        self.gapw = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.gapw.setRange(0, 20); self.gapw.setValue(2)
        lform.addRow("Gap (px):", self.gapw)
        self.roundw = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.roundw.setRange(0, 20); self.roundw.setValue(4)
        lform.addRow("Roundness:", self.roundw)
        col_row = QtWidgets.QHBoxLayout()
        self.color_btn = QtWidgets.QPushButton("Pick color"); self.color_btn.setProperty("color", "#00FFCC")
        self._apply_color_btn_style(self.color_btn); self.color_btn.clicked.connect(self._pick_color)
        col_row.addWidget(self.color_btn)
        self.opacity = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.opacity.setRange(10, 100); self.opacity.setValue(85)
        col_row.addWidget(QtWidgets.QLabel("Opacity")); col_row.addWidget(self.opacity, 1)
        col_wrap = QtWidgets.QWidget(); col_wrap.setLayout(col_row)
        lform.addRow("Color:", col_wrap)
        self.bg_opacity = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.bg_opacity.setRange(0, 90); self.bg_opacity.setValue(25)
        lform.addRow("Background bar opacity:", self.bg_opacity)
        self.scale_mode = QtWidgets.QComboBox()
        self.scale_mode.addItem("Linear (original amplitude)", "lin")
        self.scale_mode.addItem("Square root (balanced)", "sqrt")
        self.scale_mode.addItem("Cubic root (lift quiet parts)", "cbrt")
        self.scale_mode.addItem("Logarithmic (lift quietest)", "log")
        lform.addRow("Amplitude scale:", self.scale_mode)
        smooth_row = QtWidgets.QHBoxLayout()
        self.smoothing = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.smoothing.setRange(0, len(_SMOOTHING_PRESETS)-1); self.smoothing.setValue(2); self.smoothing.setSingleStep(1); self.smoothing.setPageStep(1)
        smooth_row.addWidget(self.smoothing)
        self.smoothing_label = QtWidgets.QLabel()
        self.smoothing_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.smoothing_label.setMinimumWidth(120)
        smooth_row.addWidget(self.smoothing_label)
        smooth_wrap = QtWidgets.QWidget(); smooth_wrap.setLayout(smooth_row)
        lform.addRow("Smoothing:", smooth_wrap)
        self.split_channels = QtWidgets.QCheckBox("Split stereo channels")
        self.split_channels.setChecked(False)
        self.split_channels.setEnabled(False)
        self.split_channels.setToolTip("Show left/right channels in separate bands when the audio is stereo.")
        lform.addRow("", self.split_channels)
        xy_grid = QtWidgets.QGridLayout()
        self.x_spin = QtWidgets.QSpinBox(); self.x_spin.setRange(0, 99999)
        self.y_spin = QtWidgets.QSpinBox(); self.y_spin.setRange(0, 99999)
        self.w_spin = QtWidgets.QSpinBox(); self.w_spin.setRange(10, 99999)
        self.h_spin = QtWidgets.QSpinBox(); self.h_spin.setRange(40, 99999)
        xy_grid.addWidget(QtWidgets.QLabel("X"), 0,0); xy_grid.addWidget(self.x_spin,0,1)
        xy_grid.addWidget(QtWidgets.QLabel("Y"), 0,2); xy_grid.addWidget(self.y_spin,0,3)
        xy_grid.addWidget(QtWidgets.QLabel("W"), 1,0); xy_grid.addWidget(self.w_spin,1,1)
        xy_grid.addWidget(QtWidgets.QLabel("H"), 1,2); xy_grid.addWidget(self.h_spin,1,3)
        self._sync_from_spins_block = False
        for sp in (self.x_spin, self.y_spin, self.w_spin, self.h_spin):
            sp.valueChanged.connect(self._manual_xywh_changed)
        lform.addRow(QtWidgets.QLabel("Box (px):"), QtWidgets.QWidget()); lform.addRow(xy_grid)
        splitter.addWidget(left)
        self.preview = WavePreviewWidget(); splitter.addWidget(self.preview); splitter.setStretchFactor(1, 1)
        right = QtWidgets.QGroupBox("Encoding"); fe = QtWidgets.QFormLayout(right)
        self.quality = QtWidgets.QComboBox(); self.quality.addItems(["Max bitrate", "Low bitrate"]); fe.addRow("Quality:", self.quality)
        self.encoder = QtWidgets.QComboBox()
        self.encoder.addItem("Auto (GPU if available)", "auto")
        self.encoder.addItem("NVIDIA NVENC (H.264)", "nvenc")
        self.encoder.addItem("AMD AMF (H.264)", "amf")
        self.encoder.addItem("CPU (libx264)", "cpu")
        fe.addRow("Video encoder:", self.encoder)
        splitter.addWidget(right)
        act = QtWidgets.QHBoxLayout()
        self.bg_check = QtWidgets.QCheckBox("Run in background"); self.bg_check.setChecked(True)
        self.btn_run = QtWidgets.QPushButton("Render")
        self.btn_cancel = QtWidgets.QPushButton("Cancel"); self.btn_cancel.setEnabled(False)
        self.btn_run.clicked.connect(self._start); self.btn_cancel.clicked.connect(self._cancel)
        act.addWidget(self.bg_check); act.addStretch(1); act.addWidget(self.btn_cancel); act.addWidget(self.btn_run)
        root.addLayout(act)
        self.pbar = QtWidgets.QProgressBar(); self.pbar.setRange(0,100)
        self.log  = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000)
        root.addWidget(self.pbar); root.addWidget(self.log,1)
        self.preview.geometryChanged.connect(self._preview_box_changed)
        self.opacity.valueChanged.connect(lambda _: self._apply_preview_style())
        self.bg_opacity.valueChanged.connect(lambda _: self._apply_preview_style())
        self.scale_mode.currentIndexChanged.connect(lambda _: self._apply_preview_style())
        self.smoothing.valueChanged.connect(self._on_smoothing_changed)
        self.split_channels.toggled.connect(lambda _: self._apply_preview_style())
        self.barw.valueChanged.connect(lambda _: self.preview.setBarWidth(self.barw.value()))
        self.gapw.valueChanged.connect(lambda _: self.preview.setGapWidth(self.gapw.value()))
        self.roundw.valueChanged.connect(lambda _: self.preview.setRoundness(self.roundw.value()))
        self.preview.setBarWidth(self.barw.value()); self.preview.setGapWidth(self.gapw.value()); self.preview.setRoundness(self.roundw.value())
        self._on_smoothing_changed(self.smoothing.value())
        if not which_ffmpeg(): self._log("⚠ FFmpeg not found on PATH. Please install FFmpeg and restart.")
    def _style_changed(self):
        self.preview.setStyle(self.style.currentData()); self._apply_preview_style()
    def _pick_input(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose video", "", "Video files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)")
        if not path: return
        logger.info("Selected input video: %s", path)
        self.in_edit.setText(path)
        wh = ffprobe_size(path); dur = ffprobe_duration(path) or 1.0
        if not wh:
            QtWidgets.QMessageBox.critical(self,"Video","Could not read input video size (ffprobe)."); return
        self._video_size = wh; self._duration = dur
        fps = ffprobe_fps(path)
        if fps and fps > 0:
            self._fps = fps
        channels = ffprobe_channels(path)
        if channels is None:
            self._audio_channels = None
            self._log('Warning: could not read audio channel count (ffprobe). Assuming stereo for preview.')
        else:
            self._audio_channels = max(0, channels)
            if self._audio_channels == 0:
                self._log('Warning: input appears to have no audio track.')
        enable_split = (self._audio_channels is None) or (self._audio_channels > 1)
        self.split_channels.setEnabled(enable_split)
        if not enable_split:
            self.split_channels.setChecked(False)
        preview_channels = self._audio_channels if (isinstance(self._audio_channels, int) and self._audio_channels > 0) else 2
        self.preview.setChannelCount(max(1, min(6, preview_channels)))
        self._apply_preview_style()
        logger.debug("Input metadata size=%s duration=%.3fs fps=%.3f", wh, dur, getattr(self, "_fps", 0))
        snap = None
        try:
            ff = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
            if shutil.which(ff):
                out = os.path.join(tempfile.gettempdir(), "wejawi_waves_preview.png")
                mid = max(0.0, dur/2.0)
                subprocess.run([ff,"-hide_banner","-loglevel","error","-y","-ss",f"{mid:.2f}","-i",path,"-frames:v","1",out],check=True)
                if os.path.isfile(out): snap = out
        except Exception: snap = None
        self.preview.setVideoMeta(*wh, snapshot_path=snap)
        x,y,w,h = self.preview.getBox(); self._set_spins(x,y,w,h)
    def _pick_output(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save output", "", "MP4 Video (*.mp4)")
        if path:
            if not path.lower().endswith(".mp4"): path += ".mp4"
            self.out_edit.setText(path)
            logger.info("Selected output path: %s", path)
    def _apply_preview_style(self):
        col = QtGui.QColor(self.color_btn.property("color") or "#00FFCC")
        self.preview.setColor(col, self.opacity.value()/100.0)
        self.preview.setBgOpacity(self.bg_opacity.value()/100.0)
        self.preview.setBarWidth(self.barw.value())
        self.preview.setGapWidth(self.gapw.value())
        self.preview.setRoundness(self.roundw.value())
        scale_mode = self.scale_mode.currentData() if hasattr(self, 'scale_mode') else 'lin'
        self.preview.setAmplitudeScale(scale_mode or 'lin')
        smoothing_multiplier = self._smoothing_multiplier(self.smoothing.value()) if hasattr(self, 'smoothing') else _SMOOTHING_PRESETS[2]
        self.preview.setSmoothingMultiplier(smoothing_multiplier)
        split = self.split_channels.isChecked() if hasattr(self, 'split_channels') else False
        self.preview.setSplitChannels(split)
        channels = self._audio_channels if isinstance(self._audio_channels, int) and self._audio_channels > 0 else (2 if split else 1)
        if not split:
            channels = 1
        self.preview.setChannelCount(max(1, min(6, channels)))
    def _pick_color(self):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.color_btn.property("color") or "#00FFCC"), self, "Pick waveform color")
        if col.isValid():
            self.color_btn.setProperty("color", col.name()); self._apply_color_btn_style(self.color_btn); self._apply_preview_style()
    def _preview_box_changed(self, x:int,y:int,w:int,h:int): self._set_spins(x,y,w,h)
    def _set_spins(self, x:int,y:int,w:int,h:int):
        self._sync_from_spins_block = True
        self.x_spin.setValue(x); self.y_spin.setValue(y); self.w_spin.setValue(w); self.h_spin.setValue(h)
        self._sync_from_spins_block = False
    def _manual_xywh_changed(self, *_):
        if getattr(self, "_sync_from_spins_block", False): return
        self.preview.setBox(self.x_spin.value(), self.y_spin.value(), self.w_spin.value(), self.h_spin.value())
    def _log(self, s: str):
        text = str(s)
        if text:
            logger.info('SoundWaves: %s', text)
        self.log.appendPlainText(text)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())
    def _start(self):
        if not self.in_edit.text().strip():
            QtWidgets.QMessageBox.warning(self,"Input","Pick an input video first."); return
        if not which_ffmpeg() or not which_ffprobe():
            QtWidgets.QMessageBox.critical(self,"FFmpeg","FFmpeg/FFprobe not found in PATH."); return
        vin = self.in_edit.text().strip()
        vout = self.out_edit.text().strip() or "output_waves.mp4"
        logger.info("Starting render vin=%s vout=%s", vin, vout)
        vw, vh = self._video_size; dur = float(self._duration or 0.0)
        if isinstance(self._audio_channels, int) and self._audio_channels == 0:
            QtWidgets.QMessageBox.warning(self, "Audio", "Input video has no audio track. Please add audio before rendering sound waves.")
            return
        fps = getattr(self, "_fps", 30.0) or 30.0
        try:
            fps = float(fps)
        except Exception:
            fps = 30.0
        fps = max(1.0, min(240.0, fps))
        mask_duration = max(1.0, dur + 1.0)
        def _fmt_float(val: float) -> str:
            s = f"{val:.6f}"
            return s.rstrip("0").rstrip(".") if "." in s else s
        fps_str = _fmt_float(fps)
        mask_duration_str = _fmt_float(mask_duration)
        x_px,y_px,bw,bh = self.preview.getBox()
        style = self.style.currentData()
        color_hex = self.color_btn.property("color") or "#00FFCC"
        color_arg = _ffmpeg_color_arg(color_hex)
        alpha = max(0.1, min(1.0, self.opacity.value()/100.0))
        bg_alpha = max(0.0, min(0.9, self.bg_opacity.value()/100.0))
        draw_bg = bg_alpha > 0.01
        bar_px = max(2, min(40, int(self.barw.value())))
        gap_px = max(0, min(20, int(self.gapw.value())))
        round_px = max(0, min(20, int(self.roundw.value())))
        split_requested = bool(self.split_channels.isChecked())
        channel_guess = self._audio_channels if isinstance(self._audio_channels, int) and self._audio_channels > 0 else (2 if split_requested else 1)
        channel_guess = max(1, min(6, channel_guess))
        split_channels = split_requested and channel_guess > 1
        amp_scale = (self.scale_mode.currentData() or 'lin') if hasattr(self, 'scale_mode') else 'lin'
        if amp_scale not in {'lin', 'log', 'sqrt', 'cbrt'}:
            amp_scale = 'lin'
        smooth_idx = self.smoothing.value() if hasattr(self, 'smoothing') else 2
        smooth_multiplier = self._smoothing_multiplier(smooth_idx)
        def _calc_wave_n(base: int) -> int:
            base = max(1, int(base))
            if smooth_idx == 0:
                return 1
            mult = smooth_multiplier if smooth_multiplier and smooth_multiplier > 0 else 1.0
            return max(1, min(16384, int(round(base * mult))))
        def _calc_freq_averaging() -> int:
            if smooth_idx == 0:
                return 1
            mult = smooth_multiplier if smooth_multiplier and smooth_multiplier > 0 else 1.0
            return max(1, min(64, int(round(1 + mult * 2))))
        freq_averaging = _calc_freq_averaging()
        wave_n_used = None
        fx = []
        if style in ("sticks","rounded"):
            period = bar_px + gap_px
            cols = max(1, min(400, (bw + gap_px)//max(1,period)))
            used_w = cols*bar_px + (cols-1)*gap_px
            off_x = x_px + max(0, (bw-used_w)//2)
            channels_for_color = channel_guess if split_channels else 1
            wave_colors = '|'.join(['white'] * max(1, channels_for_color))
            wave_n_cols = _calc_wave_n(cols)
            wave_n_used = wave_n_cols
            showwaves_parts = [
                f"s={cols}x{bh}",
                "mode=cline",
                f"n={wave_n_cols}",
                f"colors={wave_colors}",
                f"scale={amp_scale}",
            ]
            if split_channels:
                showwaves_parts.append('split_channels=1')
            fx.append(f"[0:a]aformat=channel_layouts=stereo,showwaves={':'.join(showwaves_parts)}[wave]")
            fx.append(f"[wave]format=gray,scale={used_w}:{bh}:flags=neighbor[waveg]")
            mask_expr = _rounded_bar_mask_expr(period, bar_px, bh, round_px if style == "rounded" else 0)
            fx.append(f"nullsrc=size={used_w}x{bh}:duration={mask_duration_str}:rate={fps_str},format=gray,geq='lum={mask_expr}'[mask]")
            fx.append("[waveg][mask]blend=all_mode='multiply'[alphamask]")
            fx.append(f"color=color={color_arg}@1.0:size={used_w}x{bh}:rate={fps_str}:duration={mask_duration_str},format=rgba[colclip]")
            fx.append("[colclip][alphamask]alphamerge[sw]")
            if alpha < 0.999:
                fx.append(f"[sw]colorchannelmixer=aa={alpha:.3f}[sw]")
            if draw_bg:
                fx.append(f"[0:v]drawbox=x={off_x}:y={y_px}:w={used_w}:h={bh}:color=black@{bg_alpha:.2f}:t=fill[bg]")
                fx.append(f"[bg][sw]overlay=x={off_x}:y={y_px}[vout]")
            else:
                fx.append(f"[0:v][sw]overlay=x={off_x}:y={y_px}[vout]")
        elif style == "line":
            wave_n = _calc_wave_n(max(1, bw))
            wave_n_used = wave_n
            color_entry = f"{color_arg}@{alpha:.2f}"
            channels_for_color = channel_guess if split_channels else 1
            wave_colors = '|'.join([color_entry] * max(1, channels_for_color))
            showwaves_parts = [
                f"s={bw}x{bh}",
                "mode=line",
                f"colors={wave_colors}",
                f"scale={amp_scale}",
                f"n={wave_n}",
            ]
            if split_channels:
                showwaves_parts.append('split_channels=1')
            fx.append(f"[0:a]aformat=channel_layouts=stereo,showwaves={':'.join(showwaves_parts)}[sw]")
            if draw_bg:
                fx.append(f"[0:v]drawbox=x={x_px}:y={y_px}:w={bw}:h={bh}:color=black@{bg_alpha:.2f}:t=fill[bg]")
                fx.append(f"[bg][sw]overlay=x={x_px}:y={y_px}[vout]")
            else:
                fx.append(f"[0:v][sw]overlay=x={x_px}:y={y_px}[vout]")
        else:  # spectrum
            period = bar_px + gap_px
            cols = max(4, min(200, (bw + gap_px)//max(1,period)))
            used_w = cols*bar_px + (cols-1)*gap_px
            off_x = x_px + max(0, (bw-used_w)//2)
            channels_for_color = channel_guess if split_channels else 1
            freq_colors = '|'.join([color_arg] * max(1, channels_for_color))
            freq_opts = [
                f"s={cols}x{bh}",
                "mode=bar",
                f"colors={freq_colors}",
                f"ascale={amp_scale}",
                f"averaging={freq_averaging}",
            ]
            if split_channels:
                freq_opts.append('cmode=separate')
            fx.append(f"[0:a]aformat=channel_layouts=stereo,showfreqs={':'.join(freq_opts)}[rawsw]")
            fx.append(f"[rawsw]format=rgba,scale={used_w}:{bh}:flags=neighbor[bars]")
            # Build mask stripes via helper (handles escaping and rounding)
            mask_expr = _rounded_bar_mask_expr(period, bar_px, bh, round_px)
            fx.append(f"nullsrc=size={used_w}x{bh}:duration={mask_duration_str}:rate={fps_str},format=gray,geq='lum={mask_expr}'[mask]")
            fx.append("[bars][mask]alphamerge[tmpa]")
            fx.append("[tmpa]format=rgba[sw]")
            if alpha < 0.999:
                fx.append(f"[sw]colorchannelmixer=aa={alpha:.3f}[sw]")
            if draw_bg:
                fx.append(f"[0:v]drawbox=x={off_x}:y={y_px}:w={used_w}:h={bh}:color=black@{bg_alpha:.2f}:t=fill[bg]")
                fx.append(f"[bg][sw]overlay=x={off_x}:y={y_px}[vout]")
            else:
                fx.append(f"[0:v][sw]overlay=x={off_x}:y={y_px}[vout]")
        fx.append("[vout]format=yuv420p[vout]")  # compatibility
        filter_complex = ";".join(fx)
        enc_args, enc_name = _pick_encoder_args(self.encoder.currentData() or "auto", self._log)
        if "Max" in self.quality.currentText():
            vkbps = 12000 if max(vw, vh) <= 1920 else 20000
        else:
            vkbps = 2000 if max(vw, vh) <= 1280 else 3000
        rate_args = ["-b:v", f"{vkbps}k", "-maxrate", f"{vkbps}k", "-bufsize", f"{2*vkbps}k"]
        cmd = [
            which_ffmpeg(), "-hide_banner", "-y",
            "-i", vin,
            "-filter_complex", filter_complex,
            *enc_args, *rate_args, "-pix_fmt", "yuv420p",
            "-map", "[vout]", "-map", "0:a?", "-c:a", "copy",
            "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", "-shortest", vout
        ]
        meta = {
            "tool":"sound_waves","input":vin,"output":vout,
            "video_size":{"w":vw,"h":vh},"input_duration_s":dur,
            "input_fps":fps,
            "style":style,"box":{"x":x_px,"y":y_px,"w":bw,"h":bh},
            "color":color_hex,"opacity_pct":self.opacity.value(),"bg_opacity_pct":self.bg_opacity.value(),
            "bar_px":bar_px,"gap_px":gap_px,"round_px":round_px,
            "split_channels":split_channels,
            "split_requested":split_requested,
            "detected_channels":self._audio_channels,
            "channel_count_estimate":channel_guess if split_channels else 1,
            "amp_scale":amp_scale,
            "smoothing_index":smooth_idx,
            "smoothing_multiplier":smooth_multiplier,
            "wave_samples_value":wave_n_used,
            "freq_averaging":freq_averaging,
            "encoder_choice":self.encoder.currentData() or "auto","encoder_name":enc_name,
            "quality":self.quality.currentText(),"bitrate_kbps_target":vkbps,
            "mask_duration_s":mask_duration,
            "filter_complex":filter_complex,
            "cmd_preview":" ".join(str(x) for x in cmd)
        }
        self._log(f"Using encoder: {enc_name}")
        self._log("Starting FFmpeg…")
        jm = JobManager.instance()
        job_id = jm.start_ffmpeg_job(cmd, dur, meta, tag="sound_waves")
        logger.debug("Started FFmpeg job %s", job_id)
        def _on_prog(jid,pct): 
            if jid==job_id: self.pbar.setValue(pct)
        def _on_log(jid,line): 
            if jid==job_id: self._log(line)
        def _on_done(jid,code):
            if jid==job_id:
                self.btn_cancel.setEnabled(False)
                if code==0:
                    self.pbar.setValue(100); self._log(f"Done. Saved: {vout}")
                    logger.info("Render completed successfully (%s)", vout)
                    if not self.bg_check.isChecked():
                        QtWidgets.QMessageBox.information(self,"Sound Waves",f"Saved:\n{vout}")
                else:
                    self._log("Render cancelled or failed. See log.")
                    logger.error("Render failed or cancelled (job=%s)", job_id)
        jm.jobProgress.connect(_on_prog); jm.jobLog.connect(_on_log); jm.jobFinished.connect(_on_done)
        self.btn_cancel.setEnabled(True); self._current_job_id = job_id
    def _cancel(self):
        try:
            jid = getattr(self,"_current_job_id",None)
            if jid: 
                JobManager.instance().cancel(jid)
                self._log("Cancel requested.")
                logger.info("Render cancellation requested (job=%s)", jid)
        finally:
            self.btn_cancel.setEnabled(False)
