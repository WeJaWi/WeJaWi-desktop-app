# tools/footage.py
from __future__ import annotations
import os, threading, webbrowser, requests
from typing import List, Optional
from PyQt5 import QtWidgets, QtCore, QtGui

# Optional embedded browser (TikTok/Instagram helpers)
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None  # optional

# Optional native video preview
try:
    from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
    from PyQt5.QtMultimediaWidgets import QVideoWidget
except Exception:
    QMediaPlayer = None
    QMediaContent = None
    QVideoWidget = None

from core.key_store import KeyStore
from .footage_providers import PexelsProvider, PixabayProvider, YouTubeSearchProvider, MediaItem

# Optional: yt-dlp for YouTube/TikTok/Instagram downloads and fallback search
try:
    import yt_dlp as ytdlp
except Exception:
    ytdlp = None

H_SP = 10
V_SP = 10

def _hbox(*widgets, stretch_last=True):
    box = QtWidgets.QHBoxLayout()
    box.setSpacing(H_SP)
    for i, w in enumerate(widgets):
        if w is None:
            continue
        if isinstance(w, int):
            box.addSpacing(w); continue
        box.addWidget(w, 1 if (stretch_last and i == len(widgets) - 1) else 0)
    return box

def _vbox(*widgets):
    box = QtWidgets.QVBoxLayout()
    box.setSpacing(V_SP)
    for w in widgets:
        if w is None:
            continue
        if isinstance(w, int):
            box.addSpacing(w); continue
        if isinstance(w, QtWidgets.QLayout):
            box.addLayout(w)
        else:
            box.addWidget(w)
    return box

class CardFrame(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CardFrame")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)

class Tile(QtWidgets.QFrame):
    download_requested = QtCore.pyqtSignal(object)  # MediaItem
    open_requested = QtCore.pyqtSignal(object)      # MediaItem

    def __init__(self, item: MediaItem):
        super().__init__()
        self.item = item
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setObjectName("Tile")
        self.img = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self.img.setFixedHeight(140)
        self.title = QtWidgets.QLabel(item.title); self.title.setWordWrap(True)
        self.meta = QtWidgets.QLabel(self._meta_text(item)); self.meta.setStyleSheet("color:#aaa;")

        btn_row = QtWidgets.QHBoxLayout()
        self.open_btn = QtWidgets.QPushButton("Open")
        self.dl_btn = QtWidgets.QPushButton("Download")
        btn_row.addWidget(self.open_btn); btn_row.addWidget(self.dl_btn)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.img)
        lay.addWidget(self.title)
        lay.addWidget(self.meta)
        lay.addLayout(btn_row)

        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.item))
        self.dl_btn.clicked.connect(lambda: self.download_requested.emit(self.item))

        threading.Thread(target=self._load_thumb, daemon=True).start()

    def _meta_text(self, it: MediaItem) -> str:
        parts = []
        if it.author:
            parts.append(it.author)
        if it.duration:
            parts.append(f"{int(it.duration//60)}:{int(it.duration%60):02d}")
        if it.width and it.height:
            parts.append(f"{it.width}x{it.height}")
        if it.license:
            parts.append(it.license)
        return ' | '.join(parts)


    def _load_thumb(self):
        try:
            if not self.item.thumb_url:
                return
            r = requests.get(self.item.thumb_url, timeout=30)
            r.raise_for_status()
            img = QtGui.QImage.fromData(r.content)
            pix = QtGui.QPixmap.fromImage(img).scaled(
                self.img.width(), self.img.height(),
                QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
            )
            QtCore.QTimer.singleShot(0, lambda: self.img.setPixmap(pix))
        except Exception:
            pass

class PreviewDialog(QtWidgets.QDialog):
    def __init__(self, item: MediaItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle(item.title or "Preview")
        self.setMinimumWidth(520)
        v = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel(item.title)
        title.setStyleSheet("font-size:16px; font-weight:600;")
        v.addWidget(title)
        # Large thumbnail
        self.preview = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self.preview.setFixedHeight(260)
        self.preview.setStyleSheet("background:#f7f7fb; border:1px solid #e9e9ef; border-radius:10px;")
        v.addWidget(self.preview)
        # Meta
        parts = []
        if getattr(item, "author", None):
            parts.append(item.author)
        if getattr(item, "duration", None):
            parts.append(f"{int(item.duration//60)}:{int(item.duration%60):02d}")
        if getattr(item, "width", None) and getattr(item, "height", None):
            parts.append(f"{item.width}x{item.height}")
        if getattr(item, "license", None):
            parts.append(item.license)
        meta = QtWidgets.QLabel(" | ".join(parts))
        meta.setStyleSheet("color:#666")
        v.addWidget(meta)
        # Buttons
        btns = QtWidgets.QHBoxLayout()
        btn_open = QtWidgets.QPushButton("Open in browser")
        btn_copy = QtWidgets.QPushButton("Copy media URL")
        btns.addStretch(1)
        btns.addWidget(btn_open)
        btns.addWidget(btn_copy)
        v.addLayout(btns)
        btn_open.clicked.connect(lambda: webbrowser.open(item.page_url or item.media_url))
        btn_copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(item.media_url))

        # Load thumbnail async
        def load():
            try:
                if not item.thumb_url:
                    return
                r = requests.get(item.thumb_url, timeout=30)
                r.raise_for_status()
                img = QtGui.QImage.fromData(r.content)
                pm = QtGui.QPixmap.fromImage(img).scaled(
                    self.preview.width(), self.preview.height(),
                    QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation,
                )
                QtCore.QTimer.singleShot(0, lambda: self.preview.setPixmap(pm))
            except Exception:
                pass
        threading.Thread(target=load, daemon=True).start()


