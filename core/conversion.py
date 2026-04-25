
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

def find_ffmpeg() -> Optional[str]:
    for name in ("ffmpeg", "ffmpeg.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None

def find_ffprobe() -> Optional[str]:
    for name in ("ffprobe", "ffprobe.exe"):
        path = shutil.which(name)
        if path:
            return path
    return None

def ffprobe_duration(path: str) -> Optional[float]:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if proc.returncode == 0:
            return float(proc.stdout.strip())
    except Exception:
        pass
    return None

def _run_ffmpeg(cmd, cancel_checker=None) -> int:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        while True:
            if cancel_checker and cancel_checker():
                try:
                    proc.terminate()
                except Exception:
                    pass
                return -2
            line = proc.stderr.readline()
            if not line and proc.poll() is not None:
                break
        return proc.wait()
    finally:
        try:
            proc.kill()
        except Exception:
            pass

@dataclass
class VideoConvertOptions:
    target_ext: str = "mp4"
    v_bitrate_kbps: int = 3000
    a_bitrate_kbps: int = 128
    extra_ffmpeg: tuple = ()

@dataclass
class AudioConvertOptions:
    target_ext: str = "mp3"
    bitrate_kbps: int = 192

@dataclass
class ImageConvertOptions:
    target_ext: str = "jpg"
    jpeg_quality: int = 85

def convert_video(in_path: str, out_path: str, opts: VideoConvertOptions, cancel_checker=None):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "FFmpeg not found on PATH. Please install ffmpeg."
    ext = opts.target_ext.lower().strip(".")
    vcodec = "libx264"
    acodec = "aac"
    if ext in ("webm",):
        vcodec, acodec = "libvpx-vp9", "libopus"
    out = out_path
    if not out.lower().endswith(f".{ext}"):
        out += f".{ext}"
    cmd = [
        ffmpeg, "-y", "-loglevel", "error", "-stats",
        "-i", in_path,
        "-c:v", vcodec, "-b:v", f"{max(50, int(opts.v_bitrate_kbps))}k",
        "-c:a", acodec, "-b:a", f"{max(32, int(opts.a_bitrate_kbps))}k",
        *opts.extra_ffmpeg,
        out
    ]
    code = _run_ffmpeg(cmd, cancel_checker=cancel_checker)
    if code == 0:
        return True, out
    elif code == -2:
        try:
            if os.path.exists(out):
                os.remove(out)
        except Exception:
            pass
        return False, "Cancelled."
    else:
        return False, f"FFmpeg failed with exit code {code}."

def convert_audio(in_path: str, out_path: str, opts: AudioConvertOptions, cancel_checker=None):
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "FFmpeg not found on PATH. Please install ffmpeg."
    ext = opts.target_ext.lower().strip(".")
    acodec = "libmp3lame"
    if ext in ("aac", "m4a"):
        acodec = "aac"
    elif ext in ("wav",):
        acodec = "pcm_s16le"
    elif ext in ("flac",):
        acodec = "flac"
    elif ext in ("ogg", "opus"):
        acodec = "libopus"
    out = out_path
    if not out.lower().endswith(f".{ext}"):
        out += f".{ext}"
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-stats", "-i", in_path, "-vn", "-c:a", acodec]
    if ext not in ("wav", "flac"):
        cmd += ["-b:a", f"{max(8, int(opts.bitrate_kbps))}k"]
    cmd += [out]
    code = _run_ffmpeg(cmd, cancel_checker=cancel_checker)
    if code == 0:
        return True, out
    elif code == -2:
        try:
            if os.path.exists(out):
                os.remove(out)
        except Exception:
            pass
        return False, "Cancelled."
    else:
        return False, f"FFmpeg failed with exit code {code}."

def convert_image(in_path: str, out_path: str, opts: ImageConvertOptions):
    if not _HAS_PIL:
        return False, "Pillow (PIL) not installed. Install with: pip install pillow"
    ext = opts.target_ext.lower().strip(".")
    out = out_path
    if not out.lower().endswith(f".{ext}"):
        out += f".{ext}"
    try:
        im = Image.open(in_path)
        if im.mode in ("P", "RGBA") and ext in ("jpg", "jpeg"):
            from PIL import Image as _I
            bg = _I.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
            im = bg
        save_kwargs = {}
        if ext in ("jpg", "jpeg"):
            save_kwargs["quality"] = 85
            save_kwargs["optimize"] = True
        elif ext in ("webp",):
            save_kwargs["quality"] = 85
        im.save(out, format=("JPEG" if ext in ("jpg","jpeg") else ext.upper()), **save_kwargs)
        return True, out
    except Exception as e:
        return False, f"Image convert failed: {e}"

# ---- Estimation helpers ----

def estimate_audio_size_seconds(duration_s: float, fmt: str, bitrate_kbps: int = 192) -> int:
    fmt = fmt.lower()
    if fmt in ("mp3", "aac", "m4a", "ogg", "opus"):
        total_kbps = max(8, int(bitrate_kbps))
        return int(duration_s * (total_kbps * 1000) / 8)
    elif fmt in ("wav",):
        # default: s16le, 44.1kHz, stereo
        sample_rate = 44100
        channels = 2
        bits_per_sample = 16
        bytes_per_sec = sample_rate * channels * (bits_per_sample // 8)
        return int(duration_s * bytes_per_sec)
    elif fmt in ("flac",):
        # ~50% of WAV
        wav_size = estimate_audio_size_seconds(duration_s, "wav")
        return int(wav_size * 0.5)
    else:
        total_kbps = max(8, int(bitrate_kbps))
        return int(duration_s * (total_kbps * 1000) / 8)

def estimate_video_size_seconds(duration_s: float, v_bitrate_kbps: int, a_bitrate_kbps: int = 128) -> int:
    total_kbps = max(50, int(v_bitrate_kbps)) + max(0, int(a_bitrate_kbps))
    return int(duration_s * (total_kbps * 1000) / 8)

def rough_image_ratio(src_ext: str, dst_ext: str) -> float:
    s = src_ext.lower().strip(".")
    d = dst_ext.lower().strip(".")
    if s == d:
        return 1.0
    # Heuristic ratios based on common content
    table = {
        ("png","webp"): 0.45, ("png","jpg"): 0.5, ("png","jpeg"): 0.5,
        ("jpg","webp"): 0.75, ("jpeg","webp"): 0.75,
        ("jpg","png"): 1.4, ("jpeg","png"): 1.4,   # png often larger for photos
        ("bmp","png"): 0.6, ("bmp","jpg"): 0.5, ("bmp","webp"): 0.45,
        ("tiff","jpg"): 0.5, ("tiff","webp"): 0.45, ("tiff","png"): 0.8,
        ("webp","jpg"): 1.2, ("webp","png"): 1.6,
    }
    return table.get((s,d), 0.9)
