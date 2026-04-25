# tools/motion_graphics.py
# Motion Graphics via HeyGen Hyperframes — HTML + GSAP → MP4 via headless Chromium + FFmpeg.
# No avatar required. Takes script text or SRT → generates kinetic typography video.

import html
import json
import os
import shutil
import sys
import tempfile
from typing import List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from tools.captions import parse_srt, parse_vtt, Segment


# ── constants ─────────────────────────────────────────────────────────────────

STYLE_PRESETS = [
    {
        "name":       "Dark Purple  (WeJaWi brand)",
        "bg":         "#0b0b14",
        "text":       "#ffffff",
        "accent":     "#a855f7",
        "font":       "Inter, system-ui, sans-serif",
        "size":       72,
        "bg_preview": "#0b0b14",
    },
    {
        "name":       "Clean Light",
        "bg":         "#fafaff",
        "text":       "#0b0b14",
        "accent":     "#7c3aed",
        "font":       "Inter, system-ui, sans-serif",
        "size":       72,
        "bg_preview": "#fafaff",
    },
    {
        "name":       "Bold Yellow  (viral-style)",
        "bg":         "#111111",
        "text":       "#fde047",
        "accent":     "#f59e0b",
        "font":       "Impact, 'Arial Black', sans-serif",
        "size":       80,
        "bg_preview": "#111111",
    },
    {
        "name":       "Neon Cyber",
        "bg":         "#050510",
        "text":       "#39ff14",
        "accent":     "#ff00ff",
        "font":       "'Courier New', Courier, monospace",
        "size":       66,
        "bg_preview": "#050510",
    },
    {
        "name":       "Warm Cream  (editorial)",
        "bg":         "#f5f0e8",
        "text":       "#1a1208",
        "accent":     "#c2854a",
        "font":       "Georgia, 'Times New Roman', serif",
        "size":       68,
        "bg_preview": "#f5f0e8",
    },
    {
        "name":       "Red Energy  (sports/gaming)",
        "bg":         "#0a0a0a",
        "text":       "#ff2d55",
        "accent":     "#ff6b35",
        "font":       "'Arial Black', sans-serif",
        "size":       76,
        "bg_preview": "#0a0a0a",
    },
]

RESOLUTIONS: List[Tuple[str, int, int]] = [
    ("1920 × 1080  (16:9  Landscape)",      1920, 1080),
    ("1080 × 1920  (9:16  Shorts / TikTok)", 1080, 1920),
    ("1080 × 1080  (1:1   Square)",          1080, 1080),
    ("1280 × 720   (720p)",                  1280,  720),
]

ANIM_PRESETS: List[Tuple[str, str]] = [
    ("Fade up  (smooth, professional)",  "fade_up"),
    ("Slide in  (energetic)",            "slide_in"),
    ("Scale pop  (punchy, social-media)","scale_pop"),
    ("Simple fade  (minimal)",           "simple_fade"),
]

FPS_OPTIONS = [("24 fps  (cinematic)", 24), ("30 fps  (standard)", 30), ("60 fps  (smooth)", 60)]
QUALITY_OPTIONS = [("Draft  (fast preview)", "draft"), ("Standard", "standard"), ("High  (near-lossless)", "high")]

HYPERFRAMES_MIN_VERSION = "0.1.0"   # just for the install tip


# ── utilities ─────────────────────────────────────────────────────────────────

def _find_npx() -> Optional[str]:
    npx = shutil.which("npx")
    if npx:
        return npx
    for p in ("/opt/homebrew/bin/npx", "/usr/local/bin/npx", "/usr/bin/npx"):
        if os.path.isfile(p):
            return p
    return None


def _find_node() -> Optional[str]:
    node = shutil.which("node")
    if node:
        return node
    for p in ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        if os.path.isfile(p):
            return p
    return None


def _plain_to_segments(text: str, words_per_seg: int = 8, wps: float = 2.8) -> List[Segment]:
    """Convert plain script text into timed Segments."""
    words = text.split()
    if not words:
        return []
    segs: List[Segment] = []
    t = 0.0
    i = 0
    while i < len(words):
        chunk = words[i:i + words_per_seg]
        i += words_per_seg
        dur = max(1.5, len(chunk) / wps)
        segs.append(Segment(t, t + dur, " ".join(chunk)))
        t += dur + 0.15
    return segs


