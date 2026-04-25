from __future__ import annotations

from PyQt5 import QtWidgets, QtCore

from core.app_settings import settings


class SettingsDialog(QtWidgets.QDialog):
    """Basic application settings, including theme selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(420, 260)

        self._data = settings.data  # load lazily once
        self._orig_theme = self._data.ui.theme

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)

        # Theme selection
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItem("System", "system")
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        idx = max(0, self.theme_combo.findData(self._data.ui.theme or "system"))
        self.theme_combo.setCurrentIndex(idx)
        form.addRow("Theme:", self.theme_combo)

        # UI scale
        self.scale_spin = QtWidgets.QSpinBox()
        self.scale_spin.setRange(75, 200)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setSingleStep(5)
        self.scale_spin.setValue(self._data.ui.scale_percent or 100)
        form.addRow("UI Scale:", self.scale_spin)

        # Start on boot
        self.start_boot_chk = QtWidgets.QCheckBox("Launch WeJaWi when I sign in")
        self.start_boot_chk.setChecked(bool(self._data.ui.start_on_boot))
        form.addRow("Startup:", self.start_boot_chk)

        # Auto update
        self.auto_update_chk = QtWidgets.QCheckBox("Automatically check for updates")
        self.auto_update_chk.setChecked(bool(self._data.update.auto_check))
        form.addRow("Updates:", self.auto_update_chk)

        # Logging level combo
        self.logging_combo = QtWidgets.QComboBox()
        self.logging_combo.addItems(["debug", "info", "warning", "error"])
        log_idx = max(0, self.logging_combo.findText((self._data.logging.level or "info").lower()))
        self.logging_combo.setCurrentIndex(log_idx)
        form.addRow("Log level:", self.logging_combo)

        layout.addLayout(form)

        # Buttons
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # Convenience accessors -------------------------------------------------
    def selected_theme(self) -> str:
        return self.theme_combo.currentData() or "system"

    # Overrides -------------------------------------------------------------
    def accept(self):
        data = settings.data
        data.ui.theme = self.selected_theme()
        data.ui.scale_percent = int(self.scale_spin.value())
        data.ui.start_on_boot = bool(self.start_boot_chk.isChecked())
        data.update.auto_check = bool(self.auto_update_chk.isChecked())
        data.logging.level = self.logging_combo.currentText().lower()
        settings.save()
        super().accept()
