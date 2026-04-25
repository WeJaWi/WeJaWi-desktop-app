import threading
from typing import Dict, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from tools.llm_providers import (
    load_api_keys,
    save_api_keys,
    provider_from_choice,
    ChatMessage,
    _keys_path,
)


# ── service registry ──────────────────────────────────────────────────────────

SERVICES = [
    {
        "key":   "openai",
        "label": "OpenAI  (ChatGPT / GPT-4o)",
        "icon":  "🤖",
        "hint":  "sk-…",
        "docs":  "platform.openai.com/api-keys",
        "test":  "openai",
    },
    {
        "key":   "xai",
        "label": "xAI  (Grok)",
        "icon":  "⚡",
        "hint":  "xai-…",
        "docs":  "console.x.ai",
        "test":  "xai",
    },
    {
        "key":   "anthropic",
        "label": "Anthropic  (Claude)",
        "icon":  "🧠",
        "hint":  "sk-ant-…",
        "docs":  "console.anthropic.com/settings/keys",
        "test":  "anthropic",
    },
    {
        "key":   "kimi",
        "label": "Kimi  (Moonshot AI)",
        "icon":  "🌙",
        "hint":  "sk-…",
        "docs":  "platform.moonshot.cn",
        "test":  "kimi",
    },
    {
        "key":   "heygen",
        "label": "HeyGen  (AI Avatars / Hyperframes)",
        "icon":  "🎭",
        "hint":  "Paste your HeyGen API key",
        "docs":  "app.heygen.com/settings",
        "test":  None,  # no auto-test (HeyGen has a different auth model)
    },
    {
        "key":   "youtube",
        "label": "YouTube Data API v3",
        "icon":  "▶️",
        "hint":  "AIza…",
        "docs":  "console.cloud.google.com",
        "test":  None,
    },
]


class _TestWorker(QtCore.QThread):
    result = QtCore.pyqtSignal(bool, str)   # success, message

    def __init__(self, provider_key: str, api_key: str, parent=None):
        super().__init__(parent)
        self.provider_key = provider_key
        self.api_key      = api_key

    def run(self):
        try:
            prov = provider_from_choice(
                self.provider_key,
                keys={self.provider_key: self.api_key},
            )
            prov.test()
            self.result.emit(True, "Connection successful ✓")
        except Exception as e:
            self.result.emit(False, str(e))


