# tools/captions.py
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PyQt5 import QtWidgets, QtCore, QtGui


def _stt_device_choices() -> List[Tuple[str, str]]:
    """Return (label, value) device options appropriate for the current platform."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return [
            ("Auto (prefer Metal/ANE)", "auto"),
            ("Metal / Neural Engine", "mlx"),
            ("CPU only", "cpu"),
        ]
    if sys.platform.startswith("win"):
        return [
            ("Auto (GPU if available)", "auto"),
            ("NVIDIA (CUDA)", "cuda"),
            ("AMD (DirectML)", "dml"),
            ("CPU", "cpu"),
        ]
    return [
        ("Auto (GPU if available)", "auto"),
        ("NVIDIA (CUDA)", "cuda"),
        ("CPU", "cpu"),
    ]

# --- environment niceties (Windows HF cache warnings etc.)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

ASS_ALIGN_BOTTOM_CENTER = 2  # ASS alignment code

LANG_CHOICES = [
    ("English", "en"),
    ("German",  "de"),
    ("Polish",  "pl"),
    ("Swedish", "sv"),
    ("Norwegian","no"),
    ("Hungarian","hu"),
    ("Spanish", "es"),
]

# STT model choices (smaller = faster to download and run)
STT_MODEL_CHOICES = [
    ("tiny (fastest)", "tiny"),
    ("base (good)",    "base"),
    ("small (better)", "small"),
]

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

@dataclass
class Segment:
    start: float
    end: float
    text: str

def which_ffmpeg() -> Optional[str]:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return shutil.which(exe)

def which_ffprobe() -> Optional[str]:
    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    return shutil.which(exe)

def _run(cmd: List[str]):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, proc.stdout, proc.stderr

def get_video_duration(path: str) -> Optional[float]:
    probe = which_ffprobe()
    if not probe:
        return None
    code, out, _ = _run([probe, "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", path])
    if code != 0:
        return None
    try:
        return float(out.strip())
    except Exception:
        return None

def get_video_size(path: str) -> Optional[Tuple[int, int]]:
    probe = which_ffprobe()
    if not probe:
        return None
    code, out, _ = _run([probe, "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height",
                         "-of", "csv=p=0:s=x", path])
    if code != 0:
        return None
    out = out.strip()
    if "x" in out:
        try:
            w, h = out.split("x")
            return int(w), int(h)
        except Exception:
            return None
    return None

def extract_first_frame(video: str, out_img: str) -> bool:
    ffm = which_ffmpeg()
    if not ffm:
        return False
    code, _, _ = _run([ffm, "-y", "-i", video, "-frames:v", "1", "-q:v", "2", out_img])
    return code == 0

# --- Transcript parsing ------------------------------------------------------

SRT_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")
VTT_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})")

def _time_to_seconds(m):
    return int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3)) + int(m.group(4))/1000.0

def parse_srt(text: str) -> List[Segment]:
    segs: List[Segment] = []
    blocks = re.split(r"\r?\n\r?\n", text.strip())
    for b in blocks:
        lines = [ln.strip("\ufeff") for ln in b.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if "-->" in lines[0]:
            times = lines[0]; words = lines[1:]
        else:
            if len(lines) < 2: continue
            times = lines[1]; words = lines[2:]
        tparts = times.split("-->")
        if len(tparts) != 2: continue
        m1 = SRT_TIME.search(tparts[0]); m2 = SRT_TIME.search(tparts[1])
        if not (m1 and m2): continue
        start = _time_to_seconds(m1); end = _time_to_seconds(m2)
        txt = " ".join(words).strip()
        txt = re.sub(r"<.*?>", "", txt)
        segs.append(Segment(start, end, txt))
    return segs

def parse_vtt(text: str) -> List[Segment]:
    segs: List[Segment] = []
    text = re.sub(r"^WEBVTT.*?\n", "", text, flags=re.IGNORECASE|re.DOTALL)
    blocks = re.split(r"\r?\n\r?\n", text.strip())
    for b in blocks:
        lines = [ln.strip("\ufeff") for ln in b.strip().splitlines() if ln.strip()]
        if not lines: continue
        if "-->" not in lines[0]:
            if len(lines) < 2: continue
            times = lines[1]; words = lines[2:]
        else:
            times = lines[0]; words = lines[1:]
        tparts = times.split("-->")
        if len(tparts) != 2: continue
        m1 = VTT_TIME.search(tparts[0]); m2 = VTT_TIME.search(tparts[1])
        if not (m1 and m2): continue
        start = _time_to_seconds(m1); end = _time_to_seconds(m2)
        txt = " ".join(words).strip()
        txt = re.sub(r"<.*?>", "", txt)
        segs.append(Segment(start, end, txt))
    return segs

def seconds_to_ass(t: float) -> str:
    h = int(t//3600); m = int((t%3600)//60); s = int(t%60); cs = int((t - int(t)) * 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def qcolor_to_ass(qc: QtGui.QColor, alpha: int = 0) -> str:
    r, g, b = qc.red(), qc.green(), qc.blue()
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

def build_ass(style: dict, segments: List[Segment], out_path: str, video_wh: Optional[Tuple[int, int]] = None):
    if video_wh:
        play_res_x, play_res_y = video_wh
    else:
        play_res_x, play_res_y = 1920, 1080

    ass = []
    ass += [
        "[Script Info]","ScriptType: v4.00+",
        f"PlayResX: {play_res_x}",f"PlayResY: {play_res_y}","ScaledBorderAndShadow: yes","",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: WeJaWi,{style['FontName']},{style['FontSize']},{style['PrimaryColour']},&H000000FF,"
        f"{style['OutlineColour']},&H7F000000,0,0,0,0,100,100,0,0,1,{style['Outline']},0,"
        f"{style['Alignment']},40,40,{style['MarginV']},0","",
        "[Events]","Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    for s in segments:
        ass.append(f"Dialogue: 0,{seconds_to_ass(s.start)},{seconds_to_ass(s.end)},WeJaWi,,0,0,0,,{s.text}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ass))

        
def get_exact_font_name(font_family: str) -> str:
    """
    Get the exact font name that the system recognizes.
    This helps with ASS font matching.
    """
    # Create a QFont with the desired family
    font = QtGui.QFont(font_family)
    
    # Get font info to see what the system actually resolved
    font_info = QtGui.QFontInfo(font)
    actual_family = font_info.family()
    
    # If we got an exact match, use it
    if actual_family.lower() == font_family.lower():
        return actual_family
    
    # Otherwise, try to find the best match
    db = QtGui.QFontDatabase()
    families = db.families()
    
    # Look for exact match first
    for family in families:
        if family.lower() == font_family.lower():
            return family
    
    # Look for partial match
    for family in families:
        if font_family.lower() in family.lower():
            return family
    
    # Fall back to the resolved font
    return actual_family


def _ff_filter_escape_for_subtitles(path: str) -> str:
    """
    Windows-safe subtitles filter arg.
    Use a more compatible approach for FFmpeg subtitle filters.
    """
    # Convert to absolute path
    abs_path = os.path.abspath(path)
    
    # On Windows, convert backslashes to forward slashes for FFmpeg
    if os.name == "nt":
        abs_path = abs_path.replace("\\", "/")
    
    # For modern FFmpeg, try the simpler syntax first
    # Some versions are pickier about escaping
    escaped_path = abs_path
    
    # Only escape characters that absolutely need it for filter parsing
    escaped_path = escaped_path.replace(":", "\\:")  # Escape ALL colons for filter syntax
    escaped_path = escaped_path.replace(",", "\\,")   # Escape commas
    escaped_path = escaped_path.replace("'", "\\'")   # Escape single quotes
    
    # Try wrapping the entire path in quotes for better compatibility
    return f"subtitles='{escaped_path}'"

# -----------------------------------------------------------------------------
# Aspect-aware preview
# -----------------------------------------------------------------------------

FALLBACK_FONTS = ["Arial", "Noto Sans", "Segoe UI", "Helvetica", "DejaVu Sans",
                  "Liberation Sans", "Verdana", "Tahoma", "Sans Serif", "System"]

class VideoPreview(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(340)
        self._pix: Optional[QtGui.QPixmap] = None
        self._aspect: float = 16/9
        self._text: str = "This is a sample caption preview"
        self._font_family: str = QtGui.QFont().defaultFamily()
        self._font_pt: int = 42
        self._txt_color = QtGui.QColor("#FFFFFF")
        self._stroke_color = QtGui.QColor("#000000")
        self._stroke_px: int = 3
        self._bg = QtGui.QColor("#222")

    def set_snapshot(self, path: Optional[str]):
        self._pix = QtGui.QPixmap(path) if path and os.path.exists(path) else None
        self.update()

    def set_aspect_from_size(self, w: Optional[int], h: Optional[int]):
        if w and h and w > 0 and h > 0:
            self._aspect = float(w) / float(h)
        self.update()

    def set_style(self, text: str, font_family: str, font_pt: int,
                  txt_color: QtGui.QColor, stroke_color: QtGui.QColor, stroke_px: int):
        self._text = text
        self._font_family = font_family
        self._font_pt = font_pt
        self._txt_color = txt_color
        self._stroke_color = stroke_color
        self._stroke_px = stroke_px
        self.update()

    def _target_rect(self) -> QtCore.QRect:
        w, h = self.width(), self.height()
        if self._aspect <= 0:
            return QtCore.QRect(0, 0, w, h)
        if w / h > self._aspect:
            th = h; tw = int(th * self._aspect); tx = (w - tw) // 2; ty = 0
        else:
            tw = w; th = int(tw / self._aspect); tx = 0; ty = (h - th) // 2
        return QtCore.QRect(tx, ty, tw, th)

    def _best_font(self) -> QtGui.QFont:
        qf = QtGui.QFont(self._font_family, self._font_pt)
        info = QtGui.QFontInfo(qf)
        if not info.exactMatch():
            fams = set(QtGui.QFontDatabase().families())
            for fam in FALLBACK_FONTS:
                if fam in fams:
                    qf = QtGui.QFont(fam, self._font_pt)
                    break
        qf.setStyleStrategy(QtGui.QFont.PreferDefault)
        return qf

    def resizeEvent(self, e):
        self.update()
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), self._bg)
        tgt = self._target_rect()
        if self._pix:
            scaled = self._pix.scaled(tgt.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            px = tgt.x() + (tgt.width() - scaled.width()) // 2
            py = tgt.y() + (tgt.height() - scaled.height()) // 2
            p.drawPixmap(px, py, scaled)

            p.setFont(self._best_font())
            text_h = max(60, int(scaled.height() * 0.22))
            rect = QtCore.QRect(px, py + scaled.height() - text_h - 12, scaled.width(), text_h)

            if self._stroke_px > 0:
                for dx in range(-self._stroke_px, self._stroke_px + 1):
                    for dy in range(-self._stroke_px, self._stroke_px + 1):
                        if dx*dx + dy*dy > self._stroke_px*self._stroke_px:
                            continue
                        p.setPen(QtGui.QPen(self._stroke_color, 2))
                        p.drawText(rect.translated(dx, dy),
                                   QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter | QtCore.Qt.TextWordWrap,
                                   self._text)
            p.setPen(QtGui.QPen(self._txt_color, 1))
            p.drawText(rect,
                       QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter | QtCore.Qt.TextWordWrap,
                       self._text)
        else:
            p.setPen(QtGui.QPen(QtGui.QColor("#888")))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter,
                       "No preview yet.\nPick a video and press “Load / Snapshot”.")
        p.end()

# -----------------------------------------------------------------------------
# STT as a separate Python process (killable, GPU preferred)
# -----------------------------------------------------------------------------

STT_SCRIPT = r"""
import os, sys, json, platform, subprocess

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

