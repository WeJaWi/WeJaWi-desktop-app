from PyQt5 import QtWidgets, QtCore, QtGui

# (key, glyph, label) — glyphs render via system emoji/SF on macOS for crisp Apple-native look.
NAV_ITEMS = [
    ('browse',            '\U0001F310', 'Browser'),          # 🌐
    ('transcribe',        '\U0001F399', 'Transcribe'),       # 🎙
    ('captions',          '\U0001F4AC', 'Captions'),         # 💬
    ('stitch',            '\u2702',     'Stitch Up'),        # ✂
    ('motion_graphics',   '\U0001F39E', 'Motion Graphics'),  # 🎞
    ('convert',           '\U0001F501', 'Convert'),          # 🔁
    ('sound_waves',       '\U0001F39A', 'Sound Waves'),      # 🎚
    ('scene_images',      '\U0001F3AC', 'Scenes + Images'),  # 🎬
    ('footage',           '\U0001F4FC', 'Footage'),          # 📼
    ('script_writer',     '\u270D',     'Script Writer'),    # ✍
    ('translate',         '\U0001F310', 'Translate'),        # 🌐 (alt globe)
    ('channel_identity',  '\U0001F4AB', 'Channel Identity'), # 💫
    ('jobs_center',       '\U0001F4CB', 'Jobs Center'),      # 📋
    ('brave_auto',        '\U0001F981', 'Brave Automation'), # 🦁
    ('mouse_auto',        '\U0001F5B1', 'Mouse Automation'), # 🖱
    ('automation_editor', '\u2699',     'Automation Editor'),# ⚙
    ('api_storage',       '\U0001F511', 'API Storage'),      # 🔑
    ('more',              '\u2026',     'More'),             # …
]

BOTTOM_ITEMS = [
    ('notifications', '\U0001F514', 'Notifications'),  # 🔔
    ('settings',      '\u2699',     'Settings'),       # ⚙
]


class Sidebar(QtWidgets.QFrame):
    navSelected = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(0)

        # Brand header
        brand = QtWidgets.QLabel("WeJaWi")
        brand.setObjectName("Brand")
        root.addWidget(brand)

        subtitle = QtWidgets.QLabel("Studio")
        subtitle.setObjectName("BrandSubtitle")
        root.addWidget(subtitle)

        # Subtle accent divider
        divider = QtWidgets.QFrame()
        divider.setObjectName("SidebarDivider")
        divider.setFrameShape(QtWidgets.QFrame.NoFrame)
        divider.setFixedHeight(1)
        root.addWidget(divider)

        # Scrollable nav area (in case sidebar gets cramped on small windows)
        nav_container = QtWidgets.QWidget()
        nav_layout = QtWidgets.QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 6, 0, 6)
        nav_layout.setSpacing(0)

        for key, glyph, label in NAV_ITEMS:
            btn = self._make_nav_btn(glyph, label)
            btn.setProperty("key", key)
            self._group.addButton(btn)
            nav_layout.addWidget(btn)

        nav_layout.addStretch(1)

        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("SidebarScroll")
        scroll.setWidget(nav_container)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        nav_container.setStyleSheet("background: transparent;")
        root.addWidget(scroll, 1)

        # Bottom bar (notifications + settings)
        bottom_w = QtWidgets.QWidget(objectName="BottomBar")
        bottom = QtWidgets.QHBoxLayout(bottom_w)
        bottom.setContentsMargins(8, 8, 8, 10)
        bottom.setSpacing(6)

        self._bottom_map = {}
        for key, glyph, tooltip in BOTTOM_ITEMS:
            b = self._make_bottom_btn(glyph, tooltip)
            b.setProperty("key", key)
            bottom.addWidget(b)
            self._bottom_map[key] = b
        bottom.addStretch(1)

        root.addWidget(bottom_w)

        # Signals
        self._group.buttonClicked.connect(self._on_clicked)
        for b in self._bottom_map.values():
            b.clicked.connect(self._on_bottom_clicked)

        # Default selection
        if self._group.buttons():
            self._group.buttons()[0].setChecked(True)

    def select(self, key: str) -> None:
        for btn in self._group.buttons():
            if btn.property("key") == key:
                btn.setChecked(True)
                return

    def _make_nav_btn(self, glyph: str, label: str) -> QtWidgets.QPushButton:
        # Fixed-width glyph column keeps labels aligned even with mixed-width emoji.
        btn = QtWidgets.QPushButton(f"  {glyph}    {label}")
        btn.setCheckable(True)
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        btn.setObjectName("SideBtn")
        btn.setProperty("class", "SideBtn")
        btn.setMinimumHeight(38)
        return btn

    def _make_bottom_btn(self, glyph: str, tooltip: str) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(glyph)
        btn.setCheckable(False)
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        btn.setObjectName("BottomBtn")
        btn.setProperty("class", "BottomBtn")
        btn.setToolTip(tooltip)
        return btn

    def _on_clicked(self, btn: QtWidgets.QAbstractButton):
        key = btn.property("key")
        if key:
            self.navSelected.emit(key)

    def _on_bottom_clicked(self):
        btn = self.sender()
        key = btn.property("key")
        if key:
            self.navSelected.emit(key)
