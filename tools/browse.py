# tools/browse.py
# PyQt5 "Browse" tool â€” Brave-like simple browser with low-RAM profile,
# custom start page with link tiles, a left "Pins" bar, and a minimal
# Axiom-style side panel (design-only, no automation logic).
#
# Requires: pip install PyQt5 PyQtWebEngine
# - If PyQtWebEngine is missing, we show a friendly help panel.
#
# Notes for integration:
# - The app's main_window.py imports: from tools.browse import BrowsePage
# - This file only uses Python + PyQt5, no MoviePy or extra deps.
# - Link storage is JSON at: ../data/quick_links.json (created on first run).

from __future__ import annotations
import os, json, re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PyQt5 import QtWidgets, QtCore, QtGui

from core.logging_utils import get_logger

logger = get_logger(__name__)

# ---- WebEngine check ---------------------------------------------------------
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile, QWebEngineSettings, QWebEnginePage
    from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
    WEB_OK = True
except Exception as exc:
    WEB_OK = False
    logger.warning("Qt WebEngine imports failed: %s", exc)

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LINKS_PATH = DATA_DIR / "quick_links.json"
PINS_PATH = DATA_DIR / "pins.json"


def _asset_path(*parts: str) -> str:
    path = ROOT_DIR.joinpath(*parts)
    if path.exists():
        return str(path)
    return str(Path(*parts))


def _ensure_json(path: str, default_obj):
    if not os.path.isfile(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default_obj, f, ensure_ascii=False, indent=2)
            logger.info("Created default JSON store at %s", path)
        except Exception:
            logger.exception("Failed to create JSON store at %s", path)

# sensible defaults
_ensure_json(LINKS_PATH, {
    "links":[
        {"title":"Google","url":"https://www.google.com","color":"#4285F4"},
        {"title":"YouTube","url":"https://www.youtube.com","color":"#FF3D00"},
        {"title":"X / Twitter","url":"https://twitter.com","color":"#111111"},
        {"title":"Reddit","url":"https://www.reddit.com","color":"#FF4500"},
        {"title":"GitHub","url":"https://github.com","color":"#24292e"},
    ]
})
_ensure_json(PINS_PATH, {"pins":[]})

# ---- Storage -----------------------------------------------------------------
class LinkStore:
    def __init__(self, path: str):
        self.path = path
        self._data = {"links":[]}
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f) or {"links":[]}
            logger.debug("Loaded %s with %d entries", self.path, len(self._data.get("links", [])))
        except Exception:
            logger.exception("Failed to load links from %s", self.path)
            self._data = {"links":[]}

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            logger.debug("Saved %s", self.path)
        except Exception:
            logger.exception("Failed to save links to %s", self.path)

    def all(self) -> List[dict]:
        return list(self._data.get("links") or [])

    def add(self, title: str, url: str, color: str = "#6E56CF"):
        url = self._norm_url(url)
        self._data.setdefault("links", []).append({"title": title.strip() or url, "url": url, "color": color})
        logger.info("Added quick link: title=%s url=%s", title.strip() or url, url)
        self.save()

    def remove_at(self, idx: int):
        links = self._data.get("links") or []
        if 0 <= idx < len(links):
            logger.info("Removing quick link at index %s (%s)", idx, links[idx].get("title"))
            del links[idx]
            self.save()

    def _norm_url(self, u: str) -> str:
        u = u.strip()
        if not u: return u
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
            return u
        if "." in u and " " not in u:
            return "https://" + u
        # fallback: search
        return "https://www.google.com/search?q=" + QtCore.QUrl.toPercentEncoding(u).data().decode("utf-8")

class PinsStore(LinkStore):
    pass

# ---- Helper widgets -----------------------------------------------------------
def circle_pixmap(letter: str, fill: QtGui.QColor, size: int = 32) -> QtGui.QPixmap:
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHints(QtGui.QPainter.Antialiasing|QtGui.QPainter.TextAntialiasing)
    # circle
    brush = QtGui.QBrush(fill)
    p.setBrush(brush); p.setPen(QtCore.Qt.NoPen)
    p.drawEllipse(0,0,size,size)
    # letter
    f = QtGui.QFont()
    f.setBold(True); f.setPointSize(int(size*0.44))
    p.setFont(f)
    p.setPen(QtGui.QColor("#FFFFFF") if fill.lightness() < 130 else QtGui.QColor("#000000"))
    p.drawText(QtCore.QRect(0,0,size,size), QtCore.Qt.AlignCenter, (letter[:1] or " ").upper())
    p.end()
    return pm

