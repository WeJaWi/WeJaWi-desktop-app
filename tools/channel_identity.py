# tools/channel_identity.py
# Requirements:
#   pip install yt-dlp youtube-transcript-api
#
# What it does:
# - Ask for a YouTube channel URL (@handle, /channel/UC..., or /c/...)
# - Fetch top 10 videos (Latest by default; can sort by Most popular)
# - Pull transcripts via youtube-transcript-api (manual > auto, with language preference)
# - Show channel + video metadata, export transcripts to .txt and a summary JSON

from __future__ import annotations
import os, sys, time, json, glob
import re
import json
import threading
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from html import escape

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtCore import QUrl
from pathlib import Path

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)
CATS_FILE = os.path.join(DATA_DIR, "channel_categories.json")

def load_category_map() -> dict:
    try:
        with open(CATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_category_map(m: dict):
    try:
        with open(CATS_FILE, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
try:
    from core.jobs import JobManager
except Exception:
    from jobs import JobManager



# ---------- helpers ----------
def _sanitize_filename(name: str, keep: int = 120) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:keep]).rstrip(" ._-") or "video"

def _fmt_int(n: Optional[int]) -> str:
    if n is None:
        return "—"
    s = f"{n:,}".replace(",", " ")
    return s

def _fmt_duration(sec: Optional[int]) -> str:
    if sec is None:
        return "—"
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

def _fmt_date(ydl_upload_date: Optional[str]) -> str:
    # ydl upload_date is "YYYYMMDD"
    if not ydl_upload_date or len(ydl_upload_date) != 8:
        return "—"
    y, m, d = ydl_upload_date[:4], ydl_upload_date[4:6], ydl_upload_date[6:]
    return f"{y}-{m}-{d}"

# ---------- worker ----------
@dataclass
class VideoRow:
    id: str
    title: str
    url: str
    upload_date: Optional[str]
    duration: Optional[int]
    view_count: Optional[int]
    transcript_lang: str
    transcript_chars: int
    transcript_text: Optional[str]

@dataclass
class ChannelResult:
    channel_title: str
    channel_id: Optional[str]
    channel_url: str
    description: Optional[str]
    follower_count: Optional[int]
    videos: List[VideoRow]

