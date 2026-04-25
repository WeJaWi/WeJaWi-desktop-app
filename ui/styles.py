"""Application-wide Qt styles and theme helpers."""

from __future__ import annotations

from PyQt5 import QtGui, QtWidgets

LIGHT_QSS = """
QWidget { font-family: 'Inter', -apple-system, 'SF Pro Text', 'Segoe UI', system-ui, sans-serif; font-size: 14px; color: #0b0b14; }
QMainWindow { background: #fafaff; }

#Sidebar {
    background: #ffffff;
    border-right: 1px solid #ece8f7;
    min-width: 220px;
    max-width: 220px;
}
#Brand {
    font-weight: 800;
    font-size: 26px;
    padding: 18px 18px 2px 18px;
    color: #0b0b14;
    letter-spacing: 0.3px;
}
#BrandSubtitle {
    font-size: 11px;
    color: #7c3aed;
    padding: 0 18px 14px 18px;
    letter-spacing: 2px;
    font-weight: 600;
    text-transform: uppercase;
}
#SidebarDivider {
    background: #ece8f7;
    max-height: 1px;
    margin: 4px 14px;
}
.SideBtn {
    text-align: left;
    padding: 10px 14px;
    border: none;
    border-radius: 10px;
    margin: 3px 10px;
    color: #2a2240;
    background: transparent;
    font-size: 14px;
}
.SideBtn:hover { background: #f5f1ff; color: #0b0b14; }
.SideBtn:checked {
    background: #f1ebff;
    color: #5b21b6;
    font-weight: 700;
    border-left: 3px solid #7c3aed;
    padding-left: 11px;
}

#BottomBar {
    padding: 10px;
    border-top: 1px solid #ece8f7;
}
.BottomBtn {
    width: 40px; height: 40px;
    border-radius: 10px;
    border: none;
    margin: 0 6px;
    background: #f5f1ff;
    color: #0b0b14;
    font-size: 16px;
}
.BottomBtn:hover { background: #ebe2ff; color: #5b21b6; }
.BottomBtn:checked { background: #e2d4ff; color: #5b21b6; }

#ComingSoon { color: #5b5870; font-size: 16px; padding: 0 16px 16px 16px; }
#ContentArea { background: #fafaff; }
#PageTitle { color: #0b0b14; font-size: 22px; font-weight: 800; padding: 4px 0 8px 0; }

QGroupBox { background: #ffffff; border: 1px solid #ece8f7; border-radius: 10px; margin-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #5b5870; font-weight: 600; background: #ffffff; }
QFrame#CardFrame { background: #ffffff; border: 1px solid #ece8f7; border-radius: 12px; }
QFrame#Tile { background: #ffffff; border: 1px solid #ece8f7; border-radius: 12px; }
QFrame#Tile:hover { border-color: #7c3aed; }
QFrame#Tile QLabel#Meta { color: #5b5870; font-size: 12px; }
QFrame#FootagePreviewPane { background: #fafaff; border: 1px solid #ece8f7; border-radius: 12px; }
QFrame#FootagePreviewPane QPushButton { min-height: 30px; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QComboBox { border-radius: 8px; border: 1px solid #ece8f7; padding: 8px; background: #ffffff; color: #0b0b14; selection-background-color: #7c3aed; selection-color: #ffffff; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus, QComboBox:focus { border: 1px solid #7c3aed; }
QPushButton { border-radius: 8px; border: 1px solid #ece8f7; padding: 8px 14px; background: #ffffff; color: #0b0b14; }
QPushButton:hover { background: #f5f1ff; border-color: #d6c8ff; }
QPushButton:pressed { background: #ebe2ff; }
QPushButton:disabled { background: #f7f7fa; color: #b7b3c7; border-color: #ece8f7; }
QProgressBar { border: 1px solid #ece8f7; border-radius: 8px; background: #ffffff; height: 18px; text-align: center; color: #0b0b14; }
QProgressBar::chunk { background-color: #7c3aed; border-radius: 8px; }
QSplitter::handle { background: #ece8f7; width: 6px; }
QSplitter::handle:hover { background: #d6c8ff; }

QTableWidget, QTreeWidget, QTreeView, QListWidget {
    background: #ffffff;
    border: 1px solid #ece8f7;
    border-radius: 8px;
    color: #0b0b14;
    alternate-background-color: #f5f1ff;
}
QAbstractItemView::item:selected {
    background: #f1ebff;
    color: #5b21b6;
}
QHeaderView::section {
    background: #f5f1ff;
    color: #0b0b14;
    border: none;
    border-right: 1px solid #ece8f7;
    padding: 6px 10px;
}
QHeaderView::section:last { border-right: none; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 6px 4px 6px 0; }
QScrollBar::handle:vertical { background: #d6c8ff; min-height: 28px; border-radius: 6px; }
QScrollBar::handle:vertical:hover { background: #b89cff; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0 6px 4px 6px; }
QScrollBar::handle:horizontal { background: #d6c8ff; min-width: 28px; border-radius: 6px; }
QScrollBar::handle:horizontal:hover { background: #b89cff; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }

QMenuBar { background: #ffffff; color: #0b0b14; border-bottom: 1px solid #ece8f7; }
QMenuBar::item { background: transparent; padding: 6px 12px; }
QMenuBar::item:selected { background: #f1ebff; color: #5b21b6; }
QMenu { background: #ffffff; color: #0b0b14; border: 1px solid #ece8f7; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #f1ebff; color: #5b21b6; }
QToolTip { background: #0b0b14; color: #ffffff; border: 1px solid #7c3aed; padding: 4px 8px; border-radius: 6px; }

QTabBar::tab {
    background: #f5f1ff;
    border: 1px solid #ece8f7;
    padding: 6px 12px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
}
QTabBar::tab:selected { background: #ffffff; color: #5b21b6; font-weight: 600; }
QTabBar::tab:hover { background: #ebe2ff; }
QTabWidget::pane { border: 1px solid #ece8f7; border-radius: 8px; }

#DropZone { background: #ffffff; border: 2px dashed #d6c8ff; border-radius: 12px; min-height: 140px; }
#DropZone:hover { background: #f5f1ff; border-color: #7c3aed; }
#DropZoneText { color: #5b5870; }

#BrowsePage { background: #fafaff; color: #0b0b14; }
#BrowseToolbar { background: #ffffff; border-bottom: 1px solid #ece8f7; }
#BrowseToolbar QToolButton { border: none; padding: 4px; border-radius: 8px; }
#BrowseToolbar QToolButton:hover { background: #f1ebff; }
#BrowseAddressBar { background: #ffffff; color: #0b0b14; border: 1px solid #ece8f7; border-radius: 14px; padding: 10px 14px; font-size: 14px; }
#BrowseGoButton { background: #7c3aed; color: #ffffff; border: none; border-radius: 14px; padding: 10px 22px; font-weight: 600; }
#BrowseGoButton:hover { background: #6d28d9; }
#BrowsePinButton { background: #f5f1ff; color: #5b21b6; border: 1px solid #ece8f7; border-radius: 14px; padding: 10px 18px; font-weight: 600; }
#BrowsePinButton:hover { background: #ebe2ff; }
#BrowseTabs { background: transparent; border: none; }
#BrowseTabs::tab { background: #ffffff; color: #0b0b14; border: none; padding: 8px 14px; border-radius: 10px 10px 0 0; font-weight: 600; }
#BrowseTabs::tab:hover { background: #f5f1ff; }
#BrowseTabs::tab:selected { background: #ffffff; color: #5b21b6; }
#BrowsePinBar { background: #fafaff; border-right: 1px solid #ece8f7; }
#BrowsePinBar QToolButton { border: none; border-radius: 12px; padding: 4px; }
#BrowsePinBar QToolButton:hover { background: #f1ebff; }
#BrowsePinHeader { font-weight: 700; font-size: 11px; color: #7c3aed; letter-spacing: 1px; text-transform: uppercase; }
#BrowseHeroCard { background: #ffffff; border: 1px solid #ece8f7; border-radius: 22px; }
#BrowseHeroTitle { font-size: 26px; font-weight: 700; color: #0b0b14; }
#BrowseHeroSubtitle { color: #5b5870; font-size: 14px; }
#BrowseSearchWrap { background: #fafaff; border: 1px solid #ece8f7; border-radius: 16px; }
#BrowseHeroSearchEdit { background: transparent; border: none; font-size: 15px; padding: 4px 0; color: #0b0b14; }
#BrowseHeroSearchButton { background: #7c3aed; color: #ffffff; border: none; border-radius: 14px; padding: 10px 20px; font-weight: 600; }
#BrowseHeroSearchButton:hover { background: #6d28d9; }
#BrowseActionsFrame { background: #ffffff; border: 1px solid #ece8f7; border-radius: 18px; }
#BrowseQuickActionsLabel { font-weight: 700; color: #0b0b14; }
#BrowseQuickActionButton { background: #f5f1ff; color: #5b21b6; border: 1px solid #ece8f7; border-radius: 12px; padding: 10px 18px; font-size: 13px; font-weight: 600; }
#BrowseQuickActionButton:hover { background: #ebe2ff; border-color: #d6c8ff; }
#BrowseGridFrame { background: #ffffff; border: 1px solid #ece8f7; border-radius: 20px; }
#BrowseGridHeading { font-weight: 700; font-size: 16px; color: #0b0b14; }
#BrowseTile { background: #ffffff; border: 1px solid #ece8f7; border-radius: 20px; text-align: left; }
#BrowseTile:hover { border-color: #7c3aed; }
#BrowseTileTitle { font-weight: 700; font-size: 17px; color: #0b0b14; }
#BrowseTileUrl { color: #5b5870; font-size: 13px; }
#BrowseAddTile { background: #f5f1ff; border: 1px dashed #d6c8ff; border-radius: 20px; color: #5b21b6; font-weight: 600; }
#BrowseAddTile:hover { background: #ebe2ff; border-color: #7c3aed; }
#BrowseEmptyLabel { color: #5b5870; font-size: 13px; }
#BrowseSplitter::handle { background: #ece8f7; width: 6px; }
#BrowseSplitter::handle:hover { background: #d6c8ff; }
"""

