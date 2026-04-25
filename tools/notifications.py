from __future__ import annotations

from functools import partial

from PyQt5 import QtCore, QtWidgets

from core.notifications import SMTPConfig, notifier


class NotificationsPage(QtWidgets.QScrollArea):
    COLUMN_MAP = [
        ("success", "email"),
        ("success", "windows"),
        ("success", "telegram"),
        ("failure", "email"),
        ("failure", "windows"),
        ("failure", "telegram"),
    ]

    CHANNEL_TITLES = {
        "email": "Email",
        "windows": "Windows",
        "telegram": "Telegram",
    }


    CATEGORY_OPTIONS = [
        ("Information", "info"),
        ("Success", "success"),
        ("Warning", "warning"),
        ("Error", "error"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)

        self._loading = False
        self._pending_save = False
        self._stored_password = ""

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._commit_pending_changes)

        container = QtWidgets.QWidget()
        self.setWidget(container)
        root = QtWidgets.QVBoxLayout(container)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        title = QtWidgets.QLabel("Notifications")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        subtitle = QtWidgets.QLabel(
            "Choose how WeJaWi alerts you after jobs complete or fail."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.windows_box = self._build_windows_group()
        root.addWidget(self.windows_box)

        self.telegram_box = self._build_telegram_group()
        root.addWidget(self.telegram_box)

        self.email_box = self._build_email_group()
        root.addWidget(self.email_box)

        self.general_box = self._build_general_group()
        root.addWidget(self.general_box)

        self.rules_box = self._build_rules_group()
        root.addWidget(self.rules_box)

        root.addStretch(1)

        self._load_from_manager()

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------
    def _build_windows_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Windows notifications")
        layout = QtWidgets.QGridLayout(box)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)

        self.win_enable_chk = QtWidgets.QCheckBox("Enable Windows toast notifications")
        self.win_enable_chk.toggled.connect(self._on_windows_enabled)
        layout.addWidget(self.win_enable_chk, 0, 0, 1, 2)

        layout.addWidget(QtWidgets.QLabel("Category"), 1, 0)
        self.win_category_combo = QtWidgets.QComboBox()
        for label, value in self.CATEGORY_OPTIONS:
            self.win_category_combo.addItem(label, value)
        self.win_category_combo.currentIndexChanged.connect(self._on_windows_options)
        layout.addWidget(self.win_category_combo, 1, 1)

        layout.addWidget(QtWidgets.QLabel("Stay on screen"), 2, 0)
        self.win_duration_spin = QtWidgets.QSpinBox()
        self.win_duration_spin.setRange(1, 60)
        self.win_duration_spin.setSuffix(" s")
        self.win_duration_spin.valueChanged.connect(self._on_windows_options)
        layout.addWidget(self.win_duration_spin, 2, 1)

        layout.addWidget(QtWidgets.QLabel("Max message length"), 3, 0)
        self.win_length_spin = QtWidgets.QSpinBox()
        self.win_length_spin.setRange(0, 500)
        self.win_length_spin.setSpecialValueText("Unlimited")
        self.win_length_spin.setSuffix(" chars")
        self.win_length_spin.valueChanged.connect(self._on_windows_options)
        layout.addWidget(self.win_length_spin, 3, 1)

        self.win_sound_chk = QtWidgets.QCheckBox("Play notification sound")
        self.win_sound_chk.toggled.connect(self._on_windows_options)
        layout.addWidget(self.win_sound_chk, 4, 0, 1, 2)

        self.win_show_body_chk = QtWidgets.QCheckBox("Show detailed message body")
        self.win_show_body_chk.toggled.connect(self._on_windows_options)
        layout.addWidget(self.win_show_body_chk, 5, 0, 1, 2)

        self.win_append_tool_chk = QtWidgets.QCheckBox("Append tool name")
        self.win_append_tool_chk.toggled.connect(self._on_windows_options)
        layout.addWidget(self.win_append_tool_chk, 6, 0, 1, 2)

        self.win_append_event_chk = QtWidgets.QCheckBox("Append event outcome")
        self.win_append_event_chk.toggled.connect(self._on_windows_options)
        layout.addWidget(self.win_append_event_chk, 7, 0, 1, 2)

        self.win_keep_chk = QtWidgets.QCheckBox("Keep toast on screen until dismissed")
        self.win_keep_chk.toggled.connect(self._on_windows_options)
        layout.addWidget(self.win_keep_chk, 8, 0, 1, 2)

        self.win_test_btn = QtWidgets.QPushButton("Send test toast")
        self.win_test_btn.clicked.connect(self._send_windows_test)
        layout.addWidget(self.win_test_btn, 9, 0, 1, 2)

        return box


    def _build_telegram_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Telegram notifications")
        layout = QtWidgets.QGridLayout(box)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)

        self.telegram_enable_chk = QtWidgets.QCheckBox("Enable Telegram alerts")
        self.telegram_enable_chk.toggled.connect(self._on_telegram_enabled)
        layout.addWidget(self.telegram_enable_chk, 0, 0, 1, 2)

        layout.addWidget(QtWidgets.QLabel("Bot token"), 1, 0)
        self.telegram_token_edit = QtWidgets.QLineEdit()
        self.telegram_token_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.telegram_token_edit.setPlaceholderText("123456789:ABCDEF...")
        self.telegram_token_edit.textChanged.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_token_edit, 1, 1)

        layout.addWidget(QtWidgets.QLabel("Chat ID"), 2, 0)
        self.telegram_chat_edit = QtWidgets.QLineEdit()
        self.telegram_chat_edit.setPlaceholderText("@channel or numeric id")
        self.telegram_chat_edit.textChanged.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_chat_edit, 2, 1)

        layout.addWidget(QtWidgets.QLabel("Parse mode"), 3, 0)
        self.telegram_parse_combo = QtWidgets.QComboBox()
        self.telegram_parse_combo.addItem("Plain text", "")
        self.telegram_parse_combo.addItem("Markdown", "Markdown")
        self.telegram_parse_combo.addItem("MarkdownV2", "MarkdownV2")
        self.telegram_parse_combo.addItem("HTML", "HTML")
        self.telegram_parse_combo.currentIndexChanged.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_parse_combo, 3, 1)

        self.telegram_body_chk = QtWidgets.QCheckBox("Include message body")
        self.telegram_body_chk.toggled.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_body_chk, 4, 0, 1, 2)

        self.telegram_tool_chk = QtWidgets.QCheckBox("Include tool name")
        self.telegram_tool_chk.toggled.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_tool_chk, 5, 0, 1, 2)

        self.telegram_event_chk = QtWidgets.QCheckBox("Include event outcome")
        self.telegram_event_chk.toggled.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_event_chk, 6, 0, 1, 2)

        self.telegram_timestamp_chk = QtWidgets.QCheckBox("Include timestamp")
        self.telegram_timestamp_chk.toggled.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_timestamp_chk, 7, 0, 1, 2)

        self.telegram_preview_chk = QtWidgets.QCheckBox("Disable link previews")
        self.telegram_preview_chk.toggled.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_preview_chk, 8, 0, 1, 2)

        self.telegram_silent_chk = QtWidgets.QCheckBox("Send silently")
        self.telegram_silent_chk.toggled.connect(self._on_telegram_options_changed)
        layout.addWidget(self.telegram_silent_chk, 9, 0, 1, 2)

        self.telegram_test_btn = QtWidgets.QPushButton("Send test Telegram message")
        self.telegram_test_btn.clicked.connect(self._send_telegram_test)
        layout.addWidget(self.telegram_test_btn, 10, 0, 1, 2)

        return box


    def _build_email_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Email notifications")
        layout = QtWidgets.QVBoxLayout(box)
        layout.setSpacing(12)

        self.email_enable_chk = QtWidgets.QCheckBox("Enable email notifications")
        self.email_enable_chk.toggled.connect(self._on_email_enabled)
        layout.addWidget(self.email_enable_chk)

        smtp_box = QtWidgets.QGroupBox("SMTP server")
        smtp_layout = QtWidgets.QGridLayout(smtp_box)
        smtp_layout.setHorizontalSpacing(12)
        smtp_layout.setVerticalSpacing(6)

        smtp_layout.addWidget(QtWidgets.QLabel("Host"), 0, 0)
        self.smtp_host_edit = QtWidgets.QLineEdit()
        self.smtp_host_edit.setPlaceholderText("smtp.example.com")
        smtp_layout.addWidget(self.smtp_host_edit, 0, 1)

        smtp_layout.addWidget(QtWidgets.QLabel("Port"), 1, 0)
        self.smtp_port_spin = QtWidgets.QSpinBox()
        self.smtp_port_spin.setRange(1, 65535)
        self.smtp_port_spin.setValue(587)
        smtp_layout.addWidget(self.smtp_port_spin, 1, 1)

        smtp_layout.addWidget(QtWidgets.QLabel("Security"), 2, 0)
        self.smtp_security_combo = QtWidgets.QComboBox()
        self.smtp_security_combo.addItem("STARTTLS", "starttls")
        self.smtp_security_combo.addItem("SSL/TLS", "ssl")
        self.smtp_security_combo.addItem("None", "none")
        smtp_layout.addWidget(self.smtp_security_combo, 2, 1)

        smtp_layout.addWidget(QtWidgets.QLabel("Username"), 3, 0)
        self.smtp_user_edit = QtWidgets.QLineEdit()
        smtp_layout.addWidget(self.smtp_user_edit, 3, 1)

        smtp_layout.addWidget(QtWidgets.QLabel("Password"), 4, 0)
        self.smtp_password_edit = QtWidgets.QLineEdit()
        self.smtp_password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.smtp_password_edit.setPlaceholderText("Leave blank to keep current password")
        smtp_layout.addWidget(self.smtp_password_edit, 4, 1)

        smtp_layout.addWidget(QtWidgets.QLabel("From address"), 5, 0)
        self.smtp_from_edit = QtWidgets.QLineEdit()
        self.smtp_from_edit.setPlaceholderText("wejawi@example.com")
        smtp_layout.addWidget(self.smtp_from_edit, 5, 1)

        smtp_layout.addWidget(QtWidgets.QLabel("Recipients"), 6, 0)
        self.smtp_to_edit = QtWidgets.QLineEdit()
        self.smtp_to_edit.setPlaceholderText("alice@example.com, bob@example.com")
        smtp_layout.addWidget(self.smtp_to_edit, 6, 1)

        recipients_hint = QtWidgets.QLabel("Separate multiple recipients with commas.")
        recipients_hint.setWordWrap(True)
        recipients_hint.setStyleSheet("color: #6c6c6c; font-size: 11px;")
        smtp_layout.addWidget(recipients_hint, 7, 0, 1, 2)

        layout.addWidget(smtp_box)

        format_box = QtWidgets.QGroupBox("Message formatting")
        format_layout = QtWidgets.QGridLayout(format_box)
        format_layout.setHorizontalSpacing(12)
        format_layout.setVerticalSpacing(6)

        format_layout.addWidget(QtWidgets.QLabel("Subject prefix"), 0, 0)
        self.email_subject_prefix_edit = QtWidgets.QLineEdit()
        self.email_subject_prefix_edit.editingFinished.connect(self._on_email_options_changed)
        format_layout.addWidget(self.email_subject_prefix_edit, 0, 1)

        self.email_include_tool_chk = QtWidgets.QCheckBox("Include tool name in body")
        self.email_include_tool_chk.toggled.connect(self._on_email_options_changed)
        format_layout.addWidget(self.email_include_tool_chk, 1, 0, 1, 2)

        self.email_include_event_chk = QtWidgets.QCheckBox("Include outcome (success/failure)")
        self.email_include_event_chk.toggled.connect(self._on_email_options_changed)
        format_layout.addWidget(self.email_include_event_chk, 2, 0, 1, 2)

        self.email_include_timestamp_chk = QtWidgets.QCheckBox("Include timestamp")
        self.email_include_timestamp_chk.toggled.connect(self._on_email_options_changed)
        format_layout.addWidget(self.email_include_timestamp_chk, 3, 0, 1, 2)

        format_layout.addWidget(QtWidgets.QLabel("Custom footer"), 4, 0)
        self.email_footer_edit = QtWidgets.QPlainTextEdit()
        self.email_footer_edit.setPlaceholderText("Regards,\nTeam WeJaWi")
        self.email_footer_edit.setFixedHeight(75)
        self.email_footer_edit.textChanged.connect(self._on_email_footer_changed)
        format_layout.addWidget(self.email_footer_edit, 4, 1)

        layout.addWidget(format_box)

        buttons = QtWidgets.QHBoxLayout()
        self.email_save_btn = QtWidgets.QPushButton("Save mail settings")
        self.email_save_btn.clicked.connect(self._save_smtp_settings)
        buttons.addWidget(self.email_save_btn)

        buttons.addStretch(1)

        self.email_test_btn = QtWidgets.QPushButton("Send test email")
        self.email_test_btn.clicked.connect(self._send_email_test)
        buttons.addWidget(self.email_test_btn)

        layout.addLayout(buttons)

        return box

    def _build_general_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("General")
        layout = QtWidgets.QGridLayout(box)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(6)

        layout.addWidget(QtWidgets.QLabel("Debounce identical alerts"), 0, 0)
        self.debounce_spin = QtWidgets.QSpinBox()
        self.debounce_spin.setRange(0, 240)
        self.debounce_spin.setSuffix(" min")
        self.debounce_spin.valueChanged.connect(self._on_debounce_changed)
        layout.addWidget(self.debounce_spin, 0, 1)

        hint = QtWidgets.QLabel("Set to zero to receive every notification.")
        hint.setWordWrap(True)
        layout.addWidget(hint, 1, 0, 1, 2)

        self.reset_rules_btn = QtWidgets.QPushButton("Reset delivery rules to defaults")
        self.reset_rules_btn.clicked.connect(self._reset_rules)
        layout.addWidget(self.reset_rules_btn, 2, 0, 1, 2)

        return box

    def _build_rules_group(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Delivery rules")
        layout = QtWidgets.QVBoxLayout(box)
        layout.setSpacing(8)

        desc = QtWidgets.QLabel("Select when each tool sends Email, Windows, or Telegram notifications.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        headers = ['Tool']
        for event, channel in self.COLUMN_MAP:
            pretty_channel = self.CHANNEL_TITLES.get(channel, channel.title())
            headers.append(f"{event.capitalize()} - {pretty_channel}")
        self.rules_table = QtWidgets.QTableWidget(0, len(headers), self)
        self.rules_table.setHorizontalHeaderLabels(headers)
        self.rules_table.verticalHeader().setVisible(False)
        self.rules_table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.rules_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.rules_table.horizontalHeader().setStretchLastSection(True)
        self.rules_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch
        )
        for col in range(1, self.rules_table.columnCount()):
            self.rules_table.horizontalHeader().setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeToContents
            )
        layout.addWidget(self.rules_table)

        return box

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------
    def _load_from_manager(self) -> None:
        self._loading = True
        self._save_timer.stop()
        self._pending_save = False

        notifier.load()

        win_opts = notifier.channel_options.get("windows", {})
        self.win_enable_chk.setChecked(bool(win_opts.get("enabled", True)))
        category = win_opts.get("category", "info")
        idx = self.win_category_combo.findData(category)
        if idx < 0:
            idx = 0
        self.win_category_combo.setCurrentIndex(idx)
        duration = max(1, int(win_opts.get("duration_sec", 8) or 1))
        self.win_duration_spin.setValue(duration)
        length = int(win_opts.get("max_body_length", 220) or 0)
        self.win_length_spin.setValue(length)
        self.win_sound_chk.setChecked(bool(win_opts.get("play_sound", True)))
        self.win_show_body_chk.setChecked(bool(win_opts.get("show_body", True)))
        self.win_append_tool_chk.setChecked(bool(win_opts.get("append_tool", True)))
        self.win_append_event_chk.setChecked(bool(win_opts.get("append_event", True)))
        self.win_keep_chk.setChecked(bool(win_opts.get("keep_on_screen", False)))

        telegram_opts = notifier.channel_options.get("telegram", {})
        self.telegram_enable_chk.setChecked(bool(telegram_opts.get("enabled", False)))
        self.telegram_token_edit.setText(telegram_opts.get("bot_token", ""))
        self.telegram_chat_edit.setText(str(telegram_opts.get("chat_id", "")))
        parse_mode = telegram_opts.get("parse_mode", "")
        idx = self.telegram_parse_combo.findData(parse_mode)
        if idx < 0:
            idx = 0
        self.telegram_parse_combo.setCurrentIndex(idx)
        self.telegram_body_chk.setChecked(bool(telegram_opts.get("include_body", True)))
        self.telegram_tool_chk.setChecked(bool(telegram_opts.get("include_tool", True)))
        self.telegram_event_chk.setChecked(bool(telegram_opts.get("include_event", True)))
        self.telegram_timestamp_chk.setChecked(bool(telegram_opts.get("include_timestamp", True)))
        self.telegram_preview_chk.setChecked(bool(telegram_opts.get("disable_link_preview", True)))
        self.telegram_silent_chk.setChecked(bool(telegram_opts.get("silent", False)))

        email_opts = notifier.channel_options.get("email", {})

        email_opts = notifier.channel_options.get("email", {})
        self.email_enable_chk.setChecked(bool(email_opts.get("enabled", False)))
        self.email_subject_prefix_edit.setText(email_opts.get("subject_prefix", ""))
        self.email_include_tool_chk.setChecked(bool(email_opts.get("include_tool", True)))
        self.email_include_event_chk.setChecked(bool(email_opts.get("include_event_tag", True)))
        self.email_include_timestamp_chk.setChecked(bool(email_opts.get("include_timestamp", True)))
        self.email_footer_edit.blockSignals(True)
        self.email_footer_edit.setPlainText(email_opts.get("extra_footer", ""))
        self.email_footer_edit.blockSignals(False)

        cfg = notifier.smtp
        self.smtp_host_edit.setText(cfg.host)
        self.smtp_port_spin.setValue(int(cfg.port or 587))
        idx = self.smtp_security_combo.findData(cfg.security or "starttls")
        if idx < 0:
            idx = 0
        self.smtp_security_combo.setCurrentIndex(idx)
        self.smtp_user_edit.setText(cfg.username)
        self.smtp_password_edit.clear()
        self.smtp_from_edit.setText(cfg.from_addr)
        self.smtp_to_edit.setText(", ".join(cfg.to_addrs or []))
        self._stored_password = cfg.get_password()

        self.debounce_spin.setValue(int(notifier.debounce_minutes or 0))

        self._refresh_rules_table()

        self._loading = False
        self._update_windows_controls_enabled()
        self._update_telegram_controls_enabled()

    def _refresh_rules_table(self) -> None:
        self.rules_table.setRowCount(0)
        tools = sorted(notifier.rules.keys())
        for row, tool in enumerate(tools):
            self.rules_table.insertRow(row)
            item = QtWidgets.QTableWidgetItem(self._tool_label(tool))
            item.setFlags(QtCore.Qt.ItemIsEnabled)
            self.rules_table.setItem(row, 0, item)
            for col, (event, channel) in enumerate(self.COLUMN_MAP, start=1):
                chk = QtWidgets.QCheckBox()
                chk.setChecked(notifier.get_rule(tool, event, channel))
                chk.stateChanged.connect(partial(self._on_rule_changed, tool, event, channel))
                wrapper = QtWidgets.QWidget()
                inner = QtWidgets.QHBoxLayout(wrapper)
                inner.setContentsMargins(0, 0, 0, 0)
                inner.setAlignment(QtCore.Qt.AlignCenter)
                inner.addWidget(chk)
                self.rules_table.setCellWidget(row, col, wrapper)

    def _collect_smtp_config(self, keep_existing_password: bool) -> SMTPConfig:
        cfg = SMTPConfig()
        cfg.host = self.smtp_host_edit.text().strip()
        cfg.port = int(self.smtp_port_spin.value() or 587)
        cfg.security = self.smtp_security_combo.currentData() or "starttls"
        cfg.username = self.smtp_user_edit.text().strip()
        password = self.smtp_password_edit.text()
        if password:
            cfg.set_password(password)
        elif keep_existing_password and self._stored_password:
            cfg.set_password(self._stored_password)
        cfg.from_addr = self.smtp_from_edit.text().strip()
        cfg.to_addrs = [addr.strip() for addr in self.smtp_to_edit.text().split(",") if addr.strip()]
        return cfg

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_windows_enabled(self, state: bool) -> None:
        if self._loading:
            return
        notifier.set_channel_enabled("windows", bool(state), persist=False)
        self._update_windows_controls_enabled()
        self._mark_dirty()

    def _on_windows_options(self) -> None:
        if self._loading:
            return
        options = {
            "play_sound": self.win_sound_chk.isChecked(),
            "duration_sec": self.win_duration_spin.value(),
            "max_body_length": self.win_length_spin.value(),
            "append_tool": self.win_append_tool_chk.isChecked(),
            "append_event": self.win_append_event_chk.isChecked(),
            "show_body": self.win_show_body_chk.isChecked(),
            "keep_on_screen": self.win_keep_chk.isChecked(),
            "category": self.win_category_combo.currentData(),
        }
        for key, value in options.items():
            notifier.set_channel_option("windows", key, value, persist=False)
        self._mark_dirty()

    def _on_telegram_enabled(self, state: bool) -> None:
        if self._loading:
            return
        notifier.set_channel_enabled("telegram", bool(state), persist=False)
        self._update_telegram_controls_enabled()
        self._mark_dirty()

    def _on_telegram_options_changed(self) -> None:
        if self._loading:
            return
        options = {
            "bot_token": self.telegram_token_edit.text().strip(),
            "chat_id": self.telegram_chat_edit.text().strip(),
            "parse_mode": self.telegram_parse_combo.currentData() or "",
            "include_body": self.telegram_body_chk.isChecked(),
            "include_tool": self.telegram_tool_chk.isChecked(),
            "include_event": self.telegram_event_chk.isChecked(),
            "include_timestamp": self.telegram_timestamp_chk.isChecked(),
            "disable_link_preview": self.telegram_preview_chk.isChecked(),
            "silent": self.telegram_silent_chk.isChecked(),
        }
        for key, value in options.items():
            notifier.set_channel_option("telegram", key, value, persist=False)
        self._mark_dirty()

    def _on_email_enabled(self, state: bool) -> None:
        if self._loading:
            return
        notifier.set_channel_enabled("email", bool(state), persist=False)
        self._mark_dirty()

    def _on_email_options_changed(self) -> None:
        if self._loading:
            return
        options = {
            "subject_prefix": self.email_subject_prefix_edit.text(),
            "include_tool": self.email_include_tool_chk.isChecked(),
            "include_event_tag": self.email_include_event_chk.isChecked(),
            "include_timestamp": self.email_include_timestamp_chk.isChecked(),
        }
        for key, value in options.items():
            notifier.set_channel_option("email", key, value, persist=False)
        self._mark_dirty()

    def _on_email_footer_changed(self) -> None:
        if self._loading:
            return
        notifier.set_channel_option("email", "extra_footer", self.email_footer_edit.toPlainText(), persist=False)
        self._mark_dirty()

    def _on_debounce_changed(self, value: int) -> None:
        if self._loading:
            return
        notifier.set_debounce_minutes(int(value), persist=False)
        self._mark_dirty()

    def _on_rule_changed(self, tool: str, event: str, channel: str, state: int) -> None:
        if self._loading:
            return
        enabled = state == QtCore.Qt.Checked
        notifier.set_rule(tool, event, channel, enabled, persist=False)
        self._mark_dirty()

    def _save_smtp_settings(self) -> None:
        cfg = self._collect_smtp_config(keep_existing_password=True)
        notifier.set_smtp(cfg, persist=True)
        self._stored_password = cfg.get_password()
        self.smtp_password_edit.clear()
        QtWidgets.QMessageBox.information(self, "Mail settings", "SMTP settings saved.")

    def _send_email_test(self) -> None:
        cfg = self._collect_smtp_config(keep_existing_password=True)
        if not (cfg.host and cfg.from_addr and cfg.to_addrs):
            QtWidgets.QMessageBox.warning(
                self,
                "Test email",
                "Provide SMTP host, from address, and at least one recipient before sending a test.",
            )
            return
        original_cfg = notifier.smtp
        original_copy = SMTPConfig.from_dict(original_cfg.to_dict())
        notifier.set_smtp(cfg, persist=False)
        success = notifier.send_test("email")
        notifier.set_smtp(original_copy, persist=False)
        if success:
            QtWidgets.QMessageBox.information(
                self,
                "Test email",
                "Test email sent. Check your inbox.",
            )
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Test email",
                "Failed to send test email. Verify your SMTP credentials and network access.",
            )

    def _send_windows_test(self) -> None:
        success = notifier.send_test("windows")
        if success:
            QtWidgets.QMessageBox.information(
                self,
                "Windows notification",
                "Toast sent. Look near the Windows notification center.",
            )
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Windows notification",
                "Could not display a toast. Ensure Windows channel is enabled and the app tray icon is running.",
            )

    def _send_telegram_test(self) -> None:
        success = notifier.send_test("telegram")
        if success:
            QtWidgets.QMessageBox.information(
                self,
                "Telegram notification",
                "Test message sent. Check your Telegram client.",
            )
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Telegram notification",
                "Failed to send Telegram message. Verify bot token and chat ID, then ensure the bot can message the chat.",
            )

    def _reset_rules(self) -> None:
        if QtWidgets.QMessageBox.question(
            self,
            "Reset rules",
            "Restore notification delivery rules to the defaults?",
        ) != QtWidgets.QMessageBox.Yes:
            return
        notifier.reset_rules(persist=True)
        self._load_from_manager()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _update_windows_controls_enabled(self) -> None:
        enabled = self.win_enable_chk.isChecked()
        for widget in (
            self.win_category_combo,
            self.win_duration_spin,
            self.win_length_spin,
            self.win_sound_chk,
            self.win_show_body_chk,
            self.win_append_tool_chk,
            self.win_append_event_chk,
            self.win_keep_chk,
        ):
            widget.setEnabled(enabled)

    def _update_telegram_controls_enabled(self) -> None:
        enabled = self.telegram_enable_chk.isChecked()
        for widget in (
            self.telegram_token_edit,
            self.telegram_chat_edit,
            self.telegram_parse_combo,
            self.telegram_body_chk,
            self.telegram_tool_chk,
            self.telegram_event_chk,
            self.telegram_timestamp_chk,
            self.telegram_preview_chk,
            self.telegram_silent_chk,
            self.telegram_test_btn,
        ):
            widget.setEnabled(enabled)

    def _tool_label(self, key: str) -> str:
        return key.replace("_", " ").title()

    def _mark_dirty(self) -> None:
        if self._loading:
            return
        self._pending_save = True
        self._save_timer.start()

    def _commit_pending_changes(self) -> None:
        if not self._pending_save:
            return
        notifier.save()
        self._pending_save = False


__all__ = ["NotificationsPage"]