IS_DARWIN = sys.platform == "darwin"
IS_APPLE_SILICON = IS_DARWIN and platform.machine() == "arm64"

def has_cudnn():
    # cuDNN doesn't ship on macOS at all.
    if IS_DARWIN:
        return False
    try:
        exe = "where" if os.name == "nt" else "which"
        name = "cudnn_ops64_9.dll" if os.name == "nt" else "libcudnn_ops.so.9"
        r = subprocess.run([exe, name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return r.returncode == 0
    except Exception:
        return False

def main():
    # args: audio_path lang_code model_name device_pref
    audio = sys.argv[1]
    lang  = sys.argv[2]
    model = sys.argv[3]        # tiny/base/small
    device_pref = sys.argv[4]  # auto|cuda|cpu|dml|mlx|mps

    # --- 0) MLX-Whisper on Apple Silicon (Metal + ANE). Fastest path on M-series. ---
    if IS_APPLE_SILICON and device_pref in ("auto", "mlx", "metal"):
        try:
            import mlx_whisper  # type: ignore
            repo = f"mlx-community/whisper-{model}"
            print(f"[stt] mlx-whisper init: repo={repo}", file=sys.stderr)
            kwargs = {"path_or_hf_repo": repo}
            if lang:
                kwargs["language"] = lang
            res = mlx_whisper.transcribe(audio, **kwargs)
            segs = [
                {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
                for s in (res.get("segments") or [])
            ]
            print(json.dumps(segs))
            return
        except Exception as e:
            print(f"[stt] mlx-whisper unavailable/failed: {e}", file=sys.stderr)

    # --- 1) faster-whisper (CUDA or CPU). On Mac this runs CPU only. ---
    try:
        from faster_whisper import WhisperModel  # type: ignore

        want_cuda = (device_pref in ("auto","cuda")) and has_cudnn()
        device = "cuda" if want_cuda else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        print(f"[stt] faster-whisper init: device={device}, model={model}", file=sys.stderr)
        m = WhisperModel(model, device=device, compute_type=compute_type)

        segs = []
        for s in m.transcribe(audio, language=lang)[0]:
            segs.append({"start": float(s.start), "end": float(s.end), "text": s.text.strip()})
        print(json.dumps(segs))
        return

    except Exception as e:
        print(f"[stt] faster-whisper unavailable/failed: {e}", file=sys.stderr)

    # --- 2) openai-whisper on DirectML (AMD/Intel, Windows only) ---
    if device_pref in ("auto","dml") and not IS_DARWIN:
        try:
            import torch_directml as dml   # type: ignore
            import whisper                 # type: ignore
            device = dml.device()
            print(f"[stt] openai-whisper on DirectML (AMD): model={model}", file=sys.stderr)
            m = whisper.load_model(model).to(device)
            res = m.transcribe(audio, language=lang, fp16=False)
            segs = [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()} for s in (res.get("segments") or [])]
            print(json.dumps(segs))
            return
        except Exception as e:
            print(f"[stt] DirectML path failed: {e}", file=sys.stderr)

    # --- 3) openai-whisper (CUDA, MPS on Mac, or CPU) ---
    try:
        import torch, whisper  # type: ignore
        use_cuda = torch.cuda.is_available() and device_pref in ("auto","cuda")
        use_mps = (
            IS_APPLE_SILICON
            and device_pref in ("auto", "mps", "mlx", "metal")
            and hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
            and not use_cuda
        )
        target = "cuda" if use_cuda else ("mps" if use_mps else "cpu")
        print(f"[stt] openai-whisper init: device={target}, model={model}", file=sys.stderr)
        m = whisper.load_model(model)
        if target != "cpu":
            m = m.to(target)
        res = m.transcribe(audio, language=lang, fp16=use_cuda)
        segs = [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()} for s in (res.get("segments") or [])]
        print(json.dumps(segs))
        return
    except Exception as e:
        print(f"[stt] openai-whisper not available: {e}", file=sys.stderr)

    # --- 4) Vosk (coarse offline fallback) ---
    try:
        import vosk  # type: ignore
        print("[stt] using Vosk (offline)\u2026", file=sys.stderr)
        # Expect host app to chunk text if timestamps are missing.
        print("[]")
        return
    except Exception as e:
        print(f"[stt] vosk not available: {e}", file=sys.stderr)

    print("[]")  # no segments

if __name__ == "__main__":
    main()
"""


class STTProcessRunner(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)   # List[Segment] or None
    logLine = QtCore.pyqtSignal(str)

    def __init__(self, audio_path: str, lang_code: str, model_name: str, device_pref: str, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.lang_code = lang_code
        self.model_name = model_name
        self.device_pref = device_pref  # "auto" | "cuda" | "cpu"
        self._proc = QtCore.QProcess(self)
        self._script_file = None

    def start(self):
        # Write the helper script to a temp file
        tf = tempfile.NamedTemporaryFile(delete=False, suffix="_stt_worker.py", mode="w", encoding="utf-8")
        tf.write(STT_SCRIPT)
        tf.flush()
        tf.close()
        self._script_file = tf.name

        # Run in a separate Python process
        py = sys.executable
        args = [py, self._script_file, self.audio_path, self.lang_code, self.model_name, self.device_pref]
        self._proc.setProcessChannelMode(QtCore.QProcess.SeparateChannels)
        self._proc.readyReadStandardError.connect(self._read_err)
        self._proc.readyReadStandardOutput.connect(self._read_out)
        self._proc.finished.connect(self._done)
        self._proc.start(args[0], args[1:])
        self.logLine.emit("STT process started…")

    def cancel(self):
        try:
            self._proc.kill()
        except Exception:
            pass

    def _read_err(self):
        msg = bytes(self._proc.readAllStandardError()).decode("utf-8", "ignore")
        if msg.strip():
            for line in msg.strip().splitlines():
                self.logLine.emit(line)

    def _read_out(self):
        pass  # we parse on finish (final JSON only)

    def _done(self, code, _status):
        try:
            raw = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "ignore").strip()
            import json
            data = json.loads(raw) if raw else []
            segs: List[Segment] = []
            if data:
                # Vosk fallback may return one long text with no timestamps -> chunk it
                if isinstance(data, list) and len(data) == 1 and (data[0].get("end", 0.0) == 0.0):
                    txt = data[0].get("text", "")
                    dur = get_video_duration(self.audio_path) or 60.0
                    segs = plain_text_to_segments(txt, dur)
                else:
                    for s in data:
                        segs.append(Segment(float(s["start"]), float(s["end"]), s["text"]))
        except Exception as e:
            self.logLine.emit(f"STT parse error: {e}")
            segs = None

        # cleanup temp script
        try:
            if self._script_file and os.path.exists(self._script_file):
                os.unlink(self._script_file)
        except Exception:
            pass

        self.finished.emit(segs)

# -----------------------------------------------------------------------------
# FFmpeg progress runner (non-blocking)
# -----------------------------------------------------------------------------

class FFmpegRunner(QtCore.QObject):
    progressChanged = QtCore.pyqtSignal(int)
    logLine = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(int)

    def __init__(self, cmd: List[str], duration_sec: float, parent=None):
        super().__init__(parent)
        self._cmd = cmd
        self._dur_ms = max(1.0, duration_sec) * 1000.0
        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(QtCore.QProcess.SeparateChannels)
        self._proc.readyReadStandardOutput.connect(self._read_out)
        self._proc.readyReadStandardError.connect(self._read_err)
        self._proc.finished.connect(self._on_finished)

    def start(self):
        self._proc.start(self._cmd[0], self._cmd[1:])

    def cancel(self):
        try:
            self.logLine.emit("Cancelling render…")
            self._proc.kill()
        except Exception:
            pass


    def _read_out(self):
        def emit_ms(ms_value: float):
            pct = min(95, int(10 + (ms_value / self._dur_ms) * 80))
            self.progressChanged.emit(pct)

        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "ignore")
        for line in data.splitlines():
            line = line.strip()
            if line.startswith("out_time_ms="):
                raw = line.split("=", 1)[1].strip()
                if raw != "N/A":
                    try:
                        emit_ms(float(raw))
                    except Exception:
                        pass
            elif line.startswith("out_time="):
                ts = line.split("=", 1)[1].strip()
                # Parse HH:MM:SS.micro
                if ts != "N/A" and ":" in ts:
                    try:
                        h, m, s = ts.split(":")
                        sec, _, frac = s.partition(".")
                        ms = (int(h)*3600 + int(m)*60 + int(sec)) * 1000.0
                        if frac.isdigit():
                            # microseconds → ms (keep it simple)
                            ms += float("0." + frac) * 1000.0
                        emit_ms(ms)
                    except Exception:
                        pass
            elif line.startswith("progress=") and "end" in line:
                self.progressChanged.emit(100)


    def _read_err(self):
        d = bytes(self._proc.readAllStandardError()).decode("utf-8", "ignore")
        if d.strip():
            self.logLine.emit(d.rstrip())

    def _on_finished(self, exitCode, _status):
        self.finished.emit(int(exitCode))

# ---- GPU encoder detection ----
_FFMPEG_ENCODERS_CACHE = None

def _ffmpeg_list_encoders() -> str:
    global _FFMPEG_ENCODERS_CACHE
    if _FFMPEG_ENCODERS_CACHE is not None:
        return _FFMPEG_ENCODERS_CACHE
    ffm = which_ffmpeg()
    if not ffm:
        return ""
    code, out, _ = _run([ffm, "-hide_banner", "-encoders"])
    _FFMPEG_ENCODERS_CACHE = out if code == 0 else ""
    return _FFMPEG_ENCODERS_CACHE or ""

def _has_encoder(name: str) -> bool:
    enc = _ffmpeg_list_encoders()
    # lines look like: " V..... h264_nvenc           NVIDIA NVENC H.264 encoder"
    return f" {name} " in enc or enc.strip().endswith(name)

def _pick_encoder_args(preference: str, log_cb) -> Tuple[list, str]:
    """
    preference: 'auto' | 'nvenc' | 'amf' | 'cpu'
    returns (ffmpeg_args, name_for_log)
    """
    # Try exactly what the user asked for
    if preference == "nvenc":
        if _has_encoder("h264_nvenc"):
            return (["-c:v", "h264_nvenc", "-preset", "p5"], "NVIDIA NVENC (h264_nvenc)")
        log_cb("NVENC not available in your FFmpeg build; falling back to CPU.")
        return (["-c:v", "libx264", "-preset", "medium"], "CPU x264")

    if preference == "amf":
        if _has_encoder("h264_amf"):
            return (["-c:v", "h264_amf"], "AMD AMF (h264_amf)")
        log_cb("AMF not available in your FFmpeg build; falling back to CPU.")
        return (["-c:v", "libx264", "-preset", "medium"], "CPU x264")

    if preference == "cpu":
        return (["-c:v", "libx264", "-preset", "medium"], "CPU x264")

    # Auto: prefer NVENC, then AMF, else CPU
    if _has_encoder("h264_nvenc"):
        return (["-c:v", "h264_nvenc", "-preset", "p5"], "NVIDIA NVENC (h264_nvenc)")
    if _has_encoder("h264_amf"):
        return (["-c:v", "h264_amf"], "AMD AMF (h264_amf)")
    return (["-c:v", "libx264", "-preset", "medium"], "CPU x264")



# -----------------------------------------------------------------------------
# Captions page
# -----------------------------------------------------------------------------

class CaptionsPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.video_path: Optional[str] = None
        self.preview_path: Optional[str] = None
        self.transcript_path: Optional[str] = None
        self.lang_code = "en"
        self._segments: Optional[List[Segment]] = None
        self._video_wh: Optional[Tuple[int, int]] = None
        self._stt_runner: Optional[STTProcessRunner] = None
        self._build_ui()

    def on_cancel_render(self):
        if hasattr(self, "_runner") and self._runner:
            self._runner.cancel()
            self.btn_cancel_render.setEnabled(False)


    def _apply_color_btn_style(self, btn: QtWidgets.QPushButton):
        hexcol = btn.property("color") or "#FFFFFF"
        q = QtGui.QColor(hexcol)
        # readable label color on any background
        txtcol = "#000000" if q.lightness() > 128 else "#FFFFFF"
        btn.setStyleSheet(
            f"border:1px solid #dfe1ee; border-radius:8px; padding:8px;"
            f"background:{hexcol}; color:{txtcol};"
        )

    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self); root.setContentsMargins(16,16,16,16); root.setSpacing(16)

        # Left: preview
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Captions", objectName="PageTitle"))
        self.preview = VideoPreview()
        left.addWidget(self.preview, 1)
        self.sample_text = QtWidgets.QLineEdit("This is a sample caption preview")
        self.sample_text.textChanged.connect(self.update_preview)
        left.addWidget(self.sample_text)
        


        # Right controls
        right = QtWidgets.QVBoxLayout()

        # 1) Video
        g1 = QtWidgets.QGroupBox("1) Choose video"); v1 = QtWidgets.QHBoxLayout(g1)
        self.video_edit = QtWidgets.QLineEdit()
        b_browse = QtWidgets.QPushButton("Browse…"); b_browse.clicked.connect(self.on_browse_video)
        b_snap = QtWidgets.QPushButton("Load / Snapshot"); b_snap.clicked.connect(self.on_snapshot)
        v1.addWidget(self.video_edit, 1); v1.addWidget(b_browse); v1.addWidget(b_snap)
        right.addWidget(g1)

        # 2) Style
        g2 = QtWidgets.QGroupBox("2) Style"); f2 = QtWidgets.QFormLayout(g2)
        self.font_combo = QtWidgets.QFontComboBox()
        try:
            self.font_combo.setFontFilters(QtWidgets.QFontComboBox.ScalableFonts)
            if hasattr(QtGui, "QFontDatabase") and hasattr(QtGui.QFontDatabase, "WritingSystem"):
                self.font_combo.setWritingSystem(QtGui.QFontDatabase.WritingSystem.Latin)
        except Exception:
            pass
        self.font_combo.currentFontChanged.connect(self.update_preview)
        f2.addRow("Font:", self.font_combo)

        self.size_spin = QtWidgets.QSpinBox(); self.size_spin.setRange(12, 96); self.size_spin.setValue(42)
        self.size_spin.valueChanged.connect(self.update_preview); f2.addRow("Caption size:", self.size_spin)

        self.color_btn = QtWidgets.QPushButton("Pick text color")
        self.color_btn.clicked.connect(lambda: self.pick_color(self.color_btn))
        self.color_btn.setProperty("color", "#FFFFFF"); f2.addRow("Text color:", self.color_btn)

        self.stroke_spin = QtWidgets.QSpinBox(); self.stroke_spin.setRange(0, 10); self.stroke_spin.setValue(5)
        self.stroke_spin.valueChanged.connect(self.update_preview); f2.addRow("Stroke size:", self.stroke_spin)

        self.stroke_btn = QtWidgets.QPushButton("Pick stroke color")
        self.stroke_btn.clicked.connect(lambda: self.pick_color(self.stroke_btn))
        self.stroke_btn.setProperty("color", "#000000"); f2.addRow("Stroke color:", self.stroke_btn)
        
        # After creating self.color_btn and self.stroke_btn:
        self._apply_color_btn_style(self.color_btn)
        self._apply_color_btn_style(self.stroke_btn)

        right.addWidget(g2)

        # 3) Transcript
        g3 = QtWidgets.QGroupBox("3) Transcript"); v3 = QtWidgets.QVBoxLayout(g3)
        row = QtWidgets.QHBoxLayout()
        self.transcript_edit = QtWidgets.QLineEdit()
        btn_tbrowse = QtWidgets.QPushButton("Load transcript (.srt/.vtt/.txt)…")
        btn_tbrowse.clicked.connect(self.on_browse_transcript)
        row.addWidget(self.transcript_edit, 1); row.addWidget(btn_tbrowse)
        v3.addLayout(row)
        self.textarea = QtWidgets.QPlainTextEdit(); self.textarea.setPlaceholderText("Or paste transcript text here…")
        v3.addWidget(self.textarea, 1)

        self.lang_combo = QtWidgets.QComboBox()
        for display, code in LANG_CHOICES: self.lang_combo.addItem(display, code)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)

        self.stt_model = QtWidgets.QComboBox()
        for label, name in STT_MODEL_CHOICES: self.stt_model.addItem(label, name)
        self.stt_model.setCurrentIndex(0)  # default: tiny

        self.stt_device = QtWidgets.QComboBox()
        for label, value in _stt_device_choices():
            self.stt_device.addItem(label, value)

        self.chk_autostt = QtWidgets.QCheckBox("Auto-transcribe if transcript not provided")
        self.chk_autostt.setChecked(True)
        btn_transcribe = QtWidgets.QPushButton("Transcribe Now")
        btn_transcribe.clicked.connect(self.on_transcribe_now)
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_cancel.clicked.connect(self.on_cancel_stt)

        # row2: dropdowns on one grid row, buttons on a second row
        opts_grid = QtWidgets.QGridLayout()
        opts_grid.setHorizontalSpacing(6)
        opts_grid.setVerticalSpacing(4)
        opts_grid.addWidget(QtWidgets.QLabel("Language:"), 0, 0)
        opts_grid.addWidget(self.lang_combo, 0, 1)
        opts_grid.addWidget(QtWidgets.QLabel("Model:"), 0, 2)
        opts_grid.addWidget(self.stt_model, 0, 3)
        opts_grid.addWidget(QtWidgets.QLabel("Device:"), 0, 4)
        opts_grid.addWidget(self.stt_device, 0, 5)
        opts_grid.setColumnStretch(1, 1)
        opts_grid.setColumnStretch(3, 1)
        opts_grid.setColumnStretch(5, 1)
        v3.addLayout(opts_grid)

        actions_row = QtWidgets.QHBoxLayout()
        actions_row.addWidget(self.chk_autostt)
        actions_row.addStretch(1)
        actions_row.addWidget(btn_transcribe)
        actions_row.addWidget(btn_cancel)
        v3.addLayout(actions_row)
        right.addWidget(g3, 1)

        # 4) Render
        g4 = QtWidgets.QGroupBox("4) Render"); f4 = QtWidgets.QFormLayout(g4)
        self.encoder_combo = QtWidgets.QComboBox()
        self.encoder_combo.addItem("Auto (GPU if available)", "auto")
        self.encoder_combo.addItem("NVIDIA NVENC (H.264)", "nvenc")
        self.encoder_combo.addItem("AMD AMF (H.264)", "amf")
        self.encoder_combo.addItem("CPU (libx264)", "cpu")
        f4.addRow("Video encoder:", self.encoder_combo)
        self.out_edit = QtWidgets.QLineEdit("output_captions.mp4")
        btn_out = QtWidgets.QPushButton("Pick…"); btn_out.clicked.connect(self.on_pick_output)
        row4 = QtWidgets.QHBoxLayout(); row4.addWidget(self.out_edit, 1); row4.addWidget(btn_out)
        wrap = QtWidgets.QWidget(); wrap.setLayout(row4); f4.addRow("Output file:", wrap)

        row_btns = QtWidgets.QHBoxLayout()
        self.btn_render = QtWidgets.QPushButton("Render captions → video")
        self.btn_cancel_render = QtWidgets.QPushButton("Cancel")
        self.btn_cancel_render.setEnabled(False)
        self.btn_render.clicked.connect(self.on_render)
        self.btn_cancel_render.clicked.connect(self.on_cancel_render)
        row_btns.addWidget(self.btn_render, 1)
        row_btns.addWidget(self.btn_cancel_render)
        wrap_btns = QtWidgets.QWidget(); wrap_btns.setLayout(row_btns)
        f4.addRow("", wrap_btns)

        self.pbar = QtWidgets.QProgressBar(); self.pbar.setRange(0, 100)
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000)
        f4.addRow("Progress:", self.pbar); f4.addRow("Log:", self.log)
        right.addWidget(g4)

        # Wrap layouts into widgets for the splitter
        leftW = QtWidgets.QWidget(); leftW.setLayout(left)
        rightW = QtWidgets.QWidget(); rightW.setLayout(right)

        # Scroll area for right panel so controls aren't clipped on small windows
        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        right_scroll.setWidget(rightW)

        # Sensible minimums so the preview never collapses
        self.preview.setMinimumWidth(320)
        leftW.setMinimumWidth(360)

        # Resizable split panes
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        split.addWidget(leftW)
        split.addWidget(right_scroll)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([400, 560])

        root.addWidget(split)


    # --- helpers --------------------------------------------------------------

    def log_msg(self, s: str):
        self.log.appendPlainText(s)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def pick_color(self, btn: QtWidgets.QPushButton):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(btn.property("color") or "#FFFFFF"), self, "Choose color")
        if col.isValid():
            btn.setProperty("color", col.name())
            self._apply_color_btn_style(btn)   # <— use our helper
            self.update_preview()


    def _on_lang_changed(self, idx: int):
        self.lang_code = self.lang_combo.itemData(idx) or "en"

    # --- video ----------------------------------------------------------------

    def on_browse_video(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose video", "", "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v)"
        )
        if path:
            self.video_edit.setText(path)

    def on_snapshot(self):
        if not self.video_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Video", "Pick a video first.")
            return
        if not which_ffmpeg() or not which_ffprobe():
            QtWidgets.QMessageBox.critical(self, "FFmpeg", "FFmpeg/FFprobe not found in PATH.")
            return
        path = self.video_edit.text().strip()
        self._video_wh = get_video_size(path)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg"); tmp.close()
        if not extract_first_frame(path, tmp.name):
            QtWidgets.QMessageBox.critical(self, "FFmpeg", "Failed to snapshot first frame.")
            try: os.unlink(tmp.name)
            except Exception: pass
            return
        self.video_path = path
        self.preview_path = tmp.name
        if self._video_wh:
            self.preview.set_aspect_from_size(*self._video_wh)
        self.preview.set_snapshot(self.preview_path)
        self.update_preview()

    # --- preview --------------------------------------------------------------

    def update_preview(self):
        qfont = self.font_combo.currentFont()
        self.preview.set_style(
            text=self.sample_text.text(),
            font_family=qfont.family(),
            font_pt=self.size_spin.value(),
            txt_color=QtGui.QColor(self.color_btn.property("color") or "#FFFFFF"),
            stroke_color=QtGui.QColor(self.stroke_btn.property("color") or "#000000"),
            stroke_px=self.stroke_spin.value(),
        )

    # --- STT controls ---------------------------------------------------------

    def _extract_audio_wav16k(self) -> Optional[str]:
        if not which_ffmpeg():
            QtWidgets.QMessageBox.critical(self, "FFmpeg", "FFmpeg not found in PATH.")
            return None
        outdir = tempfile.mkdtemp(prefix="wejawi_audio_")
        audio = os.path.join(outdir, "audio_16k.wav")
        self.log_msg("Extracting mono 16 kHz WAV for STT…")
        code, _, e = _run([
            which_ffmpeg(), "-y",
            "-i", self.video_edit.text().strip(),
            "-vn", "-ac", "1", "-ar", "16000",
            "-f", "wav",
            audio
        ])
        if code != 0:
            self.log_msg(e.strip())
            QtWidgets.QMessageBox.critical(self, "FFmpeg", "Failed to extract audio.")
            return None
        return audio

    def _start_stt_process(self, audio_path: str):
        model = self.stt_model.currentData() or "tiny"
        device = self.stt_device.currentData() or "auto"
        self._stt_runner = STTProcessRunner(audio_path, self.lang_code, model, device, self)
        self._stt_runner.logLine.connect(self.log_msg)
        def _done(segs):
            self._stt_runner = None
            if not segs:
                self.log_msg("Transcription failed or libraries not installed.")
                return
            # normalize (in case Vosk returned one long line)
            if isinstance(segs, list) and segs and segs[0].end == 0.0:
                dur = get_video_duration(self.video_edit.text().strip()) or 60.0
                segs = plain_text_to_segments(segs[0].text, dur)
            self._segments = segs
            self.textarea.setPlainText("\n".join(s.text for s in segs))
            self.pbar.setValue(35)
            self.log_msg(f"Transcribed {len(segs)} segments.")
        self._stt_runner.finished.connect(_done)
        self._stt_runner.start()
        self.pbar.setValue(5)

    def on_transcribe_now(self):
        if not self.video_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Transcribe", "Pick a video first.")
            return
        audio = self._extract_audio_wav16k()
        if not audio:
            return
        self._start_stt_process(audio)

    def on_cancel_stt(self):
        if self._stt_runner:
            self.log_msg("Cancelling STT…")
            self._stt_runner.cancel()
            self._stt_runner = None

    # --- render ---------------------------------------------------------------

    def on_render(self):
        if not self.video_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Render", "Pick a video first."); return
        if not which_ffmpeg():
            QtWidgets.QMessageBox.critical(self, "FFmpeg", "FFmpeg not found in PATH."); return

        out_path = self.out_edit.text().strip() or "output_captions.mp4"

        # Try to build segments from provided transcript
        segs: Optional[List[Segment]] = None
        if self.transcript_path and os.path.exists(self.transcript_path):
            with open(self.transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                data = f.read()
            if self.transcript_path.lower().endswith(".srt"):
                segs = parse_srt(data)
            elif self.transcript_path.lower().endswith(".vtt"):
                segs = parse_vtt(data)
            else:
                dur = get_video_duration(self.video_edit.text().strip()) or 60.0
                segs = plain_text_to_segments(data, dur)
        elif self.textarea.toPlainText().strip():
            dur = get_video_duration(self.video_edit.text().strip()) or 60.0
            segs = plain_text_to_segments(self.textarea.toPlainText(), dur)

        # If we still have no segments and auto-STT is checked, run STT first (then render)
        if not segs and self.chk_autostt.isChecked():
            audio = self._extract_audio_wav16k()
            if not audio:
                return
            self.btn_render.setEnabled(False)
            self.log_msg("Transcribing in background before render…")
            runner = STTProcessRunner(audio, self.lang_code,
                                      self.stt_model.currentData() or "tiny",
                                      self.stt_device.currentData() or "auto", self)
            runner.logLine.connect(self.log_msg)
            def _done(segs2):
                self.btn_render.setEnabled(True)
                if not segs2:
                    self.log_msg("Transcription failed or libraries not installed.")
                    return
                if isinstance(segs2, list) and segs2 and segs2[0].end == 0.0:
                    dur = get_video_duration(self.video_edit.text().strip()) or 60.0
                    segs_final = plain_text_to_segments(segs2[0].text, dur)
                else:
                    segs_final = segs2
                self.textarea.setPlainText("\n".join(s.text for s in segs_final))
                self._render_with_segments(segs_final, out_path)
            runner.finished.connect(_done)
            self._stt_runner = runner
            runner.start()
            self.pbar.setValue(5)
            return

        if not segs:
            QtWidgets.QMessageBox.warning(self, "Transcript",
                "Provide a transcript (SRT/VTT/TXT) or enable auto-transcribe.")
            return

        self._render_with_segments(segs, out_path)

    def _render_with_segments(self, segs: List[Segment], out_path: str):
        style = {
            "FontName": self.font_combo.currentFont().family(),
            "FontSize": self.size_spin.value(),
            "PrimaryColour": qcolor_to_ass(QtGui.QColor(self.color_btn.property("color") or "#FFFFFF"), 0x00),
            "OutlineColour": qcolor_to_ass(QtGui.QColor(self.stroke_btn.property("color") or "#000000"), 0x00),
            "Outline": max(0, self.stroke_spin.value()),
            "Alignment": ASS_ALIGN_BOTTOM_CENTER,
            "MarginV": 60,
        }

        tmpdir = tempfile.mkdtemp(prefix="wejawi_subs_")
        ass_path = os.path.join(tmpdir, "subs.ass")
        build_ass(style, segs, ass_path, self._video_wh)

        vf = _ff_filter_escape_for_subtitles(ass_path)
        enc_args, enc_name = _pick_encoder_args(self.encoder_combo.currentData() or "auto", self.log_msg)
        self.log_msg(f"Using encoder: {enc_name}")

        duration_sec = get_video_duration(self.video_edit.text().strip()) or 1.0
        cmd = [
            which_ffmpeg(), "-hide_banner", "-y",
            "-i", self.video_edit.text().strip(),
            "-vf", vf,
            *enc_args,
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-progress", "pipe:1", "-nostats",
            out_path
        ]

        self.pbar.setValue(10)
        self.btn_render.setEnabled(False)
        self.btn_cancel_render.setEnabled(True)
        self.log_msg("Starting FFmpeg…")

        self._runner = FFmpegRunner(cmd, duration_sec, self)
        self._runner.progressChanged.connect(self.pbar.setValue)
        self._runner.logLine.connect(self.log_msg)

        def _done(exit_code: int):
            self.btn_render.setEnabled(True)
            self.btn_cancel_render.setEnabled(False)
            if exit_code == 0:
                self.pbar.setValue(100)
                self.log_msg("Done.")
                QtWidgets.QMessageBox.information(self, "Render", f"Saved:\n{out_path}")
            else:
                # If user cancelled, exitCode is usually non-zero; make it clear.
                if self.pbar.value() < 100:
                    self.log_msg("Render cancelled.")
                else:
                    self.log_msg("FFmpeg failed. See log.")
                # No popup on cancel
        self._runner.finished.connect(_done)
        self._runner.start()

    # --- file pickers ---------------------------------------------------------

    def on_browse_transcript(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load transcript", "", "Subtitle/Transcript (*.srt *.vtt *.txt)"
        )
        if path:
            self.transcript_path = path
            self.transcript_edit.setText(path)

    def on_pick_output(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save output", "", "MP4 Video (*.mp4)")
        if path:
            if not path.lower().endswith(".mp4"):
                path += ".mp4"
            self.out_edit.setText(path)

def plain_text_to_segments(txt: str, total_sec: float) -> List[Segment]:
    words = re.findall(r"\S+", txt)
    if not words: return []
    wps = 3.0
    est_total = max(1.0, len(words) / wps)
    scale = total_sec / est_total
    chunks, i = [], 0
    while i < len(words):
        n = min(10, len(words)-i)
        chunks.append(" ".join(words[i:i+n])); i += n
    segs: List[Segment] = []
    t = 0.0
    for c in chunks:
        dur = max(1.6, len(c.split())/wps) * scale
        segs.append(Segment(t, min(total_sec, t+dur), c))
        t += dur
        if t >= total_sec: break
    for j in range(1, len(segs)):
        segs[j].start = max(segs[j].start, segs[j-1].end + 0.02)
    if segs:
        segs[-1].end = min(segs[-1].end, total_sec)
    return segs