class LinkTile(QtWidgets.QPushButton):
    clickedUrl = QtCore.pyqtSignal(str)

    def __init__(self, title: str, url: str, color: str):
        super().__init__()
        self.title, self.url, self.color = title, url, color or "#5865f2"
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.setMinimumHeight(110)
        self.setCheckable(False)
        self.setObjectName("BrowseTile")

        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setObjectName('BrowseTileIcon')
        icon_lbl.setFixedSize(52, 52)
        icon_lbl.setPixmap(circle_pixmap(title[:1] or "?", QtGui.QColor(self.color), 52))

        title_lbl = QtWidgets.QLabel(title)
        title_lbl.setObjectName('BrowseTileTitle')
        url_lbl = QtWidgets.QLabel(url)
        url_lbl.setObjectName('BrowseTileUrl')
        url_lbl.setWordWrap(True)

        text_col = QtWidgets.QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(6)
        text_col.addWidget(title_lbl)
        text_col.addWidget(url_lbl)

        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        row.addWidget(icon_lbl, 0)
        row.addLayout(text_col, 1)

        self.clicked.connect(lambda: self.clickedUrl.emit(self.url))
class AddTile(QtWidgets.QPushButton):
    addRequested = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__('+ Add link')
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        self.setMinimumHeight(110)
        self.setObjectName('BrowseAddTile')
        self.clicked.connect(self.addRequested.emit)