DARK_QSS = """
QWidget { font-family: 'Inter', -apple-system, 'SF Pro Text', 'Segoe UI', system-ui, sans-serif; font-size: 14px; color: #f5f3ff; }
QMainWindow { background: #0b0b14; }

#Sidebar {
    background: #08080f;
    border-right: 1px solid #1a1530;
    min-width: 220px;
    max-width: 220px;
}
#Brand {
    font-weight: 800;
    font-size: 26px;
    padding: 18px 18px 2px 18px;
    color: #ffffff;
    letter-spacing: 0.3px;
}
#BrandSubtitle {
    font-size: 11px;
    color: #a855f7;
    padding: 0 18px 14px 18px;
    letter-spacing: 2px;
    font-weight: 600;
    text-transform: uppercase;
}
#SidebarDivider {
    background: #1a1530;
    max-height: 1px;
    margin: 4px 14px;
}
.SideBtn {
    text-align: left;
    padding: 10px 14px;
    border: none;
    border-radius: 10px;
    margin: 3px 10px;
    color: #c8bfe0;
    background: transparent;
    font-size: 14px;
}
.SideBtn:hover { background: #1a1530; color: #ffffff; }
.SideBtn:checked {
    background: #2a1a4a;
    color: #ffffff;
    font-weight: 700;
    border-left: 3px solid #a855f7;
    padding-left: 11px;
}

#BottomBar {
    padding: 10px;
    border-top: 1px solid #1a1530;
}
.BottomBtn {
    width: 40px; height: 40px;
    border-radius: 10px;
    border: none;
    margin: 0 6px;
    background: #13121f;
    color: #f5f3ff;
    font-size: 16px;
}
.BottomBtn:hover { background: #1a1530; color: #ffffff; }
.BottomBtn:checked { background: #2a1a4a; color: #a855f7; }

#ComingSoon { color: #a89cc9; font-size: 16px; padding: 0 16px 16px 16px; }
#ContentArea { background: #0b0b14; }
#PageTitle { color: #ffffff; font-size: 22px; font-weight: 800; padding: 4px 0 8px 0; }

QGroupBox { background: #13121f; border: 1px solid #1a1530; border-radius: 10px; margin-top: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #a89cc9; font-weight: 600; background: #13121f; }
QFrame#CardFrame { background: #13121f; border: 1px solid #1a1530; border-radius: 12px; }
QFrame#Tile { background: #13121f; border: 1px solid #1a1530; border-radius: 12px; }
QFrame#Tile:hover { border-color: #a855f7; }
QFrame#Tile QLabel#Meta { color: #a89cc9; font-size: 12px; }
QFrame#FootagePreviewPane { background: #0b0b14; border: 1px solid #1a1530; border-radius: 12px; }
QFrame#FootagePreviewPane QPushButton { min-height: 30px; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QComboBox { border-radius: 8px; border: 1px solid #1a1530; padding: 8px; background: #13121f; color: #f5f3ff; selection-background-color: #a855f7; selection-color: #ffffff; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus, QComboBox:focus { border: 1px solid #a855f7; }
QPushButton { border-radius: 8px; border: 1px solid #1a1530; padding: 8px 14px; background: #13121f; color: #f5f3ff; }
QPushButton:hover { background: #1a1530; border-color: #2a1a4a; color: #ffffff; }
QPushButton:pressed { background: #2a1a4a; }
QPushButton:disabled { background: #0e0d18; color: #5d5778; border-color: #1a1530; }
QProgressBar { border: 1px solid #1a1530; border-radius: 8px; background: #13121f; height: 18px; text-align: center; color: #ffffff; }
QProgressBar::chunk { background-color: #a855f7; border-radius: 8px; }
QSplitter::handle { background: #1a1530; width: 6px; }
QSplitter::handle:hover { background: #2a1a4a; }

QTableWidget, QTreeWidget, QTreeView, QListWidget {
    background: #13121f;
    border: 1px solid #1a1530;
    border-radius: 8px;
    color: #f5f3ff;
    alternate-background-color: #161425;
}
QAbstractItemView::item:selected {
    background: #2a1a4a;
    color: #ffffff;
}
QHeaderView::section {
    background: #1a1530;
    color: #f5f3ff;
    border: none;
    border-right: 1px solid #2a1a4a;
    padding: 6px 10px;
}
QHeaderView::section:last { border-right: none; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 6px 4px 6px 0; }
QScrollBar::handle:vertical { background: #2a1a4a; min-height: 28px; border-radius: 6px; }
QScrollBar::handle:vertical:hover { background: #3d2466; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0 6px 4px 6px; }
QScrollBar::handle:horizontal { background: #2a1a4a; min-width: 28px; border-radius: 6px; }
QScrollBar::handle:horizontal:hover { background: #3d2466; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }

QMenuBar { background: #08080f; color: #f5f3ff; border-bottom: 1px solid #1a1530; }
QMenuBar::item { background: transparent; padding: 6px 12px; }
QMenuBar::item:selected { background: #1a1530; color: #ffffff; }
QMenu { background: #13121f; color: #f5f3ff; border: 1px solid #1a1530; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #2a1a4a; color: #ffffff; }
QToolTip { background: #2a1a4a; color: #ffffff; border: 1px solid #a855f7; padding: 4px 8px; border-radius: 6px; }

QTabBar::tab {
    background: #13121f;
    border: 1px solid #1a1530;
    padding: 6px 12px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
}
QTabBar::tab:selected { background: #0b0b14; color: #a855f7; font-weight: 600; }
QTabBar::tab:hover { background: #1a1530; }
QTabWidget::pane { border: 1px solid #1a1530; border-radius: 8px; }

#DropZone { background: #13121f; border: 2px dashed #2a1a4a; border-radius: 12px; min-height: 140px; }
#DropZone:hover { background: #1a1530; border-color: #a855f7; }
#DropZoneText { color: #a89cc9; }

#BrowsePage { background: #0b0b14; color: #f5f3ff; }
#BrowseToolbar { background: #08080f; border-bottom: 1px solid #1a1530; }
#BrowseToolbar QToolButton { border: none; padding: 4px; border-radius: 8px; }
#BrowseToolbar QToolButton:hover { background: #1a1530; }
#BrowseAddressBar { background: #13121f; color: #f5f3ff; border: 1px solid #1a1530; border-radius: 14px; padding: 10px 14px; font-size: 14px; }
#BrowseGoButton { background: #a855f7; color: #ffffff; border: none; border-radius: 14px; padding: 10px 20px; font-weight: 600; }
#BrowseGoButton:hover { background: #9333ea; }
#BrowsePinButton { background: #13121f; color: #c8bfe0; border: 1px solid #1a1530; border-radius: 14px; padding: 10px 18px; font-weight: 600; }
#BrowsePinButton:hover { background: #1a1530; color: #ffffff; }
#BrowseTabs { background: transparent; border: none; }
#BrowseTabs::tab { background: #13121f; color: #f5f3ff; border: none; padding: 8px 14px; border-radius: 10px 10px 0 0; font-weight: 600; }
#BrowseTabs::tab:hover { background: #1a1530; }
#BrowseTabs::tab:selected { background: #0b0b14; color: #a855f7; }
#BrowsePinBar { background: #08080f; border-right: 1px solid #1a1530; }
#BrowsePinBar QToolButton { border: none; border-radius: 12px; padding: 4px; }
#BrowsePinBar QToolButton:hover { background: #1a1530; }
#BrowsePinHeader { font-weight: 700; font-size: 11px; color: #a855f7; letter-spacing: 1px; text-transform: uppercase; }
#BrowseHeroCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #13121f, stop:1 #1a1530); border: 1px solid #2a1a4a; border-radius: 22px; }
#BrowseHeroTitle { font-size: 26px; font-weight: 700; color: #ffffff; }
#BrowseHeroSubtitle { color: #a89cc9; font-size: 14px; }
#BrowseSearchWrap { background: #0b0b14; border: 1px solid #1a1530; border-radius: 16px; }
#BrowseHeroSearchEdit { background: transparent; border: none; font-size: 15px; color: #f5f3ff; padding: 4px 0; }
#BrowseHeroSearchButton { background: #a855f7; color: #ffffff; border: none; border-radius: 14px; padding: 10px 20px; font-weight: 600; }
#BrowseHeroSearchButton:hover { background: #9333ea; }
#BrowseActionsFrame { background: #13121f; border: 1px solid #1a1530; border-radius: 18px; }
#BrowseQuickActionsLabel { font-weight: 700; color: #ffffff; }
#BrowseQuickActionButton { background: #1a1530; color: #f5f3ff; border: 1px solid #2a1a4a; border-radius: 12px; padding: 10px 18px; font-size: 13px; font-weight: 600; }
#BrowseQuickActionButton:hover { background: #2a1a4a; border-color: #a855f7; }
#BrowseGridFrame { background: #13121f; border: 1px solid #1a1530; border-radius: 20px; }
#BrowseGridHeading { font-weight: 700; font-size: 16px; color: #ffffff; }
#BrowseTile { background: #13121f; border: 1px solid #1a1530; border-radius: 20px; text-align: left; }
#BrowseTile:hover { border-color: #a855f7; }
#BrowseTileTitle { font-weight: 700; font-size: 17px; color: #ffffff; }
#BrowseTileUrl { color: #a89cc9; font-size: 13px; }
#BrowseAddTile { background: #13121f; border: 1px dashed #2a1a4a; border-radius: 20px; color: #c8bfe0; font-weight: 600; }
#BrowseAddTile:hover { background: #1a1530; border-color: #a855f7; }
#BrowseEmptyLabel { color: #a89cc9; font-size: 13px; }
#BrowseSplitter::handle { background: #1a1530; width: 6px; }
#BrowseSplitter::handle:hover { background: #2a1a4a; }
"""