class FootagePreviewPane(QtWidgets.QFrame):
    """Inline video/web preview panel for footage results."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FootagePreviewPane")
        self.current_item: Optional[MediaItem] = None
        self._duration = 0
        self._slider_active = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self.title_label = QtWidgets.QLabel("Preview")
        self.title_label.setStyleSheet("font-weight:600; font-size:16px;")
        root.addWidget(self.title_label)

        self.stack = QtWidgets.QStackedWidget()
        root.addWidget(self.stack, 1)

        placeholder = QtWidgets.QWidget()
        ph_layout = QtWidgets.QVBoxLayout(placeholder)
        ph_layout.setContentsMargins(0, 0, 0, 0)
        ph_layout.setSpacing(8)
        ph_layout.addStretch(1)
        self.placeholder_label = QtWidgets.QLabel("Select a clip to preview.")
        self.placeholder_label.setAlignment(QtCore.Qt.AlignCenter)
        self.placeholder_label.setWordWrap(True)
        self.placeholder_label.setStyleSheet("color:#8d95b3;")
        ph_layout.addWidget(self.placeholder_label)
        ph_layout.addStretch(1)
        self.stack.addWidget(placeholder)

        self.player = None
        self.video_page = None
        self.video_widget = None
        self.position_slider = None
        self.time_label = None

        if QMediaPlayer and QVideoWidget:
            self.video_page = QtWidgets.QWidget()
            v_layout = QtWidgets.QVBoxLayout(self.video_page)
            v_layout.setContentsMargins(0, 0, 0, 0)
            v_layout.setSpacing(6)
            self.video_widget = QVideoWidget()
            v_layout.addWidget(self.video_widget, 1)
            self.position_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.position_slider.setEnabled(False)
            v_layout.addWidget(self.position_slider)
            self.time_label = QtWidgets.QLabel("00:00 / 00:00")
            self.time_label.setAlignment(QtCore.Qt.AlignRight)
            self.time_label.setStyleSheet("color:#8d95b3; font-size:12px;")
            v_layout.addWidget(self.time_label)
            self.stack.addWidget(self.video_page)

            self.player = QMediaPlayer(self)
            self.player.setVideoOutput(self.video_widget)
            self.player.positionChanged.connect(self._on_position)
            self.player.durationChanged.connect(self._on_duration)
            self.player.stateChanged.connect(self._on_state)

            self.position_slider.sliderPressed.connect(self._slider_pressed)
            self.position_slider.sliderReleased.connect(self._slider_released)
            self.position_slider.sliderMoved.connect(self._on_slider_moved)

        self.web_view = None
        self.web_page = None
        if QWebEngineView:
            self.web_page = QtWidgets.QWidget()
            w_layout = QtWidgets.QVBoxLayout(self.web_page)
            w_layout.setContentsMargins(0, 0, 0, 0)
            w_layout.setSpacing(0)
            self.web_view = QWebEngineView()
            w_layout.addWidget(self.web_view)
            self.stack.addWidget(self.web_page)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(8)
        self.play_btn = QtWidgets.QPushButton("Play")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        controls.addWidget(self.play_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        self.open_btn = QtWidgets.QPushButton("Open URL")
        self.copy_btn = QtWidgets.QPushButton("Copy URL")
        controls.addWidget(self.open_btn)
        controls.addWidget(self.copy_btn)
        root.addLayout(controls)

        if not self.player:
            self.play_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_play)
        self.stop_btn.clicked.connect(self._stop)
        self.open_btn.clicked.connect(self._open_in_browser)
        self.copy_btn.clicked.connect(self._copy_media)

        self.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear(self, message: Optional[str] = None) -> None:
        if self.player:
            self.player.stop()
        self.current_item = None
        self.title_label.setText("Preview")
        self._show_message(message or "Select a clip to preview.")
        self.open_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self._disable_player_controls()
        self._duration = 0

    def show_item(self, item: Optional[MediaItem]) -> None:
        if item is None:
            self.clear()
            return
        self.current_item = item
        self.title_label.setText(item.title or "Preview")
        url = item.page_url or item.media_url
        self.open_btn.setEnabled(bool(url))
        self.copy_btn.setEnabled(bool(item.media_url))

        if self.player:
            self.player.stop()
        if self._can_stream(item):
            self._play_stream(item.media_url)
            return
        if self.web_view and (item.page_url or item.media_url):
            self.stack.setCurrentWidget(self.web_page)
            self.web_view.setUrl(QtCore.QUrl(item.page_url or item.media_url))
            self._disable_player_controls()
            return
        self._show_message("Can't preview this clip here. Use Open in browser.")
        self._disable_player_controls()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _play_stream(self, url: str) -> None:
        if not (self.player and self.video_page):
            self._show_message("Video playback is unavailable on this system.")
            return
        self.stack.setCurrentWidget(self.video_page)
        if self.position_slider:
            self.position_slider.setEnabled(False)
            self.position_slider.setValue(0)
        if self.time_label:
            self.time_label.setText("00:00 / 00:00")
        self.player.setMedia(QMediaContent(QtCore.QUrl(url)))
        self.player.play()
        self.play_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)
        self.play_btn.setText("Pause")

    def _disable_player_controls(self) -> None:
        if self.position_slider:
            self.position_slider.setEnabled(False)
            self.position_slider.setValue(0)
        if self.time_label:
            self.time_label.setText("00:00 / 00:00")
        self.play_btn.setEnabled(bool(self.player))
        self.play_btn.setText("Play")
        self.stop_btn.setEnabled(bool(self.player))

    def _show_message(self, text: str) -> None:
        self.placeholder_label.setText(text or "Select a clip to preview.")
        self.stack.setCurrentIndex(0)

    def _toggle_play(self) -> None:
        if not self.player:
            return
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.player.mediaStatus() == QMediaPlayer.NoMedia and self.current_item and self.current_item.media_url:
                self._play_stream(self.current_item.media_url)
                return
            self.player.play()

    def _stop(self) -> None:
        if self.player:
            self.player.stop()
            self.play_btn.setText("Play")

    def _open_in_browser(self) -> None:
        if not self.current_item:
            return
        url = self.current_item.page_url or self.current_item.media_url
        if url:
            webbrowser.open(url)

    def _copy_media(self) -> None:
        if not (self.current_item and self.current_item.media_url):
            return
        QtWidgets.QApplication.clipboard().setText(self.current_item.media_url)

    def _can_stream(self, item: MediaItem) -> bool:
        if not (self.player and item and item.media_url):
            return False
        url = item.media_url.split('?')[0].lower()
        if not url.startswith('http'):
            return False
        source = (item.extra or {}).get('source') if item.extra else None
        if source in {'pexels', 'pixabay'}:
            return True
        return url.endswith(('.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi'))

    def _on_position(self, position: int) -> None:
        if not self.position_slider or self._slider_active:
            return
        self.position_slider.blockSignals(True)
        self.position_slider.setValue(position)
        self.position_slider.blockSignals(False)
        if self.time_label:
            self.time_label.setText(f"{self._fmt_ms(position)} / {self._fmt_ms(self._duration)}")

    def _on_duration(self, duration: int) -> None:
        self._duration = duration
        if self.position_slider:
            self.position_slider.setMaximum(max(duration, 0))
            self.position_slider.setEnabled(duration > 0)
        if self.time_label:
            self.time_label.setText(f"{self._fmt_ms(0)} / {self._fmt_ms(duration)}")

    def _on_state(self, state: int) -> None:
        if not self.player:
            return
        if state == QMediaPlayer.PlayingState:
            self.play_btn.setText("Pause")
        else:
            self.play_btn.setText("Play")

    def _slider_pressed(self) -> None:
        self._slider_active = True

    def _slider_released(self) -> None:
        if not (self.player and self.position_slider):
            self._slider_active = False
            return
        pos = self.position_slider.value()
        self.player.setPosition(pos)
        self._slider_active = False

    def _on_slider_moved(self, value: int) -> None:
        if self.time_label:
            self.time_label.setText(f"{self._fmt_ms(value)} / {self._fmt_ms(self._duration)}")

    @staticmethod
    def _fmt_ms(value: int) -> str:
        if value <= 0:
            return "00:00"
        seconds = int(value / 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

class FootageTile(QtWidgets.QFrame):
    download_requested = QtCore.pyqtSignal(object)  # MediaItem
    open_requested = QtCore.pyqtSignal(object)      # MediaItem
    preview_requested = QtCore.pyqtSignal(object)   # MediaItem

    def __init__(self, item: MediaItem):
        super().__init__()
        self.item = item
        self.setObjectName("Tile")
        # UI
        self.img = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self.img.setFixedHeight(140)
        self.img.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.title = QtWidgets.QLabel(item.title)
        self.title.setWordWrap(True)
        self.meta = QtWidgets.QLabel(self._meta_text(item)); self.meta.setObjectName("Meta")
        self.open_btn = QtWidgets.QPushButton("Open")
        self.preview_btn = QtWidgets.QPushButton("Preview")
        self.dl_btn = QtWidgets.QPushButton("Download")
        # Layout
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addWidget(self.open_btn)
        btn_row.addWidget(self.preview_btn)
        btn_row.addWidget(self.dl_btn)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        lay.addWidget(self.img)
        lay.addWidget(self.title)
        lay.addWidget(self.meta)
        lay.addLayout(btn_row)
        # Wire
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.item))
        self.preview_btn.clicked.connect(lambda: self.preview_requested.emit(self.item))
        self.dl_btn.clicked.connect(lambda: self.download_requested.emit(self.item))
        self.img.mousePressEvent = lambda _e: self.preview_requested.emit(self.item)
        # Context menu
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        # Load thumb
        threading.Thread(target=self._load_thumb, daemon=True).start()

    def _menu(self, pos: QtCore.QPoint):
        m = QtWidgets.QMenu(self)
        a_preview = m.addAction("Preview in panel")
        a_open = m.addAction("Open in browser")
        a_page = m.addAction("Copy page URL")
        a_media = m.addAction("Copy media URL")
        a_download = m.addAction("Download")
        action = m.exec_(self.mapToGlobal(pos))
        if action == a_preview:
            self.preview_requested.emit(self.item)
        elif action == a_open:
            self.open_requested.emit(self.item)
        elif action == a_page:
            QtWidgets.QApplication.clipboard().setText(self.item.page_url or self.item.media_url)
        elif action == a_media:
            QtWidgets.QApplication.clipboard().setText(self.item.media_url)
        elif action == a_download:
            self.download_requested.emit(self.item)

    def _meta_text(self, it: MediaItem) -> str:
        parts = []
        if it.author:
            parts.append(it.author)
        if it.duration:
            parts.append(f"{int(it.duration//60)}:{int(it.duration%60):02d}")
        if it.width and it.height:
            parts.append(f"{it.width}x{it.height}")
        if it.license:
            parts.append(it.license)
        return ' | '.join(parts)


    def _load_thumb(self):
        try:
            if not self.item.thumb_url:
                return
            r = requests.get(self.item.thumb_url, timeout=30)
            r.raise_for_status()
            img = QtGui.QImage.fromData(r.content)
            pix = QtGui.QPixmap.fromImage(img).scaled(
                self.img.width(), self.img.height(),
                QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation,
            )
            QtCore.QTimer.singleShot(0, lambda: self.img.setPixmap(pix))
        except Exception:
            pass

class StockTab(QtWidgets.QWidget):
    def __init__(self, keys: KeyStore):
        super().__init__()
        self.keys = keys
        self._providers_cache = {}
        self._build_ui()
        self._wire()

    def _build_ui(self):
        self.query = QtWidgets.QLineEdit()
        self.query.setPlaceholderText("Search stock footage (e.g., \"city skyline at night\")")
        self.query.setClearButtonEnabled(True)

        self.provider = QtWidgets.QComboBox(); self.provider.addItems(["Pexels", "Pixabay"])
        self.per_page = QtWidgets.QSpinBox(); self.per_page.setRange(1, 80); self.per_page.setValue(24)
        self.page = QtWidgets.QSpinBox(); self.page.setRange(1, 50); self.page.setValue(1)
        self.search_btn = QtWidgets.QPushButton("Search")
        self.search_btn.setDefault(True)
        self.keys_btn = QtWidgets.QPushButton("Manage API keys")
        self.status_label = QtWidgets.QLabel("Ready")
        self.status_label.setStyleSheet("color:#697296; font-size:12px;")

        search_card = CardFrame()
        search_layout = QtWidgets.QVBoxLayout(search_card)
        search_layout.setContentsMargins(16, 16, 16, 16)
        search_layout.setSpacing(12)

        header = QtWidgets.QLabel("Search Stock Libraries")
        header.setStyleSheet("font-weight:600;")

        filters = QtWidgets.QHBoxLayout()
        filters.setSpacing(10)
        filters.addWidget(QtWidgets.QLabel("Provider:"))
        filters.addWidget(self.provider)
        filters.addSpacing(6)
        filters.addWidget(QtWidgets.QLabel("Per page:"))
        filters.addWidget(self.per_page)
        filters.addSpacing(6)
        filters.addWidget(QtWidgets.QLabel("Page:"))
        filters.addWidget(self.page)
        filters.addStretch(1)
        filters.addWidget(self.keys_btn)
        filters.addWidget(self.search_btn)

        search_layout.addWidget(header)
        search_layout.addWidget(self.query)
        search_layout.addLayout(filters)
        search_layout.addWidget(self.status_label)

        self.grid = QtWidgets.QWidget()
        self.grid_layout = QtWidgets.QGridLayout(self.grid)
        self.grid_layout.setSpacing(12)
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.grid)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { border: 0; }")

        self.preview = FootagePreviewPane()
        self.preview.setMinimumWidth(340)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.addWidget(self.scroll)
        self.splitter.addWidget(self.preview)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([720, 360])

        self.save_dir = QtWidgets.QLineEdit()
        self.save_dir.setPlaceholderText("Leave empty to save to the current folder")
        self.pick_dir = QtWidgets.QPushButton("Browse...")
        self.pick_dir.clicked.connect(self._pick_out)

        out_card = CardFrame()
        out_layout = QtWidgets.QHBoxLayout(out_card)
        out_layout.setContentsMargins(16, 16, 16, 16)
        out_layout.setSpacing(10)
        out_layout.addWidget(QtWidgets.QLabel("Download to:"))
        out_layout.addWidget(self.save_dir, 1)
        out_layout.addWidget(self.pick_dir)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(search_card)
        root.addWidget(self.splitter, 1)
        root.addWidget(out_card)


    def _wire(self):
        self.search_btn.clicked.connect(self._do_search)
        self.keys_btn.clicked.connect(self._manage_keys)
        self.query.returnPressed.connect(self._do_search)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_loading(self, loading: bool) -> None:
        self.search_btn.setEnabled(not loading)
        self.search_btn.setText('Search' if not loading else 'Searching...')

    def _show_results(self, items: List[MediaItem]):
        self._set_loading(False)
        self._populate(items)

    def _pick_out(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if d:
            self.save_dir.setText(d)

    def _manage_keys(self):
        dlg = KeysDialog(self.keys, parent=self)
        dlg.exec_()
        self._providers_cache.clear()

    def _provider(self, name: str):
        if name in self._providers_cache:
            return self._providers_cache[name]
        if name == "Pexels":
            key = self.keys.get("PEXELS_API_KEY")
            if not key: raise RuntimeError('PEXELS_API_KEY missing. Click "Manage API keys".')
            prov = PexelsProvider(key)
        elif name == "Pixabay":
            key = self.keys.get("PIXABAY_API_KEY")
            if not key: raise RuntimeError('PIXABAY_API_KEY missing. Click "Manage API keys".')
            prov = PixabayProvider(key)
        else:
            raise RuntimeError("Unknown provider")
        self._providers_cache[name] = prov
        return prov

    def _clear_grid(self):
        while self.grid_layout.count():
            it = self.grid_layout.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()

    def _do_search(self):
        q = self.query.text().strip()
        if not q:
            QtWidgets.QMessageBox.warning(self, 'Enter a query', 'Type what you want to search.')
            return
        prov_name = self.provider.currentText()
        per_page = self.per_page.value()
        page = self.page.value()
        self._current_provider = prov_name
        self._clear_grid()
        self._set_status(f'Searching {prov_name}...')
        self._set_loading(True)

        def run():
            try:
                prov = self._provider(prov_name)
                items = prov.search_videos(q, per_page=per_page, page=page)
            except Exception as e:
                def notify():
                    self._set_loading(False)
                    self._set_status('Search failed.')
                    QtWidgets.QMessageBox.critical(self, 'Search failed', str(e))
                QtCore.QTimer.singleShot(0, notify)
                return
            QtCore.QTimer.singleShot(0, lambda: self._show_results(items))

        threading.Thread(target=run, daemon=True).start()


    def _populate(self, items: List[MediaItem]):
        self._clear_grid()
        if hasattr(self, 'preview'):
            self.preview.clear()
        if not items:
            empty = QtWidgets.QLabel('No results yet. Try a different search.')
            empty.setAlignment(QtCore.Qt.AlignCenter)
            empty.setStyleSheet('color:#888;')
            self.grid_layout.addWidget(empty, 0, 0)
            self._set_status('No results found.')
            return
        cols = 3
        for col in range(cols):
            self.grid_layout.setColumnStretch(col, 1)
        for i, it in enumerate(items):
            tile = FootageTile(it)
            tile.open_requested.connect(self._open_item)
            tile.preview_requested.connect(self._preview_item)
            tile.download_requested.connect(self._download_item_with_progress)
            r, c = divmod(i, cols)
            self.grid_layout.addWidget(tile, r, c)
        self.scroll.verticalScrollBar().setValue(0)
        provider = getattr(self, '_current_provider', self.provider.currentText())
        self._set_status(f'Showing {len(items)} result(s) from {provider}.')


    def _open_item(self, it: MediaItem):
        webbrowser.open(it.page_url or it.media_url)

    def _preview_item(self, it: MediaItem):
        if hasattr(self, 'preview') and isinstance(self.preview, FootagePreviewPane):
            self.preview.show_item(it)
        else:
            dlg = PreviewDialog(it, self)
            dlg.exec_()

    def _download_item_with_progress(self, it: MediaItem):
        out_dir = self.save_dir.text().strip() or os.getcwd()
        os.makedirs(out_dir, exist_ok=True)
        base = it.title.replace("/", "_").replace("\\", "_").strip() or f"{it.id}"
        ext = ".mp4"
        for e in (".mp4", ".mov", ".m4v", ".webm", ".avi"):
            if it.media_url.lower().split("?")[0].endswith(e):
                ext = e
                break
        path = os.path.join(out_dir, base + ext)

        cancel_event = threading.Event()
        prog = QtWidgets.QProgressDialog("Downloading...", "Cancel", 0, 100, self)
        prog.setWindowModality(QtCore.Qt.WindowModal)
        prog.canceled.connect(cancel_event.set)
        prog.show()

        class Worker(QtCore.QObject):
            progress = QtCore.pyqtSignal(int)
            done = QtCore.pyqtSignal(str)
            failed = QtCore.pyqtSignal(str)

        w = Worker()
        w.progress.connect(lambda v: prog.setValue(v))
        w.done.connect(lambda p: (prog.close(), QtWidgets.QMessageBox.information(self, "Downloaded", "Saved to:\n" + p)))
        w.failed.connect(lambda msg: (prog.close(), QtWidgets.QMessageBox.critical(self, "Download failed", msg)))

        def run():
            try:
                with requests.get(it.media_url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length") or 0)
                    written = 0
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1 << 20):
                            if cancel_event.is_set():
                                raise RuntimeError("Canceled")
                            if not chunk:
                                continue
                            f.write(chunk)
                            written += len(chunk)
                            if total:
                                pct = int(written * 100 / total)
                                w.progress.emit(pct)
                w.done.emit(path)
            except Exception as e:
                w.failed.emit(str(e))

        threading.Thread(target=run, daemon=True).start()

class _SocialTabLegacy(QtWidgets.QWidget):
    def __init__(self, keys: KeyStore):
        super().__init__()
        self.keys = keys
        self._build_ui()
        self._wire()

    def _build_ui(self):
        self.query = QtWidgets.QLineEdit()
        self.query.setPlaceholderText('Search videos (e.g., "after effects zoom transition")')
        self.platform = QtWidgets.QComboBox(); self.platform.addItems(["YouTube", "TikTok", "Instagram"])
        self.results = QtWidgets.QListWidget()
        self.results.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.search_btn = QtWidgets.QPushButton("Search")
        self.open_btn = QtWidgets.QPushButton("Open Selected")
        self.download_btn = QtWidgets.QPushButton("Download (yt-dlp)")
        self.status = QtWidgets.QLabel(); self.status.setStyleSheet("color:#aaa;")

        top = _vbox(self.query, _hbox(QtWidgets.QLabel("Platform:"), self.platform, self.search_btn), self.status)

        # Optional embedded web for TikTok/Instagram
        self.web = QWebEngineView() if (QWebEngineView and self.platform.currentText() in ("TikTok", "Instagram")) else None

        root = QtWidgets.QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.results, 2)
        if self.web:
            root.addWidget(self.web, 3)
        root.addLayout(_hbox(self.open_btn, self.download_btn))

    def _wire(self):
        self.search_btn.clicked.connect(self._do_search)
        self.open_btn.clicked.connect(self._open_selected)
        self.download_btn.clicked.connect(self._download_selected)
        self.platform.currentIndexChanged.connect(self._platform_changed)

    def _platform_changed(self):
        # (Optional) adapt UI on platform change
        pass

    def _do_search(self):
        q = self.query.text().strip()
        plat = self.platform.currentText()
        if not q:
            QtWidgets.QMessageBox.warning(self, "Enter a query", "Type what you want to search.")
            return
        self.results.clear()
        self.status.setText("Searching...")
        self.status.setText("Searching...")

        if plat == "YouTube":
            key = self.keys.get("YOUTUBE_API_KEY")
            items: List[MediaItem] = []
            if key:
                try:
                    items = YouTubeSearchProvider(key).search(q, max_results=20)
                except Exception:
                    items = []
            if not items:
                if ytdlp is None:
                    self.status.setText("No YOUTUBE_API_KEY and yt-dlp not installed. Cannot search.")
                    return
                items = self._yt_dlp_search(f"ytsearch20:{q}")
            for it in items:
                text = ("{} - {}".format(it.title, it.author) if it.author else it.title)
                li = QtWidgets.QListWidgetItem(text)
                li.setData(QtCore.Qt.UserRole, it.page_url)
                self.results.addItem(li)
            self.status.setText("Found {} result(s).".format(len(items)))

        elif plat == "TikTok":
            url = "https://www.tiktok.com/search?q=" + requests.utils.quote(q)
            self._open_web(url)
            li = QtWidgets.QListWidgetItem("Open TikTok search in web view: " + q)
            li.setData(QtCore.Qt.UserRole, url)
            self.results.addItem(li)
            self.status.setText("Use the web view, open a post, copy its URL to download.")

        elif plat == "Instagram":
            url = "https://www.instagram.com/explore/tags/{}/".format(requests.utils.quote(q.replace(' ', '')))
            self._open_web(url)
            li = QtWidgets.QListWidgetItem("Open Instagram hashtag page: #" + q.replace(' ', ''))
            li.setData(QtCore.Qt.UserRole, url)
            self.results.addItem(li)
            self.status.setText("Log in if required. Copy post URLs to download via yt-dlp.")

    def _open_web(self, url: str):
        if self.web:
            self.web.load(QtCore.QUrl(url))
        else:
            webbrowser.open(url)

    def _yt_dlp_search(self, query: str) -> List[MediaItem]:
        out: List[MediaItem] = []
        if ytdlp is None:
            return out
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "default_search": "ytsearch",
        }
        with ytdlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(query, download=False)
        entries = res.get("entries", []) if isinstance(res, dict) else []
        for e in entries:
            url = e.get("url") or e.get("webpage_url") or ""
            out.append(MediaItem(
                id=e.get("id") or url,
                title=e.get("title", ""),
                author=e.get("uploader") or e.get("channel") or "",
                duration=e.get("duration"),
                width=None, height=None,
                thumb_url=e.get("thumbnail", ""),
                media_url=url,
                page_url=url,
                license=None,
                extra={"source": "yt-dlp"}
            ))
        return out

    def _open_selected(self):
        medias = self._selected_media_items()
        for media in medias:
            url = media.page_url or media.media_url
            if url:
                webbrowser.open(url)

    def _download_selected(self):
        if ytdlp is None:
            QtWidgets.QMessageBox.critical(self, "yt-dlp not installed", "Install with: pip install yt-dlp")
            return
        items = self.results.selectedItems()
        if not items:
            QtWidgets.QMessageBox.information(self, "Select items", "Select one or more results to download.")
            return
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not out_dir:
            return

        def run():
            opts = {
                "outtmpl": os.path.join(out_dir, "%(title).200B [%(id)s].%(ext)s"),
                "quiet": False,
                "noprogress": True,
                "ignoreerrors": True,
            }
            try:
                with ytdlp.YoutubeDL(opts) as ydl:
                    for it in items:
                        url = it.data(QtCore.Qt.UserRole)
                        if url:
                            ydl.download([url])
                QtCore.QTimer.singleShot(0, lambda: QtWidgets.QMessageBox.information(self, "Done", "Downloaded {} item(s).".format(len(items))))
            except Exception as e:
                QtCore.QTimer.singleShot(0, lambda: QtWidgets.QMessageBox.critical(self, "Download failed", str(e)))
        threading.Thread(target=run, daemon=True).start()


class BetterSocialTab(QtWidgets.QWidget):
    def __init__(self, keys: KeyStore):
        super().__init__()
        self.keys = keys
        self._build_ui()
        self._wire()

    def _build_ui(self) -> None:
        self.query = QtWidgets.QLineEdit()
        self.query.setPlaceholderText('Search social clips (e.g., "after effects zoom transition")')
        self.query.setClearButtonEnabled(True)

        self.platform = QtWidgets.QComboBox()
        self.platform.addItems(["YouTube", "TikTok", "Instagram"])

        self.results = QtWidgets.QListWidget()
        self.results.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.results.setAlternatingRowColors(True)
        self.results.setUniformItemSizes(True)
        self.results.setStyleSheet("QListWidget { border: 1px solid #e0e4f2; border-radius: 8px; }")

        self.preview = FootagePreviewPane()
        self.preview.setMinimumWidth(320)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.addWidget(self.results)
        self.splitter.addWidget(self.preview)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

        self.search_btn = QtWidgets.QPushButton("Search")
        self.open_btn = QtWidgets.QPushButton("Open Selected")
        self.download_btn = QtWidgets.QPushButton("Download (yt-dlp)")
        self.status = QtWidgets.QLabel("Ready")
        self.status.setStyleSheet("color:#697296; font-size:12px;")

        search_card = CardFrame()
        search_layout = QtWidgets.QVBoxLayout(search_card)
        search_layout.setContentsMargins(16, 16, 16, 16)
        search_layout.setSpacing(12)

        header = QtWidgets.QLabel("Search Social Platforms")
        header.setStyleSheet("font-weight:600;")

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(QtWidgets.QLabel("Platform:"))
        controls.addWidget(self.platform)
        controls.addStretch(1)
        controls.addWidget(self.search_btn)

        search_layout.addWidget(header)
        search_layout.addWidget(self.query)
        search_layout.addLayout(controls)
        search_layout.addWidget(self.status)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addStretch(1)
        action_row.addWidget(self.open_btn)
        action_row.addWidget(self.download_btn)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(search_card)
        root.addWidget(self.splitter, 1)
        root.addLayout(action_row)

        self._platform_changed()

    def _wire(self) -> None:
        self.search_btn.clicked.connect(self._do_search)
        self.open_btn.clicked.connect(self._open_selected)
        self.download_btn.clicked.connect(self._download_selected)
        self.results.itemSelectionChanged.connect(self._on_selection_changed)
        self.query.returnPressed.connect(self._do_search)
        self.platform.currentIndexChanged.connect(lambda _: self._platform_changed())

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _set_loading(self, loading: bool) -> None:
        self.search_btn.setEnabled(not loading)
        self.search_btn.setText('Search' if not loading else 'Searching...')

    def _item_from_list_item(self, list_item: Optional[QtWidgets.QListWidgetItem]) -> Optional[MediaItem]:
        if list_item is None:
            return None
        payload = list_item.data(QtCore.Qt.UserRole)
        if isinstance(payload, MediaItem):
            return payload
        if isinstance(payload, str) and payload:
            return MediaItem(
                id=payload,
                title=payload,
                author="",
                duration=None,
                width=None,
                height=None,
                thumb_url="",
                media_url=payload,
                page_url=payload,
                license=None,
                extra={"source": "external"},
            )
        return None

    def _selected_media_items(self) -> List[MediaItem]:
        out: List[MediaItem] = []
        for list_item in self.results.selectedItems():
            media = self._item_from_list_item(list_item)
            if media:
                out.append(media)
        return out

    def _on_selection_changed(self) -> None:
        media = self._item_from_list_item(self.results.currentItem())
        if media:
            self.preview.show_item(media)
        else:
            self.preview.clear()

    def _platform_changed(self) -> None:
        plat = self.platform.currentText()
        if plat == 'YouTube':
            hint = 'Ready to search YouTube.'
        else:
            hint = f'Search opens {plat} in your browser.'
        self._set_status(hint)

    def _do_search(self) -> None:
        q = self.query.text().strip()
        plat = self.platform.currentText()
        if not q:
            QtWidgets.QMessageBox.warning(self, 'Enter a query', 'Type what you want to search.')
            return
        self.results.clear()
        self.preview.clear()
        self._set_loading(True)
        self._set_status(f'Searching {plat}...')

        if plat == 'TikTok':
            url = 'https://www.tiktok.com/search?q=' + requests.utils.quote(q)
            webbrowser.open(url)
            media = MediaItem(id=url, title='TikTok search', author='', duration=None,
                              width=None, height=None, thumb_url='', media_url=url,
                              page_url=url, license=None, extra={'source': 'tiktok-search'})
            li = QtWidgets.QListWidgetItem('Opened TikTok search: ' + q)
            li.setData(QtCore.Qt.UserRole, media)
            self.results.addItem(li)
            self.results.setCurrentRow(0)
            self._set_status('Opened TikTok search in your browser. Copy a post URL to download with yt-dlp.')
            self._set_loading(False)
            return

        if plat == 'Instagram':
            url = 'https://www.instagram.com/explore/tags/{}/'.format(requests.utils.quote(q.replace(' ', '')))
            webbrowser.open(url)
            media = MediaItem(id=url, title='Instagram hashtag', author='', duration=None,
                              width=None, height=None, thumb_url='', media_url=url,
                              page_url=url, license=None, extra={'source': 'instagram-search'})
            li = QtWidgets.QListWidgetItem('Opened Instagram hashtag: #' + q.replace(' ', ''))
            li.setData(QtCore.Qt.UserRole, media)
            self.results.addItem(li)
            self.results.setCurrentRow(0)
            self._set_status('Opened Instagram in your browser. Copy post URLs for yt-dlp.')
            self._set_loading(False)
            return

        def _populate(items: List[MediaItem]) -> None:
            self.results.clear()
            for media in items:
                label = f"{media.title} - {media.author}" if media.author else media.title
                li = QtWidgets.QListWidgetItem(label)
                li.setData(QtCore.Qt.UserRole, media)
                self.results.addItem(li)
            if items:
                self.results.setCurrentRow(0)
            self._set_status(f'Found {len(items)} result(s) on YouTube.')
            self._set_loading(False)

        def run() -> None:
            key = self.keys.get('YOUTUBE_API_KEY')
            items: List[MediaItem] = []
            if key:
                try:
                    items = YouTubeSearchProvider(key).search(q, max_results=20)
                except Exception as exc:
                    QtCore.QTimer.singleShot(0, lambda: self._set_status(f'YouTube API error: {exc}'))
            if not items:
                if ytdlp is None:
                    QtCore.QTimer.singleShot(0, lambda: (
                        self._set_status('No YOUTUBE_API_KEY and yt-dlp not installed. Cannot search.'),
                        self._set_loading(False),
                    ))
                    return
                try:
                    items = self._yt_dlp_search(f'ytsearch20:{q}')
                except Exception as exc:
                    QtCore.QTimer.singleShot(0, lambda: (
                        self._set_status(f'yt-dlp search failed: {exc}'),
                        self._set_loading(False),
                    ))
                    return
            QtCore.QTimer.singleShot(0, lambda: _populate(items))

        threading.Thread(target=run, daemon=True).start()

    def _yt_dlp_search(self, query: str) -> List[MediaItem]:
        out: List[MediaItem] = []
        if ytdlp is None:
            return out
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "default_search": "ytsearch",
        }
        with ytdlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(query, download=False)
        entries = res.get("entries", []) if isinstance(res, dict) else []
        for e in entries:
            url = e.get("url") or e.get("webpage_url") or ""
            out.append(MediaItem(
                id=e.get("id") or url,
                title=e.get("title", ""),
                author=e.get("uploader") or e.get("channel") or "",
                duration=e.get("duration"),
                width=None,
                height=None,
                thumb_url=e.get("thumbnail", ""),
                media_url=url,
                page_url=url,
                license=None,
                extra={'source': 'yt-dlp'},
            ))
        return out

    def _open_selected(self) -> None:
        for media in self._selected_media_items():
            url = media.page_url or media.media_url
            if url:
                webbrowser.open(url)

    def _download_selected(self) -> None:
        if ytdlp is None:
            QtWidgets.QMessageBox.critical(self, "yt-dlp not installed", "Install with: pip install yt-dlp")
            return
        medias = self._selected_media_items()
        if not medias:
            QtWidgets.QMessageBox.information(self, "Select items", "Select one or more results to download.")
            return
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder")
        if not out_dir:
            return

        def run() -> None:
            opts = {
                "outtmpl": os.path.join(out_dir, "%(title).200B [%(id)s].%(ext)s"),
                "quiet": False,
                "noprogress": True,
                "ignoreerrors": True,
            }
            try:
                with ytdlp.YoutubeDL(opts) as ydl:
                    for media in medias:
                        url = media.media_url or media.page_url
                        if url:
                            ydl.download([url])
                QtCore.QTimer.singleShot(0, lambda: QtWidgets.QMessageBox.information(self, "Done", f"Downloaded {len(medias)} item(s)."))
            except Exception as exc:
                QtCore.QTimer.singleShot(0, lambda: QtWidgets.QMessageBox.critical(self, "Download failed", str(exc)))

        threading.Thread(target=run, daemon=True).start()

class KeysDialog(QtWidgets.QDialog):
    def __init__(self, keys: KeyStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API Keys")
        self.setMinimumWidth(460)
        self.keys = keys
        self._build_ui()
        self._wire()

    def _build_ui(self):
        self.pexels = QtWidgets.QLineEdit(self.keys.get("PEXELS_API_KEY") or "")
        self.pixabay = QtWidgets.QLineEdit(self.keys.get("PIXABAY_API_KEY") or "")
        self.unsplash = QtWidgets.QLineEdit(self.keys.get("UNSPLASH_ACCESS_KEY") or "")
        self.youtube = QtWidgets.QLineEdit(self.keys.get("YOUTUBE_API_KEY") or "")
        for le in (self.pexels, self.pixabay, self.unsplash, self.youtube):
            le.setEchoMode(QtWidgets.QLineEdit.PasswordEchoOnEdit)
        form = QtWidgets.QFormLayout()
        form.addRow("Pexels API Key:", self.pexels)
        form.addRow("Pixabay API Key:", self.pixabay)
        form.addRow("Unsplash Access Key (photos):", self.unsplash)
        form.addRow("YouTube API Key:", self.youtube)
        self.save_btn = QtWidgets.QPushButton("Save")
        self.cancel_btn = QtWidgets.QPushButton("Close")
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1); btns.addWidget(self.save_btn); btns.addWidget(self.cancel_btn)
        root = QtWidgets.QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(btns)

    def _wire(self):
        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._save)

    def _save(self):
        self.keys.save_many({
            "PEXELS_API_KEY": self.pexels.text().strip(),
            "PIXABAY_API_KEY": self.pixabay.text().strip(),
            "UNSPLASH_ACCESS_KEY": self.unsplash.text().strip(),
            "YOUTUBE_API_KEY": self.youtube.text().strip(),
        })
        QtWidgets.QMessageBox.information(self, "Saved", "Keys saved to ~/.wejawi_keys.json")
        self.accept()

class FootagePage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FootagePage")
        self.keys = KeyStore()
        self._build_ui()

    def _build_ui(self):
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(False)
        self.stock = StockTab(self.keys)
        self.social = BetterSocialTab(self.keys)
        self.tabs.addTab(self.stock, 'Stock Sites')
        self.tabs.addTab(self.social, 'Social Search')

        title = QtWidgets.QLabel('Footage')
        title.setObjectName('PageTitle')
        title.setStyleSheet('font-size:22px; font-weight:600;')
        subtitle = QtWidgets.QLabel('Search stock sites or social platforms for clips. Manage API keys in the Stock tab.')
        subtitle.setStyleSheet('color:#555;')
        info = QtWidgets.QLabel('Tip: Install yt-dlp (pip install yt-dlp) for social downloads.')
        info.setStyleSheet('color:#6b7085; font-size:12px;')

        header = CardFrame()
        header_layout = QtWidgets.QVBoxLayout(header)
        header_layout.setContentsMargins(16, 16, 16, 16)
        header_layout.setSpacing(6)
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        header_layout.addWidget(info)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(16)
        root.addWidget(header)
        root.addWidget(self.tabs, 1)