def _html_escape(text: str) -> str:
    return html.escape(text)


# ── HTML composition generator ────────────────────────────────────────────────

def build_composition_html(segments: List[Segment], style: dict,
                           anim: str, w: int, h: int,
                           audio_path: Optional[str] = None) -> str:
    bg    = style["bg"]
    fg    = style["text"]
    font  = style["font"]
    fsize = style["size"]

    total = (max(s.end for s in segments) + 1.5) if segments else 10.0
    is_portrait = h > w

    # Caption divs — all invisible initially, GSAP controls animation
    seg_divs = "\n".join(
        f'  <div id="seg_{i}" class="cap">{_html_escape(s.text)}</div>'
        for i, s in enumerate(segments)
    )

    # Optional audio element
    audio_el = ""
    if audio_path:
        rel = os.path.basename(audio_path)
        audio_el = (
            f'\n  <audio id="narration" data-start="0" data-has-audio="true" '
            f'data-track-index="99" src="{rel}"></audio>'
        )

    # GSAP timeline entries per segment
    gsap_lines: List[str] = []
    for i, s in enumerate(segments):
        dur      = max(0.4, s.end - s.start)
        fade_in  = min(0.35, dur * 0.25)
        fade_out = min(0.30, dur * 0.20)
        fade_out_at = max(s.start + fade_in + 0.05, s.end - fade_out)

        t = f"{s.start:.3f}"
        fo = f"{fade_out_at:.3f}"

        if anim == "fade_up":
            gsap_lines.append(
                f"  tl.fromTo('#seg_{i}',{{opacity:0,y:40}},{{opacity:1,y:0,"
                f"duration:{fade_in:.2f},ease:'power2.out'}},{t});"
            )
            gsap_lines.append(
                f"  tl.to('#seg_{i}',{{opacity:0,y:-20,duration:{fade_out:.2f},"
                f"ease:'power2.in'}},{fo});"
            )
        elif anim == "slide_in":
            gsap_lines.append(
                f"  tl.fromTo('#seg_{i}',{{opacity:0,x:-100}},{{opacity:1,x:0,"
                f"duration:{fade_in:.2f},ease:'back.out(1.4)'}},{t});"
            )
            gsap_lines.append(
                f"  tl.to('#seg_{i}',{{opacity:0,x:100,duration:{fade_out:.2f},"
                f"ease:'power2.in'}},{fo});"
            )
        elif anim == "scale_pop":
            gsap_lines.append(
                f"  tl.fromTo('#seg_{i}',{{opacity:0,scale:0.75}},{{opacity:1,scale:1,"
                f"duration:{fade_in:.2f},ease:'back.out(2.2)'}},{t});"
            )
            gsap_lines.append(
                f"  tl.to('#seg_{i}',{{opacity:0,scale:1.15,duration:{fade_out:.2f},"
                f"ease:'power2.in'}},{fo});"
            )
        else:  # simple_fade
            gsap_lines.append(
                f"  tl.fromTo('#seg_{i}',{{opacity:0}},{{opacity:1,"
                f"duration:{fade_in:.2f}}},{t});"
            )
            gsap_lines.append(
                f"  tl.to('#seg_{i}',{{opacity:0,duration:{fade_out:.2f}}},{fo});"
            )

    # Sentinel to tell Hyperframes the total duration
    gsap_lines.append(f"  tl.to({{}}, {{}}, {total:.3f});")

    gsap_code = "\n".join(gsap_lines)

    # Vertical text position
    if is_portrait:
        text_pos = "top: 50%; transform: translateY(-50%);"
    else:
        text_pos = "bottom: 14%;"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: {bg}; overflow: hidden; }}
    #stage {{
      width: {w}px;
      height: {h}px;
      position: relative;
      overflow: hidden;
      background: {bg};
    }}
    .cap {{
      position: absolute;
      left: 10%;
      width: 80%;
      {text_pos}
      text-align: center;
      font-family: {font};
      font-size: {fsize}px;
      font-weight: 700;
      line-height: 1.3;
      color: {fg};
      opacity: 0;
      will-change: transform, opacity;
    }}
  </style>