class _ServiceCard(QtWidgets.QFrame):
    """One card per API service."""

    saved    = QtCore.pyqtSignal(str, str)   # key, value
    tested   = QtCore.pyqtSignal(str, bool)  # key, success

    def __init__(self, svc: dict, current_value: str, parent=None):
        super().__init__(parent)
        self.svc = svc
        self._test_thread: Optional[_TestWorker] = None
        self.setObjectName("ServiceCard")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self._build(current_value)

    def _build(self, value: str):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header row: icon + label + status badge
        hdr = QtWidgets.QHBoxLayout()
        icon_label = QtWidgets.QLabel(f"{self.svc['icon']}  {self.svc['label']}")
        icon_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        hdr.addWidget(icon_label, 1)

        self.status_badge = QtWidgets.QLabel()
        self._set_badge(bool(value))
        hdr.addWidget(self.status_badge)
        layout.addLayout(hdr)

        # Key input row
        key_row = QtWidgets.QHBoxLayout()
        self.key_edit = QtWidgets.QLineEdit(value)
        self.key_edit.setPlaceholderText(self.svc["hint"])
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_edit.textChanged.connect(self._on_text_changed)

        self.eye_btn = QtWidgets.QPushButton("👁")
        self.eye_btn.setFixedWidth(34)
        self.eye_btn.setCheckable(True)
        self.eye_btn.setToolTip("Show / hide key")
        self.eye_btn.toggled.connect(self._toggle_visibility)

        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.eye_btn)
        layout.addLayout(key_row)

        # Action row: save + test + clear
        act_row = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save")
        self.save_btn.setFixedWidth(72)
        self.save_btn.clicked.connect(self._on_save)

        if self.svc.get("test"):
            self.test_btn = QtWidgets.QPushButton("Test connection")
            self.test_btn.clicked.connect(self._on_test)
            act_row.addWidget(self.test_btn)

        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.setFixedWidth(60)
        self.clear_btn.clicked.connect(self._on_clear)

        self.feedback_label = QtWidgets.QLabel("")
        self.feedback_label.setStyleSheet("font-size: 11px;")

        act_row.addWidget(self.save_btn)
        act_row.addWidget(self.clear_btn)
        act_row.addStretch(1)
        act_row.addWidget(self.feedback_label)
        layout.addLayout(act_row)

    def _set_badge(self, is_set: bool):
        if is_set:
            self.status_badge.setText("● Set")
            self.status_badge.setStyleSheet("color: #22c55e; font-weight: bold;")
        else:
            self.status_badge.setText("○ Not set")
            self.status_badge.setStyleSheet("color: #94a3b8; font-weight: normal;")

    def _on_text_changed(self):
        self._set_badge(bool(self.key_edit.text().strip()))
        self.feedback_label.setText("")

    def _toggle_visibility(self, checked: bool):
        mode = QtWidgets.QLineEdit.Normal if checked else QtWidgets.QLineEdit.Password
        self.key_edit.setEchoMode(mode)

    def _on_save(self):
        val = self.key_edit.text().strip()
        save_api_keys({self.svc["key"]: val})
        self._set_badge(bool(val))
        self.feedback_label.setText("Saved ✓")
        self.feedback_label.setStyleSheet("color: #22c55e; font-size: 11px;")
        self.saved.emit(self.svc["key"], val)

    def _on_clear(self):
        self.key_edit.clear()
        save_api_keys({self.svc["key"]: ""})
        self._set_badge(False)
        self.feedback_label.setText("Cleared")
        self.feedback_label.setStyleSheet("color: #94a3b8; font-size: 11px;")

    def _on_test(self):
        val = self.key_edit.text().strip()
        if not val:
            self.feedback_label.setText("Enter a key first")
            self.feedback_label.setStyleSheet("color: #f59e0b; font-size: 11px;")
            return
        self.feedback_label.setText("Testing…")
        self.feedback_label.setStyleSheet("color: #a78bfa; font-size: 11px;")
        if hasattr(self, "test_btn"):
            self.test_btn.setEnabled(False)

        self._test_thread = _TestWorker(self.svc["key"], val, self)
        self._test_thread.result.connect(self._on_test_done)
        self._test_thread.start()

    def _on_test_done(self, success: bool, msg: str):
        if hasattr(self, "test_btn"):
            self.test_btn.setEnabled(True)
        color = "#22c55e" if success else "#ef4444"
        self.feedback_label.setText(msg[:80])
        self.feedback_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self.tested.emit(self.svc["key"], success)


class APIStoragePage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        root.addWidget(QtWidgets.QLabel("API Storage", objectName="PageTitle"))

        sub = QtWidgets.QLabel(
            "API keys are stored locally at: " + _keys_path() + "\n"
            "Keys saved here are used automatically by Script Writer, Translate, and other AI tools."
        )
        sub.setWordWrap(True)
        sub.setObjectName("PageSubtitle")
        root.addWidget(sub)

        # Action bar
        act_row = QtWidgets.QHBoxLayout()
        btn_save_all = QtWidgets.QPushButton("Save all")
        btn_save_all.clicked.connect(self._save_all)
        btn_reload = QtWidgets.QPushButton("Reload from disk")
        btn_reload.clicked.connect(self._reload)
        act_row.addWidget(btn_save_all)
        act_row.addWidget(btn_reload)
        act_row.addStretch(1)
        root.addLayout(act_row)

        # Scrollable cards area
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        self._cards_layout = QtWidgets.QVBoxLayout(inner)
        self._cards_layout.setSpacing(10)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        self._cards: Dict[str, _ServiceCard] = {}
        self._reload()

    def _reload(self):
        # Clear existing cards
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        keys = load_api_keys()
        for svc in SERVICES:
            card = _ServiceCard(svc, keys.get(svc["key"], ""), self)
            self._cards_layout.addWidget(card)
            self._cards[svc["key"]] = card

        self._cards_layout.addStretch(1)

    def _save_all(self):
        updates = {key: card.key_edit.text().strip()
                   for key, card in self._cards.items()}
        save_api_keys(updates)
        for card in self._cards.values():
            card.feedback_label.setText("Saved ✓")
            card.feedback_label.setStyleSheet("color: #22c55e; font-size: 11px;")