class FetchThread(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)   # ChannelResult or str (error)
    progress = QtCore.pyqtSignal(int)
    logLine = QtCore.pyqtSignal(str)

    def __init__(self, channel_url: str, sort: str, prefer_lang: str):
        super().__init__(None)  # NO PARENT so we can move this to a QThread
        self.channel_url = channel_url.strip()
        self.sort = sort  # "latest" | "popular"
        self.prefer_lang = prefer_lang

    def _log(self, s: str):
        self.logLine.emit(s)

    def _get_transcript(self, vid: str):
        """
        Try youtube-transcript-api first (manual > generated, with language prefs).
        If that fails, fall back to yt-dlp's subtitles/automatic_captions and fetch
        the best .vtt URL, converting it to plain text.
        Returns: (label, char_count, text_or_None) where label is "manual:en" / "auto:en" / "none".
        """
        from typing import Tuple, Optional
        import re

        # 1) primary path: youtube-transcript-api
        try:
            from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
            pref = self.prefer_lang or "auto"
            listed = YouTubeTranscriptApi.list_transcripts(vid)

            if pref and pref != "auto":
                langs_pref = [pref, f"{pref}-US", f"{pref}-GB"]
            else:
                # sensible default if user left "auto"
                langs_pref = ["en","en-US","en-GB"]

            try_order = [("manual", langs_pref), ("generated", langs_pref), ("any", [])]
            transcript = None
            label = "—"
            for kind, langs in try_order:
                try:
                    if kind == "manual":
                        transcript = listed.find_manually_created(langs)
                    elif kind == "generated":
                        transcript = listed.find_generated(langs)
                    else:
                        for t in listed:
                            transcript = t; break
                    if transcript:
                        label = f"{'auto' if transcript.is_generated else 'manual'}:{transcript.language_code}"
                        break
                except Exception:
                    pass

            if transcript:
                segs = transcript.fetch()
                text = " ".join(s.get("text", "").replace("\n", " ").strip() for s in segs if s.get("text"))
                return (label, len(text), text if text else None)
        except (NameError, ImportError):
            # library not installed; skip to fallback
            pass
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
            # fall through to fallback
            pass
        except Exception as e:
            self._log(f"[transcript-api] {vid}: {e}")

        # 2) fallback: yt-dlp captions (manual first, then auto)
        try:
            from yt_dlp import YoutubeDL

            _YT_HEADERS = {
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"),
                "Accept-Language": "en-US,en;q=0.9",
            }
            cookiefile = os.environ.get("WEJAWI_YT_COOKIES", "").strip()
            base_opts = {
                "quiet": True, "skip_download": True, "noplaylist": True,
                "socket_timeout": 20, "retries": 3, "http_headers": _YT_HEADERS,
                "check_formats": False, "ignore_no_formats_error": True,
                "extractor_args": {"youtube": {"player_client": ["android","web"]}},
            }
            if cookiefile:
                base_opts["cookiefile"] = cookiefile

            # fetch metadata (includes subtitles maps)
            with YoutubeDL(base_opts) as ydl:
                v = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)

            prefer = []
            if self.prefer_lang and self.prefer_lang != "auto":
                prefer = [self.prefer_lang, f"{self.prefer_lang}-US", f"{self.prefer_lang}-GB"]
            else:
                prefer = ["en","en-US","en-GB"]

            def pick_url(caps: dict) -> Tuple[Optional[str], Optional[str]]:
                # returns (lang_code, url)
                # prioritize preferred languages, prefer .vtt ext
                for code in prefer + [k for k in (caps or {}).keys() if k not in prefer]:
                    lst = (caps or {}).get(code) or []
                    if not lst: continue
                    # pick vtt first
                    lst_sorted = sorted(lst, key=lambda x: (x.get("ext") != "vtt"))
                    url = lst_sorted[0].get("url")
                    if url: return code, url
                return None, None

            subs = v.get("subtitles") or {}
            autos = v.get("automatic_captions") or {}

            lang_code, url = pick_url(subs)
            label_prefix = "manual" if url else None
            if not url:
                lang_code, url = pick_url(autos)
                label_prefix = "auto" if url else None
            if not url:
                return ("none", 0, None)

            # download the .vtt and flatten it
            try:
                import requests
                r = requests.get(url, headers=_YT_HEADERS, timeout=25)
                r.raise_for_status()
                vtt = r.text
            except Exception as e:
                self._log(f"[subs-fallback] download {vid}: {e}")
                return ("none", 0, None)

            # very lightweight VTT -> text
            lines = []
            for line in vtt.splitlines():
                L = line.strip()
                if not L: continue
                if L.startswith(("WEBVTT","Kind:","Language:","NOTE","STYLE","REGION")): continue
                if "-->" in L: continue               # timestamp lines
                if re.match(r"^\d+$", L): continue    # numeric cues
                lines.append(L)
            text = " ".join(lines)
            return (f"{label_prefix}:{lang_code}", len(text), text if text else None)

        except Exception as e:
            self._log(f"[subs-fallback] {vid}: {e}")
        return ("none", 0, None)


    # >>> THIS is the method your QThread starts <<<
    def run(self):
        from yt_dlp import YoutubeDL
        import re

        def norm_base(u: str) -> str:
            u = u.strip().rstrip("/")
            return re.sub(r"/(featured|videos|shorts|streams|playlists).*$", "", u, flags=re.I)

        def list_url_for_sort(base: str, sort: str) -> str:
            code = "p" if sort == "popular" else "dd"  # p=popular, dd=newest
            return f"{base}/videos?view=0&sort={code}"

        def extract_ids_from_entries(entries: list) -> list:
            out = []
            for e in entries or []:
                u = (e.get("url") or "").strip()
                vid = None
                m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", u)
                if m:
                    vid = m.group(1)
                if not vid and "/shorts/" in u:
                    tail = u.rstrip("/").split("/")[-1]
                    if re.fullmatch(r"[A-Za-z0-9_-]{11}", tail):
                        vid = tail
                if not vid:
                    cand = e.get("id") or ""
                    if re.fullmatch(r"[A-Za-z0-9_-]{11}", cand):
                        vid = cand
                if vid:
                    out.append(vid)
            # de-dup keep order
            seen = set(); ordered = []
            for v in out:
                if v not in seen:
                    seen.add(v); ordered.append(v)
            return ordered

        # Common headers to avoid weird blocking
        _YT_HEADERS = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        def _yt_base_opts():
            # Optional cookies: set WEJAWI_YT_COOKIES to a Netscape-format cookie file path
            cookiefile = os.environ.get("WEJAWI_YT_COOKIES", "").strip()
            opts = {
                "quiet": True,
                "skip_download": True,
                "noplaylist": True,
                "socket_timeout": 20,
                "retries": 3,
                "http_headers": _YT_HEADERS,
                # Avoid SABR formats and streaming checks; we only want metadata
                "check_formats": False,               # don't HEAD-ping formats
                "ignore_no_formats_error": True,      # if no formats, still return metadata
                "extractor_args": {
                    "youtube": {
                        # Prefer Android player client to avoid SABR throttling
                        "player_client": ["android", "web"],
                    }
                },
            }
            if cookiefile:
                opts["cookiefile"] = cookiefile
            return opts

        ydl_flat = {
            **_yt_base_opts(),
            "extract_flat": True,     # fast listing
            "playlistend": 120,
        }
        ydl_full = {
            **_yt_base_opts(),
            # rich per-video details (but still no downloads)
}

        base = norm_base(self.channel_url)
        list_url = list_url_for_sort(base, self.sort)

        # 1) tab list
        try:
            with YoutubeDL(ydl_flat) as ydl:
                info = ydl.extract_info(list_url, download=False)
        except Exception as e:
            self.finished.emit(f"Failed to read channel videos list:\n{e}\nTip: try a plain channel URL like https://www.youtube.com/@handle or /channel/UC…")
            return

        channel_title = info.get("channel") or info.get("title") or info.get("uploader") or "Channel"
        channel_id = info.get("channel_id") or info.get("uploader_id")
        channel_url = info.get("channel_url") or base
        description = info.get("description")
        follower_count = info.get("channel_follower_count") or info.get("uploader_subscriber_count")

        raw_entries = info.get("entries") or []
        video_ids = extract_ids_from_entries(raw_entries)

        # 2) fallback to uploads playlist
        if len(video_ids) < 10:
            try:
                with YoutubeDL(ydl_full) as ydl:
                    ch = ydl.extract_info(base, download=False)
                cid = ch.get("channel_id") or ch.get("uploader_id")
                if cid and cid.startswith("UC"):
                    uploads_pl = "UU" + cid[2:]
                    pl_url = f"https://www.youtube.com/playlist?list={uploads_pl}"
                    self._log(f"Low video count from tab. Falling back to uploads playlist: {uploads_pl}")
                    with YoutubeDL(ydl_flat) as ydl:
                        pli = ydl.extract_info(pl_url, download=False)
                    video_ids += extract_ids_from_entries(pli.get("entries") or [])
                    video_ids = list(dict.fromkeys(video_ids))
            except Exception as e:
                self._log(f"[fallback uploads] {e}")

        if not video_ids:
            self.finished.emit("Could not list videos for this channel. Try adding '/videos' to the URL or check your network.")
            return

        self._log(f"Found {len(video_ids)} candidate videos. Fetching details…")
        self.progress.emit(5)

        vids_meta = []
        fetch_n = min(60, len(video_ids))
        try:
            with YoutubeDL(ydl_full) as ydl:
                for idx, vid in enumerate(video_ids[:fetch_n], 1):
                    url = f"https://www.youtube.com/watch?v={vid}"
                    v = None
                    try:
                        # First attempt: rich metadata (may 403 under SABR)
                        v = ydl.extract_info(url, download=False)
                    except Exception as e:
                        self._log(f"[video rich] {vid}: {e}  -> falling back to flat")
                        # Fallback: flat extract (title/id/date often available)
                        try:
                            with YoutubeDL({**ydl_flat}) as y2:
                                vflat = y2.extract_info(url, download=False)
                                if isinstance(vflat, dict):
                                    # Normalize a minimal dict so downstream doesn’t crash
                                    v = {
                                        "id": vflat.get("id") or vid,
                                        "title": vflat.get("title") or vid,
                                        "webpage_url": url,
                                        "upload_date": vflat.get("upload_date"),
                                        "duration": vflat.get("duration"),  # may be None in flat
                                        "view_count": vflat.get("view_count"),  # may be None
                                    }
                        except Exception as e2:
                            self._log(f"[video flat] {vid}: {e2}")

                    if v:
                        vids_meta.append(v)

                    if idx % 4 == 0:
                        self.progress.emit(5 + int(20 * idx / max(1, fetch_n)))
        except Exception as e:
            self._log(f"[warn] detail fetch failed: {e}")


        def key_latest(v):
            d = v.get("upload_date")
            return int(d) if d and str(d).isdigit() else -1
        def key_pop(v):
            c = v.get("view_count")
            return int(c) if isinstance(c, int) else -1

        vids_meta.sort(key=key_pop if self.sort == "popular" else key_latest, reverse=True)
        vids_meta = vids_meta[:10]

        out_rows = []
        for i, v in enumerate(vids_meta, 1):
            vid = v.get("id")
            title = v.get("title") or vid or "Untitled"
            url = v.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
            upload_date = v.get("upload_date")
            duration = v.get("duration")
            view_count = v.get("view_count")
            lang, chars, text = self._get_transcript(vid)
            out_rows.append(
                VideoRow(
                    id=vid,
                    title=title,
                    url=url,
                    upload_date=upload_date,
                    duration=duration,
                    view_count=view_count,
                    transcript_lang=lang,
                    transcript_chars=chars,
                    transcript_text=text,
                )
            )
            self.progress.emit(30 + int(70 * i / max(1, len(vids_meta))))

        self.progress.emit(100)
        self.finished.emit(
            ChannelResult(
                channel_title=channel_title,
                channel_id=channel_id,
                channel_url=channel_url,
                description=description,
                follower_count=follower_count,
                videos=out_rows,
            )
        )