class StartPage(QtWidgets.QScrollArea):
    linkClicked = QtCore.pyqtSignal(str)
    quickActionRequested = QtCore.pyqtSignal(str)

    QUICK_ACTIONS = [
        {'title': 'Open YouTube', 'url': 'https://www.youtube.com'},
        {'title': 'Open Google Drive', 'url': 'https://drive.google.com'},
        {'title': 'Open Notion', 'url': 'https://www.notion.so'},
        {'title': 'Open ChatGPT', 'url': 'https://chat.openai.com'},
        {'title': 'Launch Brave automation', 'tool': 'brave_auto'},
    ]

    def __init__(self, store: LinkStore):
        super().__init__()
        self.setWidgetResizable(True)
        self.store = store

        wrap = QtWidgets.QWidget()
        self.setWidget(wrap)
        self.root = QtWidgets.QVBoxLayout(wrap)
        self.root.setContentsMargins(32, 32, 32, 32)
        self.root.setSpacing(24)

        self._build_header()
        self._build_quick_actions()
        self._build_grid()
        self._refresh()

    def _build_header(self):
        hero = QtWidgets.QFrame()
        hero.setObjectName('BrowseHeroCard')
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 24, 24, 24)
        hero_layout.setSpacing(16)

        title = QtWidgets.QLabel('Good to see you')
        title.setObjectName('BrowseHeroTitle')
        caption = QtWidgets.QLabel('Search the web, jump to your quick links, or pin new resources to the left rail.')
        caption.setWordWrap(True)
        caption.setObjectName('BrowseHeroSubtitle')

        hero_layout.addWidget(title)
        hero_layout.addWidget(caption)

        search_wrap = QtWidgets.QFrame()
        search_wrap.setObjectName('BrowseSearchWrap')
        search_row = QtWidgets.QHBoxLayout(search_wrap)
        search_row.setContentsMargins(14, 12, 14, 12)
        search_row.setSpacing(10)

        search_icon = QtWidgets.QLabel()
        search_icon.setPixmap(self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogContentsView).pixmap(18, 18))
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText('Search the web or type a URL')
        self.search.setFrame(False)
        self.search.setObjectName('BrowseHeroSearchEdit')
        self.search.returnPressed.connect(self._do_search)
        search_button = QtWidgets.QPushButton('Search')
        search_button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        search_button.setObjectName('BrowseHeroSearchButton')
        search_button.clicked.connect(self._do_search)

        search_row.addWidget(search_icon)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(search_button)

        hero_layout.addWidget(search_wrap)
        self.root.addWidget(hero)

    def _build_quick_actions(self):
        actions_frame = QtWidgets.QFrame()
        actions_frame.setObjectName('BrowseActionsFrame')
        actions_layout = QtWidgets.QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(18, 14, 18, 14)
        actions_layout.setSpacing(12)

        label = QtWidgets.QLabel('Quick actions')
        label.setObjectName('BrowseQuickActionsLabel')
        actions_layout.addWidget(label)

        for item in self.QUICK_ACTIONS:
            title = item.get('title', '')
            btn = QtWidgets.QPushButton(title)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            btn.setObjectName('BrowseQuickActionButton')
            tool = item.get('tool')
            url = item.get('url')
            if tool:
                btn.clicked.connect(lambda _=False, tool=tool: self.quickActionRequested.emit(tool))
            elif url:
                btn.clicked.connect(lambda _=False, target=url: self.linkClicked.emit(target))
            else:
                btn.setEnabled(False)
            actions_layout.addWidget(btn)

        actions_layout.addStretch(1)
        self.root.addWidget(actions_frame)

    def _build_grid(self):
        grid_frame = QtWidgets.QFrame()
        grid_frame.setObjectName('BrowseGridFrame')
        grid_layout = QtWidgets.QVBoxLayout(grid_frame)
        grid_layout.setContentsMargins(18, 18, 18, 18)
        grid_layout.setSpacing(16)

        header_row = QtWidgets.QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        title = QtWidgets.QLabel('Pinned links')
        title.setObjectName('BrowseGridHeading')
        header_row.addWidget(title)
        header_row.addStretch(1)
        grid_layout.addLayout(header_row)

        self.grid = QtWidgets.QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        grid_layout.addLayout(self.grid)

        self.root.addWidget(grid_frame, 1)

    def _do_search(self):
        q = self.search.text().strip()
        if not q:
            return
        url = 'https://www.google.com/search?q=' + QtCore.QUrl.toPercentEncoding(q).data().decode('utf-8')
        self.linkClicked.emit(url)

    def _refresh(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        links = self.store.all()
        cols = 3
        for i, ln in enumerate(links):
            card = LinkTile(ln.get('title', ''), ln.get('url', ''), ln.get('color', '#5865f2'))
            card.clickedUrl.connect(self.linkClicked)
            self.grid.addWidget(card, i // cols, i % cols)

        add = AddTile()
        add.addRequested.connect(self._add_link_dialog)
        row = len(links) // cols
        col = len(links) % cols
        self.grid.addWidget(add, row, col)

        if not links:
            empty = QtWidgets.QLabel('You have no links yet. Use "Add link" to create your first quick access tile.')
            empty.setWordWrap(True)
            empty.setObjectName('BrowseEmptyLabel')
            self.grid.addWidget(empty, row + 1, 0, 1, max(1, cols))

    def _add_link_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Add link')
        form = QtWidgets.QFormLayout(dialog)
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        title_edit = QtWidgets.QLineEdit()
        url_edit = QtWidgets.QLineEdit()
        color_edit = QtWidgets.QLineEdit('#5865f2')
        form.addRow('Title:', title_edit)
        form.addRow('URL:', url_edit)
        form.addRow('Color (hex):', color_edit)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            self.store.add(title_edit.text(), url_edit.text(), color_edit.text())
            self._refresh()
class SimpleBlocker(QWebEngineUrlRequestInterceptor):
    BLOCK_HOST_PARTS = [
        "doubleclick", "googlesyndication", "adservice", "adsystem",
        "facebook.net", "googletagmanager", "analytics", "scorecardresearch",
        "taboola", "outbrain", "zedo", "qualtrics", "tiqcdn",
    ]
    def interceptRequest(self, info):
        url = info.requestUrl().toString().lower()
        if any(p in url for p in self.BLOCK_HOST_PARTS):
            info.block(True)

# ---- Browser core -------------------------------------------------------------
class BrowserTab(QtWidgets.QWidget):
    titleChanged = QtCore.pyqtSignal(str)
    urlChanged = QtCore.pyqtSignal(QtCore.QUrl)
    iconChanged = QtCore.pyqtSignal(QtGui.QIcon)
    toolRequested = QtCore.pyqtSignal(str)

    def __init__(self, profile: Optional[QWebEngineProfile], start_url: Optional[str], link_store: LinkStore):
        super().__init__()
        self._link_store = link_store

        self.stack = QtWidgets.QStackedWidget(self)
        v = QtWidgets.QVBoxLayout(self); v.setContentsMargins(0,0,0,0); v.addWidget(self.stack)

        self.start = StartPage(link_store)
        self.start.linkClicked.connect(self.load_url)
        self.start.quickActionRequested.connect(self._forward_quick_action)
        self.stack.addWidget(self.start)

        if WEB_OK:
            self.view = QWebEngineView()
            if profile: self.view.setPage(QWebEnginePage(profile, self.view))
            self.view.titleChanged.connect(self.titleChanged)
            self.view.urlChanged.connect(self.urlChanged)
            self.view.iconChanged.connect(self.iconChanged)
            self.stack.addWidget(self.view)
        else:
            self.view = None

        # show start page first
        self.stack.setCurrentIndex(0)
        if start_url:
            self.load_url(start_url)

    def _forward_quick_action(self, tool_key: str):
        if tool_key:
            self.toolRequested.emit(tool_key)

    def load_url(self, url: str):
        if not WEB_OK or not self.view:
            return
        q = QtCore.QUrl(url)
        if not q.scheme():
            q = QtCore.QUrl("https://" + url)
        self.view.load(q)
        self.stack.setCurrentWidget(self.view)

    def go_home(self):
        self.stack.setCurrentWidget(self.start)

# ---- Axiom-like side panel (design only) -------------------------------------
class AxiomPanel(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        self.setStyleSheet("QFrame{background:#0f0b2e;border-left:1px solid #2a1f6c;} QLabel{color:white;}")
        v = QtWidgets.QVBoxLayout(self); v.setContentsMargins(12,12,12,12); v.setSpacing(10)
        title = QtWidgets.QLabel("Axiom â€¢ Flows"); title.setStyleSheet("font-weight:700; font-size:16px;")
        v.addWidget(title)
        desc = QtWidgets.QLabel("Design-only mock. Add your automation here later.")
        desc.setWordWrap(True); desc.setStyleSheet("color:#cfc6ff;")
        v.addWidget(desc)

        def pill(txt):
            b = QtWidgets.QPushButton(txt); b.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            b.setStyleSheet("QPushButton{background:#3d2bff;color:#fff;border:none;padding:10px 12px;border-radius:10px;}"
                            "QPushButton:hover{background:#5a47ff;}")
            return b

        v.addWidget(pill("â—‰ Record macro"))
        v.addWidget(pill("â–¶ Play a flow"))
        v.addWidget(pill("ï¼‹ New flow"))
        v.addStretch(1)

# ---- Pins bar -----------------------------------------------------------------
class PinsBar(QtWidgets.QFrame):
    pinTriggered = QtCore.pyqtSignal(str)

    def __init__(self, store: PinsStore):
        super().__init__()
        self.store = store
        self.setObjectName('BrowsePinBar')
        self.setMinimumWidth(72)
        self.setMaximumWidth(320)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.v = QtWidgets.QVBoxLayout(self)
        self.v.setContentsMargins(16, 20, 16, 20)
        self.v.setSpacing(14)
        self._reload()

    def _reload(self):
        while self.v.count():
            item = self.v.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        header = QtWidgets.QLabel('Pins')
        header.setAlignment(QtCore.Qt.AlignHCenter)
        header.setObjectName('BrowsePinHeader')
        self.v.addWidget(header)
        for pin in self.store.all():
            btn = QtWidgets.QToolButton()
            btn.setIcon(QtGui.QIcon(circle_pixmap(pin['title'][:1] or '?', QtGui.QColor(pin.get('color', '#5865f2')), 32)))
            btn.setIconSize(QtCore.QSize(36, 36))
            btn.setAutoRaise(True)
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            btn.clicked.connect(lambda _=False, target=pin.get('url', ''): self.pinTriggered.emit(target))
            self.v.addWidget(btn)
        self.v.addStretch(1)

    def pin_current(self, title: str, url: str):
        existing = {ln.get('url') for ln in self.store.all()}
        if url in existing:
            return
        self.store.add(title, url, '#4f46e5')
        self._reload()
class BrowsePage(QtWidgets.QWidget):
    toolRequested = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrowsePage")

        logger.info("Initialising BrowsePage (web support=%s)", WEB_OK)

        if not WEB_OK:
            self._build_fallback()
            return

        # Low-RAM profile
        self.profile = QWebEngineProfile("wejawi_lowram", self)
        self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self.profile.setHttpCacheMaximumSize(24 * 1024 * 1024)  # 24 MB
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        self.profile.setSpellCheckEnabled(False)
        self.profile.setRequestInterceptor(SimpleBlocker())

        s = self.profile.settings()
        s.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        s.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        s.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)  # enable minimal state per tab

        # Layout: [PinsBar | Main Column | AxiomPanel] with splitter
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.pins = PinsBar(PinsStore(PINS_PATH))

        central = QtWidgets.QWidget()
        main = QtWidgets.QVBoxLayout(central)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        self.axiom = AxiomPanel()
        self.axiom.setVisible(False)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.splitter.setObjectName("BrowseSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.pins)
        self.splitter.addWidget(central)
        self.splitter.addWidget(self.axiom)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([96, 900, 0])

        root.addWidget(self.splitter)

        # Toolbar
        tb = QtWidgets.QHBoxLayout()
        tb.setContentsMargins(16, 16, 16, 16)
        tb.setSpacing(10)
        toolbar = QtWidgets.QWidget()
        toolbar.setLayout(tb)
        toolbar.setObjectName("BrowseToolbar")
        main.addWidget(toolbar)

        style = QtWidgets.QApplication.style()

        def nav_button(icon_enum=None, icon_name=None, tip="", slot=None):
            button = QtWidgets.QToolButton()
            icon = None
            if icon_name:
                icon_path = Path(_asset_path('icons', icon_name))
                if icon_path.exists():
                    icon = QtGui.QIcon(str(icon_path))
            if icon is None and icon_enum is not None:
                icon = style.standardIcon(icon_enum)
            if icon is not None:
                button.setIcon(icon)
            button.setAutoRaise(True)
            button.setToolTip(tip)
            if slot:
                button.clicked.connect(slot)
            return button

        self.btn_back = nav_button(icon_name='left-arrow.png', tip='Back', slot=lambda: self._cur_view().back() if self._cur_view() else None)
        self.btn_fwd = nav_button(icon_name='right-arrow.png', tip='Forward', slot=lambda: self._cur_view().forward() if self._cur_view() else None)
        self.btn_reload = nav_button(icon_name='rotate-right.png', tip='Reload', slot=lambda: self._cur_view().reload() if self._cur_view() else None)
        self.btn_home = nav_button(icon_name='home.png', tip='Home', slot=self._go_home_current)

        self.addr = QtWidgets.QLineEdit()
        self.addr.setObjectName('BrowseAddressBar')
        self.addr.setPlaceholderText('Type URL or search the web')
        self.addr.returnPressed.connect(self._go_addr)

        self.btn_go = QtWidgets.QPushButton('Go')
        self.btn_go.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn_go.setObjectName('BrowseGoButton')
        self.btn_go.clicked.connect(self._go_addr)

        self.btn_pin = QtWidgets.QPushButton('Pin')
        self.btn_pin.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn_pin.setObjectName('BrowsePinButton')
        self.btn_pin.setToolTip('Pin current site to the left bar')
        self.btn_pin.clicked.connect(self._pin_current)

        self.btn_axiom = nav_button(icon_enum=QtWidgets.QStyle.SP_DialogHelpButton, tip='Toggle Axiom panel', slot=self._toggle_axiom)

        tb.addWidget(self.btn_back)
        tb.addWidget(self.btn_fwd)
        tb.addWidget(self.btn_reload)
        tb.addWidget(self.btn_home)
        tb.addSpacing(8)
        tb.addWidget(self.addr, 1)
        tb.addSpacing(8)
        tb.addWidget(self.btn_go)
        tb.addWidget(self.btn_pin)
        tb.addWidget(self.btn_axiom)

        # Tabs
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("BrowseTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        main.addWidget(self.tabs, 1)

        # Add first tab (start page)
        self._new_tab(start_url=None, label="New Tab")

        # Axiom panel (hidden by default)
        # Signals
        self.tabs.currentChanged.connect(self._sync_addr)
        self.pins.pinTriggered.connect(self._open_in_current)

    # ---- UI builders ----
    def _build_fallback(self):
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(16,16,16,16)
        t = QtWidgets.QLabel("Browse")
        t.setObjectName("PageTitle")
        v.addWidget(t)
        info = QtWidgets.QLabel(
            "Qt WebEngine is not installed.\n\n"
            "Install it for this feature:\n"
            "    pip install PyQt5 PyQtWebEngine\n\n"
            "Then relaunch WeJaWi."
        )
        info.setStyleSheet("color:white; font-size:15px;")
        v.addWidget(info)

    # ---- Actions ----
    def _cur_tab(self) -> Optional[BrowserTab]:
        w = self.tabs.currentWidget()
        return w if isinstance(w, BrowserTab) else None

    def _cur_view(self) -> Optional[QWebEngineView]:
        t = self._cur_tab()
        return t.view if (t and hasattr(t, "view")) else None

    def _sync_addr(self, _idx: int):
        v = self._cur_view()
        self.addr.setText(v.url().toString() if v else "")

    def _go_addr(self):
        text = self.addr.text().strip()
        if not text:
            logger.debug("Ignored empty address bar submission")
            return
        url = text
        if " " in text or not re.search(r"^[a-z]+://", text, re.I):
            # treat as search unless it's clearly a scheme
            url = "https://www.google.com/search?q=" + QtCore.QUrl.toPercentEncoding(text).data().decode("utf-8")
            logger.info("Address bar query routed to search: %s", text)
        else:
            logger.info("Navigating to %s", url)
        self._open_in_current(url)

    def _open_in_current(self, url: str):
        t = self._cur_tab()
        if not t:
            logger.warning("No active tab when trying to open %s", url)
            return
        logger.debug("Loading URL in current tab: %s", url)
        t.load_url(url)
        if hasattr(t, "view") and t.view:
            # update title & icon to tab
            t.view.titleChanged.connect(lambda _=None, tab=t: self._update_tab_title(tab))
            t.view.iconChanged.connect(lambda _=None, tab=t: self._update_tab_icon(tab))

    def _update_tab_title(self, tab: BrowserTab):
        idx = self.tabs.indexOf(tab)
        if idx < 0: return
        title = tab.view.title() if tab.view else "Tab"
        self.tabs.setTabText(idx, (title[:18] + "â€¦") if len(title) > 19 else title)

    def _update_tab_icon(self, tab: BrowserTab):
        idx = self.tabs.indexOf(tab)
        if idx < 0: return
        if tab.view:
            self.tabs.setTabIcon(idx, tab.view.icon())

    def _new_tab(self, start_url: Optional[str] = None, label: str = "New Tab"):
        t = BrowserTab(self.profile if WEB_OK else None, start_url, LinkStore(LINKS_PATH))
        logger.info("Opened new tab (label=%s, start_url=%s)", label, start_url)
        t.toolRequested.connect(self.toolRequested.emit)
        # wire title/url/icon to tab
        if WEB_OK and t.view:
            t.view.titleChanged.connect(lambda _=None, tab=t: self._update_tab_title(tab))
            t.view.iconChanged.connect(lambda _=None, tab=t: self._update_tab_icon(tab))
            t.view.urlChanged.connect(lambda q: self.addr.setText(q.toString()))
        idx = self.tabs.addTab(t, label)
        self.tabs.setCurrentIndex(idx)
        return t

    def _close_tab(self, idx: int):
        logger.info("Closing tab at index %s", idx)
        if self.tabs.count() == 1:
            # reset this tab to start page instead of closing
            t = self.tabs.widget(idx)
            if isinstance(t, BrowserTab):
                logger.debug("Resetting lone tab to start page")
                t.go_home()
                self.tabs.setTabText(idx, "New Tab")
                self.tabs.setTabIcon(idx, QtGui.QIcon())
                self.addr.clear()
            return
        w = self.tabs.widget(idx)
        self.tabs.removeTab(idx)
        if w: w.deleteLater()

    def _go_home_current(self):
        t = self._cur_tab()
        if t:
            logger.debug("Returning current tab to start page")
            t.go_home()
        self.addr.clear()
        self.tabs.setTabText(self.tabs.currentIndex(), "New Tab")
        self.tabs.setTabIcon(self.tabs.currentIndex(), QtGui.QIcon())

    def _pin_current(self):
        v = self._cur_view()
        if not v:
            logger.warning("Pin requested but no active web view")
            return
        title = v.title() or "Pinned"
        url = v.url().toString()
        logger.info("Pinning current page: %s (%s)", title, url)
        self.pins.pin_current(title, url)

    def _toggle_axiom(self):
        if not hasattr(self, 'splitter'):
            self.axiom.setVisible(not self.axiom.isVisible())
            return
        if self.axiom.isVisible():
            self.axiom.hide()
            sizes = self.splitter.sizes()
            if len(sizes) == 3:
                self.splitter.setSizes([sizes[0], sizes[1] + sizes[2], 0])
        else:
            self.axiom.show()
            sizes = self.splitter.sizes()
            if len(sizes) == 3:
                available = max(200, sizes[1])
                panel = max(280, min(400, available // 3))
                self.splitter.setSizes([sizes[0], max(320, available - panel), panel])