</head>
<body>
<div id="stage"
     data-composition-id="wejawi_motion"
     data-start="0"
     data-width="{w}"
     data-height="{h}">{audio_el}
{seg_divs}
</div>
<script>
  const tl = gsap.timeline({{ paused: true }});
{gsap_code}
  window.__timelines = {{ wejawi_motion: tl }};
</script>
</body>
</html>"""


HYPERFRAMES_JSON = json.dumps({
    "paths": {
        "blocks": "compositions",
        "components": "compositions/components",
        "assets": "assets",
    }
}, indent=2)


# ── Node process runner ───────────────────────────────────────────────────────

class _NodeRunner(QtCore.QObject):
    progressChanged = QtCore.pyqtSignal(int)
    logLine         = QtCore.pyqtSignal(str)
    finished        = QtCore.pyqtSignal(int)

    def __init__(self, cmd: List[str], parent=None):
        super().__init__(parent)
        self._cmd  = cmd
        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.finished.connect(lambda code, _: self.finished.emit(code))
        self._last_pct = 5

    def start(self):
        env = QtCore.QProcessEnvironment.systemEnvironment()
        # Suppress npm update-notifier noise
        env.insert("NO_UPDATE_NOTIFIER", "1")
        env.insert("NPM_CONFIG_UPDATE_NOTIFIER", "false")
        self._proc.setProcessEnvironment(env)
        self._proc.start(self._cmd[0], self._cmd[1:])

    def cancel(self):
        try:
            self._proc.kill()
        except Exception:
            pass

    def _read(self):
        raw = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "ignore")
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            self.logLine.emit(line)
            # Heuristic progress detection from hyperframes render output
            lo = line.lower()
            if any(k in lo for k in ("installing", "downloading", "fetching")):
                self._emit_pct(15)
            elif "capturing" in lo or "rendering" in lo:
                self._emit_pct(min(85, self._last_pct + 3))
            elif "encoding" in lo or "ffmpeg" in lo:
                self._emit_pct(90)
            elif "complete" in lo or "saved" in lo or "written" in lo:
                self._emit_pct(98)

    def _emit_pct(self, pct: int):
        if pct > self._last_pct:
            self._last_pct = pct
            self.progressChanged.emit(pct)


# ── TTS runner ────────────────────────────────────────────────────────────────

class _TTSRunner(QtCore.QObject):
    logLine  = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(int, str)  # exit_code, output_path

    def __init__(self, npx: str, text: str, out_path: str, voice: str = "af_nova",
                 parent=None):
        super().__init__(parent)
        self._out  = out_path
        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.finished.connect(lambda code, _: self.finished.emit(code, self._out))
        self._cmd = [npx, "hyperframes", "tts", text, "-o", out_path, "-v", voice]

    def start(self):
        self._proc.start(self._cmd[0], self._cmd[1:])

    def _read(self):
        raw = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "ignore")
        for line in raw.splitlines():
            if line.strip():
                self.logLine.emit(line.strip())


# ── Page ──────────────────────────────────────────────────────────────────────

class MotionGraphicsPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._segments: List[Segment] = []
        self._audio_path: Optional[str] = None
        self._runner: Optional[_NodeRunner]  = None
        self._tts_runner: Optional[_TTSRunner] = None
        self._project_dir: Optional[str] = None
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── LEFT: settings ────────────────────────────────────────────────────
        left_w = QtWidgets.QWidget()
        left   = QtWidgets.QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)

        left.addWidget(QtWidgets.QLabel("Motion Graphics", objectName="PageTitle"))
        sub = QtWidgets.QLabel(
            "Powered by HeyGen Hyperframes — generates animated kinetic-typography "
            "video from your script or SRT file. Requires Node.js (brew install node)."
        )
        sub.setWordWrap(True)
        sub.setObjectName("PageSubtitle")
        left.addWidget(sub)

        # Node.js status badge
        self.node_label = QtWidgets.QLabel()
        self._refresh_node_status()
        left.addWidget(self.node_label)

        # 1) Source
        g1 = QtWidgets.QGroupBox("1) Content source")
        v1 = QtWidgets.QVBoxLayout(g1)
        self.tabs = QtWidgets.QTabWidget()

        # Tab A: Script text
        tab_script = QtWidgets.QWidget()
        tv = QtWidgets.QVBoxLayout(tab_script)
        tv.setContentsMargins(6, 6, 6, 6)
        self.script_edit = QtWidgets.QPlainTextEdit()
        self.script_edit.setPlaceholderText(
            "Paste your script here…\n\nEach group of words becomes one animated caption card."
        )
        self.script_edit.setMinimumHeight(130)
        words_row = QtWidgets.QHBoxLayout()
        words_row.addWidget(QtWidgets.QLabel("Words per card:"))
        self.words_spin = QtWidgets.QSpinBox()
        self.words_spin.setRange(3, 20)
        self.words_spin.setValue(8)
        words_row.addWidget(self.words_spin)
        words_row.addStretch(1)
        tv.addWidget(self.script_edit, 1)
        tv.addLayout(words_row)
        self.tabs.addTab(tab_script, "Script text")

        # Tab B: SRT / VTT file
        tab_srt = QtWidgets.QWidget()
        sv = QtWidgets.QVBoxLayout(tab_srt)
        sv.setContentsMargins(6, 6, 6, 6)
        srt_row = QtWidgets.QHBoxLayout()
        self.srt_edit = QtWidgets.QLineEdit()
        self.srt_edit.setPlaceholderText("Path to .srt or .vtt subtitle file…")
        btn_srt = QtWidgets.QPushButton("Browse…")
        btn_srt.clicked.connect(self._browse_srt)
        srt_row.addWidget(self.srt_edit, 1)
        srt_row.addWidget(btn_srt)
        sv.addLayout(srt_row)
        self.srt_preview = QtWidgets.QLabel("No file loaded.")
        self.srt_preview.setWordWrap(True)
        self.srt_preview.setStyleSheet("color: #a89cc9; font-size: 11px;")
        sv.addWidget(self.srt_preview)
        sv.addStretch(1)
        self.tabs.addTab(tab_srt, "SRT / VTT file")

        v1.addWidget(self.tabs)
        left.addWidget(g1)

        # 2) Audio (optional)
        g_audio = QtWidgets.QGroupBox("2) Audio  (optional)")
        va = QtWidgets.QVBoxLayout(g_audio)
        audio_top = QtWidgets.QHBoxLayout()
        self.audio_edit = QtWidgets.QLineEdit()
        self.audio_edit.setPlaceholderText("WAV / MP3 file to embed (leave blank for silent video)")
        btn_audio = QtWidgets.QPushButton("Browse…")
        btn_audio.clicked.connect(self._browse_audio)
        audio_top.addWidget(self.audio_edit, 1)
        audio_top.addWidget(btn_audio)
        va.addLayout(audio_top)

        tts_row = QtWidgets.QHBoxLayout()
        self.tts_voice = QtWidgets.QComboBox()
        for v in ["af_nova", "af_bella", "am_adam", "bf_emma", "bm_daniel"]:
            self.tts_voice.addItem(v)
        self.tts_speed = QtWidgets.QDoubleSpinBox()
        self.tts_speed.setRange(0.5, 2.0)
        self.tts_speed.setSingleStep(0.1)
        self.tts_speed.setValue(1.0)
        self.btn_tts = QtWidgets.QPushButton("Generate TTS narration")
        self.btn_tts.setToolTip("Uses Hyperframes' built-in Kokoro TTS — no API key needed")
        self.btn_tts.clicked.connect(self._on_tts)
        tts_row.addWidget(QtWidgets.QLabel("Voice:"))
        tts_row.addWidget(self.tts_voice)
        tts_row.addWidget(QtWidgets.QLabel("Speed:"))
        tts_row.addWidget(self.tts_speed)
        tts_row.addWidget(self.btn_tts)
        va.addLayout(tts_row)
        left.addWidget(g_audio)

        # 3) Style
        g2 = QtWidgets.QGroupBox("3) Style")
        f2 = QtWidgets.QFormLayout(g2)

        self.style_combo = QtWidgets.QComboBox()
        for s in STYLE_PRESETS:
            self.style_combo.addItem(s["name"])
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        f2.addRow("Preset:", self.style_combo)

        self.anim_combo = QtWidgets.QComboBox()
        for label, val in ANIM_PRESETS:
            self.anim_combo.addItem(label, val)
        f2.addRow("Animation:", self.anim_combo)

        self.res_combo = QtWidgets.QComboBox()
        for label, w, h in RESOLUTIONS:
            self.res_combo.addItem(label, (w, h))
        f2.addRow("Resolution:", self.res_combo)

        self.fps_combo = QtWidgets.QComboBox()
        for label, fps in FPS_OPTIONS:
            self.fps_combo.addItem(label, fps)
        self.fps_combo.setCurrentIndex(1)
        f2.addRow("Frame rate:", self.fps_combo)

        self.quality_combo = QtWidgets.QComboBox()
        for label, q in QUALITY_OPTIONS:
            self.quality_combo.addItem(label, q)
        self.quality_combo.setCurrentIndex(1)
        f2.addRow("Quality:", self.quality_combo)

        left.addWidget(g2)

        # Style preview swatch
        self.swatch = QtWidgets.QLabel()
        self.swatch.setFixedHeight(48)
        self.swatch.setAlignment(QtCore.Qt.AlignCenter)
        self._update_swatch()
        left.addWidget(self.swatch)

        left.addStretch(1)

        # ── RIGHT: output + log ───────────────────────────────────────────────
        right_w = QtWidgets.QWidget()
        right   = QtWidgets.QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        right.addWidget(QtWidgets.QLabel("Output", objectName="PageTitle"))

        # Output path
        out_box = QtWidgets.QGroupBox("Output file")
        out_row = QtWidgets.QHBoxLayout(out_box)
        self.out_edit = QtWidgets.QLineEdit("motion_output.mp4")
        btn_out = QtWidgets.QPushButton("Pick…")
        btn_out.clicked.connect(self._pick_out)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(btn_out)
        right.addWidget(out_box)

        # Segment preview
        self.seg_list = QtWidgets.QListWidget()
        self.seg_list.setMaximumHeight(160)
        self.seg_list.setToolTip("Detected caption segments — each becomes one animated card")
        right.addWidget(QtWidgets.QLabel("Caption segments preview:"))
        right.addWidget(self.seg_list)

        # Render controls
        render_row = QtWidgets.QHBoxLayout()
        self.btn_preview = QtWidgets.QPushButton("Preview segments")
        self.btn_preview.clicked.connect(self._on_preview_segments)
        self.btn_render  = QtWidgets.QPushButton("Generate video ✨")
        self.btn_render.setMinimumHeight(38)
        self.btn_cancel  = QtWidgets.QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_preview.clicked.connect(self._on_preview_segments)
        self.btn_render.clicked.connect(self._on_render)
        self.btn_cancel.clicked.connect(self._on_cancel)
        render_row.addWidget(self.btn_preview)
        render_row.addWidget(self.btn_render, 1)
        render_row.addWidget(self.btn_cancel)
        right.addLayout(render_row)

        self.pbar = QtWidgets.QProgressBar()
        self.pbar.setRange(0, 100)
        right.addWidget(self.pbar)

        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        right.addWidget(self.log, 1)

        # Reveal button (shown after render completes)
        self.btn_reveal = QtWidgets.QPushButton("Reveal in Finder")
        self.btn_reveal.setVisible(False)
        self.btn_reveal.clicked.connect(self._reveal_output)
        right.addWidget(self.btn_reveal)

        # ── splitter ─────────────────────────────────────────────────────────
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(left_w)
        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([420, 580])
        root.addWidget(splitter)

        # Connect style change to swatch
        self.style_combo.currentIndexChanged.connect(self._update_swatch)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _refresh_node_status(self):
        npx  = _find_npx()
        node = _find_node()
        if npx and node:
            self.node_label.setText("✅  Node.js & npx found — ready to render")
            self.node_label.setStyleSheet("color: #22c55e; font-size: 11px;")
        else:
            self.node_label.setText(
                "⚠️  Node.js not found. Install with: brew install node   "
                "(then restart WeJaWi)"
            )
            self.node_label.setStyleSheet("color: #f59e0b; font-size: 11px;")

    def _current_style(self) -> dict:
        return STYLE_PRESETS[self.style_combo.currentIndex()]

    def _update_swatch(self):
        s  = self._current_style()
        bg = s["bg"]
        fg = s["text"]
        ac = s["accent"]
        self.swatch.setText("Aa  Sample caption text")
        self.swatch.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 6px; "
            f"padding: 8px; font-weight: bold; font-size: 14px; "
            f"border: 2px solid {ac};"
        )

    def _on_style_changed(self):
        self._update_swatch()

    def log_msg(self, s: str):
        self.log.appendPlainText(s)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    # ── segment parsing ───────────────────────────────────────────────────────

    def _parse_segments(self) -> List[Segment]:
        if self.tabs.currentIndex() == 0:
            text = self.script_edit.toPlainText().strip()
            if not text:
                return []
            return _plain_to_segments(text, self.words_spin.value())
        else:
            path = self.srt_edit.text().strip()
            if not path or not os.path.exists(path):
                return []
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                data = f.read()
            if path.lower().endswith(".vtt"):
                return parse_vtt(data)
            return parse_srt(data)

    def _on_preview_segments(self):
        segs = self._parse_segments()
        if not segs:
            QtWidgets.QMessageBox.warning(
                self, "No content", "Enter script text or load an SRT file first."
            )
            return
        self._segments = segs
        self.seg_list.clear()
        for s in segs:
            mins, secs = int(s.start // 60), s.start % 60
            self.seg_list.addItem(f"[{mins}:{secs:05.2f}]  {s.text}")
        self.log_msg(f"Parsed {len(segs)} segments. Total duration: {segs[-1].end:.1f}s")

    # ── file pickers ──────────────────────────────────────────────────────────

    def _browse_srt(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load subtitle file", "",
            "Subtitle files (*.srt *.vtt);;All files (*.*)"
        )
        if path:
            self.srt_edit.setText(path)
            segs = self._parse_segments()
            if segs:
                self._segments = segs
                self.srt_preview.setText(
                    f"Loaded {len(segs)} segments  ·  "
                    f"{segs[-1].end:.1f}s total"
                )
                self.seg_list.clear()
                for s in segs:
                    mins, secs = int(s.start // 60), s.start % 60
                    self.seg_list.addItem(f"[{mins}:{secs:05.2f}]  {s.text}")

    def _browse_audio(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select audio file", "",
            "Audio (*.wav *.mp3 *.m4a *.aac *.ogg)"
        )
        if path:
            self.audio_edit.setText(path)
            self._audio_path = path

    def _pick_out(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save output video", "", "MP4 Video (*.mp4)"
        )
        if path:
            if not path.lower().endswith(".mp4"):
                path += ".mp4"
            self.out_edit.setText(path)

    # ── TTS ───────────────────────────────────────────────────────────────────

    def _on_tts(self):
        npx = _find_npx()
        if not npx:
            QtWidgets.QMessageBox.critical(
                self, "Node.js",
                "npx not found.\nInstall Node.js: brew install node"
            )
            return
        text = self.script_edit.toPlainText().strip()
        if not text:
            QtWidgets.QMessageBox.warning(
                self, "TTS", "Enter script text first (Script text tab)."
            )
            return

        tmpdir = tempfile.mkdtemp(prefix="wejawi_tts_")
        out_wav = os.path.join(tmpdir, "narration.wav")
        voice   = self.tts_voice.currentText()

        self.btn_tts.setEnabled(False)
        self.log_msg(f"Generating TTS with voice '{voice}'…")
        self.log_msg("(First run downloads Kokoro-82M model ~300 MB)")

        self._tts_runner = _TTSRunner(npx, text, out_wav, voice, self)
        self._tts_runner.logLine.connect(self.log_msg)

        def _done(code: int, path: str):
            self.btn_tts.setEnabled(True)
            if code == 0 and os.path.exists(path):
                self._audio_path = path
                self.audio_edit.setText(path)
                self.log_msg(f"TTS saved → {path}")
            else:
                self.log_msg("TTS generation failed — check log above.")

        self._tts_runner.finished.connect(_done)
        self._tts_runner.start()

    # ── render ────────────────────────────────────────────────────────────────

    def _on_render(self):
        npx = _find_npx()
        if not npx:
            QtWidgets.QMessageBox.critical(
                self, "Node.js",
                "npx not found — please install Node.js.\n"
                "On macOS:  brew install node\n"
                "Then restart WeJaWi."
            )
            return

        segs = self._segments or self._parse_segments()
        if not segs:
            QtWidgets.QMessageBox.warning(
                self, "Content",
                "No caption segments found.\n"
                "Enter script text or load an SRT file, then click 'Preview segments'."
            )
            return

        out_path = self.out_edit.text().strip() or "motion_output.mp4"
        out_path = os.path.abspath(out_path)

        style   = self._current_style()
        anim    = self.anim_combo.currentData() or "fade_up"
        w, h    = self.res_combo.currentData() or (1920, 1080)
        fps     = self.fps_combo.currentData() or 30
        quality = self.quality_combo.currentData() or "standard"

        # Resolve audio
        audio_src = self.audio_edit.text().strip() or None
        if audio_src and not os.path.exists(audio_src):
            audio_src = None

        # Build project in temp dir
        project_dir = tempfile.mkdtemp(prefix="wejawi_hf_")
        self._project_dir = project_dir

        # Write hyperframes.json
        with open(os.path.join(project_dir, "hyperframes.json"), "w") as f:
            f.write(HYPERFRAMES_JSON)

        # Copy audio into project dir (Hyperframes needs relative src)
        audio_project_path = None
        if audio_src:
            dst = os.path.join(project_dir, os.path.basename(audio_src))
            import shutil as _sh
            _sh.copy2(audio_src, dst)
            audio_project_path = dst

        # Generate index.html
        html_content = build_composition_html(
            segs, style, anim, w, h,
            audio_path=audio_project_path,
        )
        with open(os.path.join(project_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_content)

        self.log_msg(f"Project dir: {project_dir}")
        self.log_msg(f"Segments: {len(segs)}  ·  Resolution: {w}×{h}  ·  FPS: {fps}  ·  Quality: {quality}")
        self.log_msg("Running npx hyperframes render…")
        self.log_msg("(First run installs Hyperframes packages — may take 1–2 min)")

        cmd = [
            npx, "--yes", "hyperframes", "render", project_dir,
            "-o", out_path,
            "-f", str(fps),
            "-q", quality,
            "--format", "mp4",
        ]

        self.btn_render.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_reveal.setVisible(False)
        self.pbar.setValue(5)

        self._runner = _NodeRunner(cmd, self)
        self._runner.progressChanged.connect(self.pbar.setValue)
        self._runner.logLine.connect(self.log_msg)

        def _done(code: int):
            self._runner = None
            self.btn_render.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            if code == 0:
                self.pbar.setValue(100)
                self.log_msg(f"Done → {out_path}")
                self.btn_reveal.setVisible(True)
                QtWidgets.QMessageBox.information(
                    self, "Motion Graphics", f"Video saved:\n{out_path}"
                )
            else:
                self.log_msg(
                    "Render failed — check log above.\n"
                    "Tip: make sure FFmpeg is installed (brew install ffmpeg)"
                )

        self._runner.finished.connect(_done)
        self._runner.start()

    def _on_cancel(self):
        if self._runner:
            self._runner.cancel()
            self.log_msg("Cancelled.")
        self.btn_render.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _reveal_output(self):
        path = self.out_edit.text().strip()
        if not path or not os.path.exists(path):
            return
        if sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", "-R", os.path.abspath(path)])
        elif sys.platform.startswith("win"):
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.abspath(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", os.path.dirname(os.path.abspath(path))])