# ---------- UI page ----------
class ChannelIdentityPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: Optional[ChannelResult] = None
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QtWidgets.QLabel("🔎 Channel Identity")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        # Row: URL + Sort + Lang + Go
        row = QtWidgets.QHBoxLayout()
        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setPlaceholderText("Paste a YouTube channel URL, e.g. https://www.youtube.com/@yourhandle")
        self.sort_combo = QtWidgets.QComboBox()
        self.sort_combo.addItem("Latest", "latest")
        self.sort_combo.addItem("Most popular", "popular")
        self.lang_combo = QtWidgets.QComboBox()
        self.lang_combo.addItem("Auto / best", "")  # empty means choose best available
        for code, label in [("en","English"), ("de","German"), ("pl","Polish"), ("sv","Swedish"),
                            ("no","Norwegian"), ("hu","Hungarian"), ("es","Spanish")]:
            self.lang_combo.addItem(f"{label} ({code})", code)
        self.go_btn = QtWidgets.QPushButton("Fetch")
        self.go_btn.clicked.connect(self.on_fetch)

        row.addWidget(QtWidgets.QLabel("Channel URL:"))
        row.addWidget(self.url_edit, 1)
        row.addWidget(QtWidgets.QLabel("Sort:"))
        row.addWidget(self.sort_combo)
        row.addWidget(QtWidgets.QLabel("Transcript lang:"))
        row.addWidget(self.lang_combo)
        row.addWidget(self.go_btn)
        root.addLayout(row)

                # Row: Category + BG Output folder + buttons
        row2 = QtWidgets.QHBoxLayout()
        self.category_edit = QtWidgets.QLineEdit()
        self.category_edit.setPlaceholderText("Category (e.g., Sleep, Tech) — you set it manually")
        # preload known categories for convenience
        cats = sorted(set(load_category_map().values()))
        if cats:
            completer = QtWidgets.QCompleter(cats); completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
            self.category_edit.setCompleter(completer)

        self.bg_out_dir_edit = QtWidgets.QLineEdit()
        self.bg_out_dir_edit.setPlaceholderText("Pick output folder for background runs / loading")
        self.btn_pick_bg_out = QtWidgets.QPushButton("Browse…")
        self.btn_pick_bg_out.clicked.connect(self._pick_bg_out)

        self.btn_load_folder = QtWidgets.QPushButton("Load from folder…")
        self.btn_load_folder.clicked.connect(self.on_load_folder)

        row2.addWidget(QtWidgets.QLabel("Category:"))
        row2.addWidget(self.category_edit, 1)
        row2.addWidget(QtWidgets.QLabel("Output folder:"))
        row2.addWidget(self.bg_out_dir_edit, 2)
        row2.addWidget(self.btn_pick_bg_out)
        row2.addWidget(self.btn_load_folder)
        root.addLayout(row2)

        # ----- Details panel -----
       

        # Title (clickable)
        self.det_title = QtWidgets.QLabel("—")
        self.det_title.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        self.det_title.setOpenExternalLinks(True)

        # Sub meta (published • duration • views) and transcript meta
        self.det_sub = QtWidgets.QLabel("—")
        self.det_meta = QtWidgets.QLabel("—")
        self.det_sub.setStyleSheet("color:#ccc;")
        self.det_meta.setStyleSheet("color:#ccc;")


        # Actions
        act = QtWidgets.QHBoxLayout()
        self.btn_open_video = QtWidgets.QPushButton("Open Video")
        self.btn_copy_url = QtWidgets.QPushButton("Copy URL")
        self.btn_open_transcript = QtWidgets.QPushButton("Open Transcript")
        self.btn_open_folder = QtWidgets.QPushButton("Open Folder")
        for b in (self.btn_open_video, self.btn_copy_url, self.btn_open_transcript, self.btn_open_folder):
            act.addWidget(b)
        act.addStretch(1)
        

        # Transcript preview (only once!)

        self.transcript_view = QtWidgets.QPlainTextEdit()
        self.transcript_view.setReadOnly(True)
        self.transcript_view.setPlaceholderText("Select a video row to view its transcript…")


        # Wire actions
        self.btn_open_video.clicked.connect(lambda: self._open_url(getattr(self, "_current_video_url", "")))
        self.btn_copy_url.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(getattr(self, "_current_video_url", "")))
        self.btn_open_transcript.clicked.connect(lambda: self._open_path(getattr(self, "_current_transcript_path", "")))
        self.btn_open_folder.clicked.connect(lambda: self._open_folder(self.bg_out_dir_edit.text().strip()))


        # Splitter: table (left) + channel info + export (right)
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        # Left table
        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Title", "Video ID", "Published", "Duration", "Views", "Transcript", "Chars"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        lv.addWidget(self.table, 1)
        self.table.itemSelectionChanged.connect(self._on_row_selected)

        # Log + progress
        self.pbar = QtWidgets.QProgressBar()
        self.pbar.setRange(0, 100)
        lv.addWidget(self.pbar)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        lv.addWidget(self.log, 1)

        split.addWidget(left)

        # Right panel
        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        self.meta_title = QtWidgets.QLabel("—")
        self.meta_title.setStyleSheet("font-weight: 700; font-size: 18px; color: white;")
        self.meta_desc = QtWidgets.QPlainTextEdit()
        self.meta_desc.setReadOnly(True)
        self.meta_desc.setPlaceholderText("Channel description…")
        self.meta_stats = QtWidgets.QLabel("—")
        self.meta_stats.setStyleSheet("color: #ddd;")

        rv.addWidget(QtWidgets.QLabel("Channel", objectName="PageTitle"))
        rv.addWidget(self.meta_title)
        rv.addWidget(self.meta_stats)
        rv.addWidget(self.meta_desc, 1)
                # Transcript preview
        rv.addWidget(self.meta_desc, 1)
        rv.addLayout(act)
        rv.addWidget(self.transcript_view, 2)
        rv.addWidget(QtWidgets.QLabel("Transcript preview"))

        # Export group
        ex = QtWidgets.QGroupBox("Export transcripts")
        ef = QtWidgets.QFormLayout(ex)
        self.out_dir = QtWidgets.QLineEdit()
        bpick = QtWidgets.QPushButton("Browse…")
        bpick.clicked.connect(self._pick_dir)
        rowd = QtWidgets.QHBoxLayout(); rowd.addWidget(self.out_dir, 1); rowd.addWidget(bpick)
        wrap = QtWidgets.QWidget(); wrap.setLayout(rowd)
        ef.addRow("Output folder:", wrap)

        self.chk_one_file = QtWidgets.QCheckBox("One .txt per video")
        self.chk_one_file.setChecked(True)
        self.chk_json = QtWidgets.QCheckBox("Also write summary JSON")
        self.chk_json.setChecked(True)
        self.btn_export = QtWidgets.QPushButton("Export")
        self.btn_export.clicked.connect(self.on_export)
        ef.addRow(self.chk_one_file)
        ef.addRow(self.chk_json)
        ef.addRow(self.btn_export)
        rv.addWidget(ex)

        bgrow = QtWidgets.QHBoxLayout()
        self.chk_bg = QtWidgets.QCheckBox("Run in background (Jobs Center)")
        self.btn_bg = QtWidgets.QPushButton("Start Background")
        self.btn_bg.clicked.connect(self.on_run_bg)
        bgrow.addWidget(self.chk_bg)
        bgrow.addStretch(1)
        bgrow.addWidget(self.btn_bg)
        root.addLayout(bgrow)


        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

     



    def _pick_bg_out(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if d: self.bg_out_dir_edit.setText(d)

    def on_load_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder with result_*.json")
        if not folder: return
        self.bg_out_dir_edit.setText(folder)
        files = sorted(glob.glob(os.path.join(folder, "result_*.json")))
        if not files:
            QtWidgets.QMessageBox.information(self, "No results", "No result_*.json files in this folder.")
            return
        self._load_json_into_ui(files[-1])

    def _load_json_into_ui(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load failed", str(e)); return

        vids = []
        for v in data.get("videos", []):
            vids.append(VideoRow(
                id=v.get("id",""),
                title=v.get("title",""),
                url=v.get("url",""),
                upload_date=v.get("upload_date"),
                duration=v.get("duration"),
                view_count=v.get("view_count"),
                transcript_lang=v.get("transcript_lang",""),
                transcript_chars=v.get("transcript_chars") or 0,
                transcript_text=v.get("transcript_text")
            ))
        self._result = ChannelResult(
            channel_title=data.get("channel",{}).get("title") or "Channel",
            channel_id=data.get("channel",{}).get("id"),
            channel_url=data.get("channel",{}).get("url") or "",
            description=data.get("channel",{}).get("description"),
            follower_count=data.get("channel",{}).get("subscribers"),
            videos=vids
        )
        self._fill_ui(self._result)
        cat = data.get("channel",{}).get("category") or ""
        if cat: self.category_edit.setText(cat)

    def on_run_bg(self):
        url = self.url_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.information(self, "Channel URL", "Paste a YouTube channel URL."); return
        sort = self.sort_combo.currentData() or "latest"
        lang = self.lang_combo.currentData() or ""
        category = self.category_edit.text().strip()

        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "channel_identity_cli.py"))
        if not os.path.isfile(script):
            QtWidgets.QMessageBox.critical(self, "Missing worker", f"Not found:\n{script}"); return

        out_dir = self.bg_out_dir_edit.text().strip()
        if not out_dir:
            try:
                out_dir = os.path.join(JobManager.instance().logs_root(), "channel_identity")
            except Exception:
                out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "channel_identity"))
        os.makedirs(out_dir, exist_ok=True)

        cmd = [sys.executable, "-u", script, "--url", url, "--sort", sort, "--lang", lang, "--out-dir", out_dir]
        if category: cmd += ["--category", category]

        meta = {"tool":"channel_identity","channel_url":url,"sort":sort,"lang":lang,"category":category,"out_dir":out_dir}
        jm = JobManager.instance()
        try:
            job_id = jm.start_process_job(cmd, meta=meta, tag="channel_identity", duration_s=100.0) \
                    if hasattr(jm, "start_process_job") else \
                    jm.start_ffmpeg_job(cmd, duration_s=100.0, meta=meta, tag="channel_identity")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Start failed", str(e)); return

        QtWidgets.QMessageBox.information(self, "Background job started",
            f"Job ID: {job_id}\nOutput folder:\n{out_dir}\nOpen Jobs Center to watch progress.")

    def _on_row_selected(self):
        self._current_video_url = ""
        self._current_transcript_path = ""
        self.transcript_view.setPlainText("")
        if not self._result: 
            self._update_details(None); 
            return
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._update_details(None); 
            return
        v = self._result.videos[rows[0].row()]
        # transcript: prefer in-memory; else try file in chosen output folder
        text = v.transcript_text
        tpath = None
        if not text:
            folder = self.bg_out_dir_edit.text().strip()
            if folder:
                tdir = os.path.join(folder, "transcripts")
                if os.path.isdir(tdir):
                    for name in os.listdir(tdir):
                        if name.endswith(".txt") and f"[{v.id}]" in name:
                            tpath = os.path.join(tdir, name)
                            try:
                                with open(tpath, "r", encoding="utf-8") as f:
                                    text = f.read()
                            except Exception:
                                pass
                            break
        self._current_video_url = v.url
        self._current_transcript_path = tpath or ""
        self.transcript_view.setPlainText(text or "— no transcript —")
        self._update_details(v, transcript_len=len(text or ""), transcript_path=tpath)

    def _update_details(self, v: Optional[VideoRow], transcript_len: int = 0, transcript_path: Optional[str] = None):
        if not v:
            self.det_title.setText("—")
            self.det_sub.setText("—")
            self.det_meta.setText("—")
            for b in (self.btn_open_video, self.btn_copy_url, self.btn_open_transcript, self.btn_open_folder):
                b.setEnabled(False)
            return
        # clickable title linking to video
        safe_title = QtWidgets.QLabel().text()  # noop to get HTML escape; we’ll just use Qt to render link
        self.det_title.setText(f'<a href="{escape(v.url or "")}">{escape(v.title or "—")}</a>')

        # published • duration • views
        pub = _fmt_date(v.upload_date)
        dur = _fmt_duration(v.duration)
        views = _fmt_int(v.view_count)
        self.det_sub.setText(f"Published: {pub}   •   Duration: {dur}   •   Views: {views}")
        # transcript meta
        tlang = v.transcript_lang or "—"
        tchars = v.transcript_chars or transcript_len or 0
        self.det_meta.setText(f"Transcript: {tlang}   •   {tchars} chars" + (f"   •   file: {os.path.basename(transcript_path)}" if transcript_path else ""))
        # enable actions
        
        self.btn_open_video.setEnabled(bool(v.url))
        self.btn_copy_url.setEnabled(bool(v.url))
        self.btn_open_transcript.setEnabled(bool(transcript_path))
        self.btn_open_folder.setEnabled(bool(self.bg_out_dir_edit.text().strip()))

    def _open_url(self, url: str):
        if not url: return
        QDesktopServices.openUrl(QUrl(url))

    def _open_path(self, path: str):
        if not path or not os.path.exists(path): return
        if os.name == "nt":
            os.startfile(path)  # type: ignore
        else:
            QtCore.QProcess.startDetached("xdg-open", [path])

    def _open_folder(self, folder: str):
        if not folder or not os.path.isdir(folder): return
        if os.name == "nt":
            os.startfile(folder)  # type: ignore
        else:
            QtCore.QProcess.startDetached("xdg-open", [folder])


    # ---- UI actions ----
    def _append_log(self, s: str):
        self.log.appendPlainText(s)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _pick_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if d:
            self.out_dir.setText(d)

    def on_fetch(self):
        url = self.url_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.information(self, "Channel URL", "Paste a YouTube channel URL.")
            return
        sort = self.sort_combo.currentData() or "latest"
        lang = self.lang_combo.currentData() or ""
        self.table.setRowCount(0)
        self.meta_title.setText("—")
        self.meta_desc.setPlainText("")
        self.meta_stats.setText("—")
        self._append_log(f"Fetching: {url}  (sort={sort}, lang={lang or 'auto'})")
        self.go_btn.setEnabled(False)
        self.pbar.setValue(0)

        # Thread + worker
        self._thread = threading.Thread(target=self._run_worker, args=(url, sort, lang), daemon=True)
        self._thread.start()

    def _run_worker(self, url: str, sort: str, lang: str):
        # Bridge worker -> UI via signals using a QObject living on main thread
        QtCore.QMetaObject.invokeMethod(self, "_start_worker", QtCore.Qt.QueuedConnection,
                                        QtCore.Q_ARG(str, url), QtCore.Q_ARG(str, sort), QtCore.Q_ARG(str, lang))

    @QtCore.pyqtSlot(str, str, str)
    def _start_worker(self, url: str, sort: str, lang: str):
        # Worker must be parentless to move threads
        self._worker = FetchThread(url, sort, lang)

        # Thread (parented to the page so it dies with the page)
        self._qthread = QtCore.QThread(self)

        # Wire signals
        self._worker.logLine.connect(self._append_log)
        self._worker.progress.connect(self.pbar.setValue)

        def _done(res):
            try:
                self.go_btn.setEnabled(True)
                if isinstance(res, str):
                    QtWidgets.QMessageBox.critical(self, "Error", res)
                else:
                    self._result = res
                    self._fill_ui(res)
            finally:
                # Clean shutdown
                self._worker.moveToThread(QtWidgets.QApplication.instance().thread())  # optional
                self._qthread.quit()
                self._qthread.wait()
                self._worker.deleteLater()
                self._qthread.deleteLater()

        self._worker.finished.connect(_done)

    # Move and start
        self._worker.moveToThread(self._qthread)
        self._qthread.started.connect(self._worker.run)
        self._qthread.start()

    


    def on_run_bg(self):
        url = self.url_edit.text().strip()
        if not url:
            QtWidgets.QMessageBox.information(self, "Channel URL", "Paste a YouTube channel URL.")
            return
        sort = self.sort_combo.currentData() or "latest"
        lang = self.lang_combo.currentData() or ""
        category = self.category_edit.text().strip()

        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "channel_identity_cli.py"))
        if not os.path.isfile(script):
            QtWidgets.QMessageBox.critical(self, "Missing worker", f"Not found:\n{script}")
            return

        out_dir = self.bg_out_dir_edit.text().strip()
        if not out_dir:
            # default to Jobs logs root if not chosen
            jm = JobManager.instance()
            try:
                out_dir = os.path.join(jm.logs_root(), "channel_identity")
            except Exception:
                out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "channel_identity"))
        os.makedirs(out_dir, exist_ok=True)

        cmd = [sys.executable, "-u", script,
            "--url", url, "--sort", sort, "--lang", lang,
            "--out-dir", out_dir]
        if category:
            cmd += ["--category", category]

        meta = {"tool": "channel_identity", "channel_url": url, "sort": sort, "lang": lang, "category": category, "out_dir": out_dir}
        jm = JobManager.instance()
        try:
            job_id = jm.start_process_job(cmd, meta=meta, tag="channel_identity", duration_s=100.0) \
                    if hasattr(jm, "start_process_job") \
                    else jm.start_ffmpeg_job(cmd, duration_s=100.0, meta=meta, tag="channel_identity")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Start failed", str(e)); return

        # Persist the category mapping for this channel id (if known later)
        # We'll save after _fill_ui when channel_id is known.

        QtWidgets.QMessageBox.information(
            self, "Background job started",
            f"Job ID: {job_id}\nOutput folder:\n{out_dir}\n"
            "Open Jobs Center to watch progress."
        )
    


    def _fill_ui(self, res: ChannelResult):
        # Channel meta
        self.meta_title.setText(f"{res.channel_title}")
        subs = _fmt_int(res.follower_count)
        cid = res.channel_id or "—"
        self.meta_stats.setText(f"ID: {cid}   •   Subscribers: {subs}\nURL: {res.channel_url}")
        self.meta_desc.setPlainText(res.description or "—")

        # Table
        self.table.setRowCount(0)
        for v in res.videos:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(v.title))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(v.id))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(_fmt_date(v.upload_date)))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(_fmt_duration(v.duration)))
            self.table.setItem(r, 4, QtWidgets.QTableWidgetItem(_fmt_int(v.view_count)))
            self.table.setItem(r, 5, QtWidgets.QTableWidgetItem(v.transcript_lang))
            self.table.setItem(r, 6, QtWidgets.QTableWidgetItem(_fmt_int(v.transcript_chars)))
        self.table.resizeColumnsToContents()
        
        # ... your existing code filling labels/table ...
        # Save category mapping if user has typed one
        cat = self.category_edit.text().strip()
        if cat and res.channel_id:
            m = load_category_map(); m[res.channel_id] = cat; save_category_map(m)
        self._update_details(None)




    def on_export(self):
        if not self._result:
            QtWidgets.QMessageBox.information(self, "Export", "Fetch a channel first.")
            return
        out_dir = self.out_dir.text().strip()
        if not out_dir:
            QtWidgets.QMessageBox.warning(self, "Output folder", "Choose an output folder.")
            return
        os.makedirs(out_dir, exist_ok=True)

        wrote = []
        # 1) per-video text files
        if self.chk_one_file.isChecked():
            for v in self._result.videos:
                if not v.transcript_text:
                    continue
                base = _sanitize_filename(f"{v.title} [{v.id}]")
                path = os.path.join(out_dir, base + ".txt")
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(v.transcript_text)
                    wrote.append(path)
                except Exception as e:
                    self._append_log(f"✖ write {base}.txt: {e}")

        # 2) summary JSON
        if self.chk_json.isChecked():
            payload = {
                "channel": {
                    "title": self._result.channel_title,
                    "id": self._result.channel_id,
                    "url": self._result.channel_url,
                    "subscribers": self._result.follower_count,
                    "description": self._result.description,
                },
                "videos": [
                    {
                        "id": v.id,
                        "title": v.title,
                        "url": v.url,
                        "upload_date": _fmt_date(v.upload_date),
                        "duration": v.duration,
                        "view_count": v.view_count,
                        "transcript_lang": v.transcript_lang,
                        "transcript_chars": v.transcript_chars,
                    }
                    for v in self._result.videos
                ],
            }
            jpath = os.path.join(out_dir, "channel_identity.json")
            try:
                with open(jpath, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                wrote.append(jpath)
            except Exception as e:
                self._append_log(f"✖ write JSON: {e}")

        QtWidgets.QMessageBox.information(self, "Export", "Saved:\n" + "\n".join(wrote) if wrote else "Nothing to save.")
