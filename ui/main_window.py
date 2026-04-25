import os
import platform
from PyQt5 import QtWidgets, QtCore, QtGui
from .styles import apply_theme
from .sidebar import Sidebar
from .settings_dialog import SettingsDialog
from core.app_settings import settings
from core.jobs import JobManager
from core.notifications import notifier
from core.logging_utils import get_logger

from tools.stitch_up import StitchUpPage
from tools.convert import ConvertPage
from tools.transcribe import TranscribePage
from tools.channel_identity import ChannelIdentityPage
from tools.more import MorePage
from tools.mouse_automation import MouseAutomationPage
from tools.api_storage import APIStoragePage
from tools.automation_editor import AutomationEditorPage
from tools.captions import CaptionsPage
from tools.scene_images import SceneImagesPage
from tools.notifications import NotificationsPage
from tools.sound_waves import SoundWavesPage
from tools.translate import TranslatePage
from tools.brave_automation import BraveAutomationPage
from tools.motion_graphics import MotionGraphicsPage
from tools.footage import FootagePage
from tools.jobs_center import JobsCenterPage
from tools.browse import BrowsePage
from tools.script_writer import ScriptWriterPage


logger = get_logger(__name__)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("Initialising MainWindow UI")
        logger.debug("Applying default window sizing and theme")
        self.setWindowTitle("WeJaWi")
        self.resize(1000, 620)
        self.setMinimumSize(880, 560)

        self.tray_icon = None
        self._tray_menu = None

        self._settings = settings
        self._setup_menu()
        self._apply_theme()

        wrapper = QtWidgets.QWidget()
        self.setCentralWidget(wrapper)
        h = QtWidgets.QHBoxLayout(wrapper)
        # Remove outer margins to eliminate extra border feeling
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        

        # Sidebar
        self.sidebar = Sidebar()
        h.addWidget(self.sidebar, 0)

        # Content stack (purple canvas)
        self.stack = QtWidgets.QStackedWidget(objectName="ContentArea")
        h.addWidget(self.stack, 1)

        # Pages (placeholders for now)
        self.pages = {
            "browse":BrowsePage(),
            "footage": FootagePage(),
            "stitch": StitchUpPage(),
            "motion_graphics": MotionGraphicsPage(),
            "convert": ConvertPage(),
            "transcribe": TranscribePage(),
            "channel_identity":ChannelIdentityPage(),
            "mouse_auto": MouseAutomationPage(),
            "script_writer": ScriptWriterPage(),
            "api_storage": APIStoragePage(),
            "automation_editor": AutomationEditorPage(),
            "captions": CaptionsPage(),
            "jobs_center": JobsCenterPage(),
            "scene_images": SceneImagesPage(),
            "more": MorePage(),
            "notifications": NotificationsPage(),
            "sound_waves": SoundWavesPage(),
            "brave_auto": BraveAutomationPage(),
        }
        for key, page in self.pages.items():
            page.setObjectName(f"page_{key}")
            self.stack.addWidget(page)

        browse_page = self.pages.get('browse')
        if hasattr(browse_page, 'toolRequested'):
            browse_page.toolRequested.connect(self._handle_tool_request)

        # Connect nav
        self.sidebar.navSelected.connect(self.route_to)

        # Start on first tool (Browse)
        self.route_to("browse")

        # Try to enable dark title bar on Windows (native bar)
        self._enable_windows_dark_titlebar()
        self._init_tray()

        self.pages["translate"] = TranslatePage()
        translate_page = self.pages["translate"]
        translate_page.setObjectName("page_translate")
        self.stack.addWidget(translate_page)

        self._sync_theme_actions()

    def _setup_menu(self):
        logger.debug("Building menu bar and theme actions")
        bar = self.menuBar()
        # Use the native macOS global menu bar; fall back to in-window bar elsewhere.
        bar.setNativeMenuBar(platform.system() == "Darwin")

        settings_menu = bar.addMenu("&Settings")

        self.act_theme_system = QtWidgets.QAction("System default", self, checkable=True)
        self.act_theme_light = QtWidgets.QAction("Light mode", self, checkable=True)
        self.act_theme_dark = QtWidgets.QAction("Dark mode", self, checkable=True)

        theme_group = QtWidgets.QActionGroup(self)
        for act in (self.act_theme_system, self.act_theme_light, self.act_theme_dark):
            theme_group.addAction(act)
            settings_menu.addAction(act)

        self.act_theme_system.triggered.connect(lambda _: self._set_theme("system"))
        self.act_theme_light.triggered.connect(lambda _: self._set_theme("light"))
        self.act_theme_dark.triggered.connect(lambda _: self._set_theme("dark"))

        settings_menu.addSeparator()

        prefs_action = QtWidgets.QAction("Preferences...", self)
        prefs_action.setShortcut(QtGui.QKeySequence("Ctrl+,"))
        prefs_action.triggered.connect(self._open_settings)
        settings_menu.addAction(prefs_action)

    def route_to(self, key: str):
        if key != 'settings' and hasattr(self, 'sidebar'):
            self.sidebar.select(key)
        if key == "settings":
            self._open_settings()
            return
        page = self.pages.get(key)
        if page is None:
            logger.warning("Navigation key '%s' is not registered", key)
            return
        self.stack.setCurrentWidget(page)
        logger.debug("Switched to page %s", key)

    def _handle_tool_request(self, tool_key: str):
        if not tool_key:
            return
        if tool_key not in self.pages:
            logger.warning("Browse requested unknown tool '%s'", tool_key)
            return
        logger.info("Routing from BrowsePage to %s", tool_key)
        self.route_to(tool_key)

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self._apply_theme()
            self._sync_theme_actions()

    def _set_theme(self, theme: str):
        data = self._settings.data
        if data.ui.theme == theme:
            return
        data.ui.theme = theme
        self._settings.save()
        self._apply_theme()
        self._sync_theme_actions()

    def _apply_theme(self):
        theme = (self._settings.data.ui.theme or "system").lower()
        apply_theme(self, theme)

    def _sync_theme_actions(self):
        theme = (self._settings.data.ui.theme or "system").lower()
        mapping = {
            "system": self.act_theme_system,
            "light": self.act_theme_light,
            "dark": self.act_theme_dark,
        }
        for key, act in mapping.items():
            act.setChecked(theme == key)

    def _enable_windows_dark_titlebar(self):
        try:
            if platform.system() != "Windows":
                return
            import ctypes
            from ctypes import wintypes
            hwnd = int(self.winId())

            # Windows 10/11: try both attribute IDs for compatibility
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Win 11/10 1903+
            DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19  # Win 10 1809
            value = ctypes.c_int(1)
            dwmset = ctypes.windll.dwmapi.DwmSetWindowAttribute
            # Try modern first, then fallback
            for attr in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD):
                dwmset(wintypes.HWND(hwnd), ctypes.c_int(attr),
                       ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            # Silently ignore if not supported
            pass
    
    def _init_tray(self):
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            notifier.register_channel_callback("windows", None)
            return
        if self.tray_icon is None:
            self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "icons", "home.png"))
        icon = QtGui.QIcon(icon_path) if os.path.isfile(icon_path) else self.windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QtWidgets.QStyle.SP_DesktopIcon)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("WeJaWi")
        menu = QtWidgets.QMenu(self)
        show_action = menu.addAction("Open WeJaWi")
        show_action.triggered.connect(self._restore_from_tray)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(QtWidgets.QApplication.instance().quit)
        self.tray_icon.setContextMenu(menu)
        self._tray_menu = menu
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()
        notifier.register_channel_callback("windows", self._show_windows_notification)

    def _on_tray_activated(self, reason):
        if reason in (QtWidgets.QSystemTrayIcon.Trigger, QtWidgets.QSystemTrayIcon.DoubleClick):
            self._restore_from_tray()

    def _restore_from_tray(self):
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _show_windows_notification(self, title: str, message: str, payload: dict):
        if not self.tray_icon or not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        options = (payload or {}).get("options") or {}
        duration_ms = 0 if options.get("keep_on_screen") else max(1, int(options.get("duration_sec", 8) or 1)) * 1000
        category = (options.get("category") or "info").lower()
        icon_map = {
            "warning": QtWidgets.QSystemTrayIcon.Warning,
            "error": QtWidgets.QSystemTrayIcon.Critical,
            "success": QtWidgets.QSystemTrayIcon.Information,
            "info": QtWidgets.QSystemTrayIcon.Information,
        }
        icon_type = icon_map.get(category, QtWidgets.QSystemTrayIcon.Information)
        display_title = title or "WeJaWi"
        display_body = (message or "").strip()
        if not display_body:
            display_body = payload.get("raw_body") or payload.get("tool_label") or payload.get("tool") or ""
        def _show():
            if not self.tray_icon:
                return
            self.tray_icon.showMessage(display_title, display_body or " ", icon_type, duration_ms)
            if options.get("play_sound", True):
                QtWidgets.QApplication.beep()
        QtCore.QTimer.singleShot(0, _show)

    def closeEvent(self, e):
        # let pages stop their workers
        for page in getattr(self, "pages", {}).values():
            if hasattr(page, "on_app_close"):
                try:
                    page.on_app_close()
                except Exception:
                    pass
        try:
            JobManager.instance().shutdown()
        except Exception:
            pass
        try:
            notifier.register_channel_callback("windows", None)
        except Exception:
            pass
        if isinstance(getattr(self, "tray_icon", None), QtWidgets.QSystemTrayIcon):
            self.tray_icon.hide()
            self.tray_icon.deleteLater()
            self.tray_icon = None
            self._tray_menu = None
        super().closeEvent(e)