def _system_prefers_dark() -> bool:
    app = QtWidgets.QApplication.instance()
    if app is None:
        return False
    palette = app.palette()
    window = palette.color(QtGui.QPalette.Window)
    return window.value() < 128


def stylesheet_for(theme: str) -> str:
    t = (theme or "").lower()
    if t == "system":
        t = "dark" if _system_prefers_dark() else "light"
    if t == "dark":
        return DARK_QSS
    return LIGHT_QSS


def palette_for(theme: str) -> QtGui.QPalette:
    t = (theme or "").lower()
    if t == "system":
        t = "dark" if _system_prefers_dark() else "light"
    if t == "dark":
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#0b0b14"))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#f5f3ff"))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#13121f"))
        palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#161425"))
        palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#2a1a4a"))
        palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#f5f3ff"))
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#13121f"))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#f5f3ff"))
        palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor("#ff6b6b"))
        palette.setColor(QtGui.QPalette.Link, QtGui.QColor("#a855f7"))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#7c3aed"))
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
        disabled = QtGui.QColor("#5d5778")
        palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, disabled)
        palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, disabled)
        palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, disabled)
        return palette
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#fafaff"))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#0b0b14"))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#f5f1ff"))
    palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#0b0b14"))
    palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#0b0b14"))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#0b0b14"))
    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor("#dc2626"))
    palette.setColor(QtGui.QPalette.Link, QtGui.QColor("#7c3aed"))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#7c3aed"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
    disabled = QtGui.QColor("#b7b3c7")
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, disabled)
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, disabled)
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, disabled)
    return palette


def apply_theme(widget: QtWidgets.QWidget, theme: str) -> None:
    qss = stylesheet_for(theme)
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.setPalette(palette_for(theme))
        app.setStyleSheet(qss)
    widget.setStyleSheet(qss)


__all__ = ["LIGHT_QSS", "DARK_QSS", "apply_theme", "stylesheet_for", "palette_for"]
