from PyQt5 import QtWidgets, QtCore
import threading
from typing import List

from core.argos_client import ArgosTranslator, ArgosOptions
from core.ct2_client import CT2Translator, CT2Options
from core.text_split import split_text

LANGS = [
    ("Auto-detect", "auto"),
    ("English", "en"), ("Arabic", "ar"), ("Chinese (Simplified)", "zh"),
    ("Czech", "cs"), ("Dutch", "nl"), ("French", "fr"), ("German", "de"),
    ("Greek", "el"), ("Hindi", "hi"), ("Hungarian", "hu"), ("Italian", "it"),
    ("Japanese", "ja"), ("Korean", "ko"), ("Polish", "pl"), ("Portuguese", "pt"),
    ("Romanian", "ro"), ("Russian", "ru"), ("Slovak", "sk"), ("Spanish", "es"),
    ("Swedish", "sv"), ("Turkish", "tr"), ("Ukrainian", "uk"),
]

class TranslatePage(QtWidgets.QWidget):
    # ---- NEW: signals that carry only simple types (thread-safe) ----
    sig_log           = QtCore.pyqtSignal(str)
    sig_progress      = QtCore.pyqtSignal(int)
    sig_set_output    = QtCore.pyqtSignal(str, str, str)
    sig_set_buttons   = QtCore.pyqtSignal(bool, bool)  # translate_enabled, cancel_enabled
    sig_clear_log     = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TranslatePage")
        self._cancel = threading.Event()
        self._worker = None

        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(16,16,16,16); root.setSpacing(12)
        title = QtWidgets.QLabel("🌍 Translate (Local: Argos / CTranslate2)"); title.setObjectName("PageTitle"); root.addWidget(title)

        # Provider + language options
        prov_box = QtWidgets.QGroupBox("Provider"); prov_form = QtWidgets.QFormLayout(prov_box)
        self.provider = QtWidgets.QComboBox(); self.provider.addItems(["Argos (local)", "CT2 (local)"]); prov_form.addRow("Engine:", self.provider)
        opts_row = QtWidgets.QHBoxLayout()
        self.source_combo = QtWidgets.QComboBox(); self._fill_langs(self.source_combo, "auto")
        self.target_combo = QtWidgets.QComboBox(); self._fill_langs(self.target_combo, "en")
        opts_row.addWidget(QtWidgets.QLabel("From:")); opts_row.addWidget(self.source_combo); opts_row.addSpacing(8)
        opts_row.addWidget(QtWidgets.QLabel("To:"));   opts_row.addWidget(self.target_combo); opts_row.addStretch(1)
        w_opts = QtWidgets.QWidget(); w_opts.setLayout(opts_row); prov_form.addRow("Languages:", w_opts)

        # CT2 settings (NLLB / M2M100 / OpenNMT)
        ct2_box = QtWidgets.QGroupBox("CTranslate2 Settings"); ct2_form = QtWidgets.QFormLayout(ct2_box)
        self.ct2_model_dir = QtWidgets.QLineEdit(""); b1 = QtWidgets.QPushButton("…"); b1.clicked.connect(self._pick_ct2_model_dir)
        row1 = QtWidgets.QHBoxLayout(); row1.addWidget(self.ct2_model_dir); row1.addWidget(b1)

        # HF tokenizer path (NLLB/M2M100)
        self.ct2_tokenizer = QtWidgets.QLineEdit(""); b2 = QtWidgets.QPushButton("…"); b2.clicked.connect(self._pick_ct2_tokenizer)
        row2 = QtWidgets.QHBoxLayout(); row2.addWidget(self.ct2_tokenizer); row2.addWidget(b2)

        # OpenNMT spm models
        self.src_spm = QtWidgets.QLineEdit(""); b3 = QtWidgets.QPushButton("…"); b3.clicked.connect(self._pick_src_spm)
        self.tgt_spm = QtWidgets.QLineEdit(""); b4 = QtWidgets.QPushButton("…"); b4.clicked.connect(self._pick_tgt_spm)
        row3 = QtWidgets.QHBoxLayout(); row3.addWidget(self.src_spm); row3.addWidget(b3)
        row4 = QtWidgets.QHBoxLayout(); row4.addWidget(self.tgt_spm); row4.addWidget(b4)

        self.ct2_type = QtWidgets.QComboBox(); self.ct2_type.addItems(["nllb", "m2m100", "opennmt"])
        self.ct2_device = QtWidgets.QComboBox(); self.ct2_device.addItems(["cpu", "cuda"])
        self.ct2_compute = QtWidgets.QComboBox(); self.ct2_compute.addItems(["default", "int8", "int8_float16", "float16"])

        w1 = QtWidgets.QWidget(); w1.setLayout(row1)
        w2 = QtWidgets.QWidget(); w2.setLayout(row2)
        w3 = QtWidgets.QWidget(); w3.setLayout(row3)
        w4 = QtWidgets.QWidget(); w4.setLayout(row4)
        ct2_form.addRow("Model dir:", w1)
        ct2_form.addRow("Tokenizer path (HF):", w2)   # nllb/m2m100
        ct2_form.addRow("Source SPM (.model):", w3)   # opennmt
        ct2_form.addRow("Target SPM (.model):", w4)   # opennmt
        ct2_form.addRow("Model type:", self.ct2_type)
        ct2_form.addRow("Device:", self.ct2_device)
        ct2_form.addRow("Compute:", self.ct2_compute)

        root.addWidget(prov_box); root.addWidget(ct2_box)

        # IO row
        io_row = QtWidgets.QHBoxLayout()
        self.btn_load = QtWidgets.QPushButton("Load Text…"); self.btn_load.clicked.connect(self._load_text)
        self.btn_save = QtWidgets.QPushButton("Save Output…"); self.btn_save.clicked.connect(self._save_output)
        self.lbl_counts = QtWidgets.QLabel("0 chars")
        io_row.addWidget(self.btn_load); io_row.addWidget(self.btn_save); io_row.addStretch(1); io_row.addWidget(self.lbl_counts)
        root.addLayout(io_row)

        # Editors
        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        left = QtWidgets.QWidget(); lv = QtWidgets.QVBoxLayout(left); lv.setContentsMargins(0,0,0,0); lv.setSpacing(6)
        lv.addWidget(QtWidgets.QLabel("Input")); self.in_edit = QtWidgets.QPlainTextEdit(); self.in_edit.textChanged.connect(self._update_counts); lv.addWidget(self.in_edit, 1)
        right = QtWidgets.QWidget(); rv = QtWidgets.QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(6)
        rv.addWidget(QtWidgets.QLabel("Output"))
        self.tabs = QtWidgets.QTabWidget()
        self.out_main = QtWidgets.QPlainTextEdit(); self.out_main.setReadOnly(True)
        self.out_alt1 = QtWidgets.QPlainTextEdit(); self.out_alt1.setReadOnly(True)
        self.out_alt2 = QtWidgets.QPlainTextEdit(); self.out_alt2.setReadOnly(True)
        self.tabs.addTab(self.out_main, "Main"); self.tabs.addTab(self.out_alt1, "Alt 1"); self.tabs.addTab(self.out_alt2, "Alt 2")
        rv.addWidget(self.tabs, 1)
        split.addWidget(left); split.addWidget(right); split.setStretchFactor(0,1); split.setStretchFactor(1,1)
        root.addWidget(split, 1)

        # Actions + progress
        act = QtWidgets.QHBoxLayout()
        self.btn_clear = QtWidgets.QPushButton("Clear"); self.btn_clear.clicked.connect(self._clear_all)
        self.btn_copy = QtWidgets.QPushButton("Copy Output"); self.btn_copy.clicked.connect(self._copy_output)
        self.btn_translate = QtWidgets.QPushButton("Translate"); self.btn_translate.clicked.connect(self._start_translate)
        self.btn_cancel = QtWidgets.QPushButton("Cancel"); self.btn_cancel.setEnabled(False); self.btn_cancel.clicked.connect(self._cancel_now)
        act.addWidget(self.btn_clear); act.addWidget(self.btn_copy); act.addStretch(1); act.addWidget(self.btn_cancel); act.addWidget(self.btn_translate)
        root.addLayout(act)
        self.pbar = QtWidgets.QProgressBar(); self.pbar.setRange(0,100); root.addWidget(self.pbar)
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000); root.addWidget(self.log, 1)

        # ---- NEW: connect signals to UI-thread slots ----
        self.sig_log.connect(self.log.appendPlainText)
        self.sig_progress.connect(self.pbar.setValue)
        self.sig_set_output.connect(self._apply_output)
        self.sig_set_buttons.connect(self._set_buttons)
        self.sig_clear_log.connect(self.log.clear)

        self._update_counts()
        self.provider.currentIndexChanged.connect(self._toggle_ct2_box)
        self.ct2_type.currentIndexChanged.connect(self._toggle_model_fields)
        self._toggle_ct2_box(); self._toggle_model_fields()

    # ---- slots used by signals ----
    @QtCore.pyqtSlot(str, str, str)
    def _apply_output(self, main, alt1, alt2):
        self.out_main.setPlainText(main)
        self.out_alt1.setPlainText(alt1)
        self.out_alt2.setPlainText(alt2)

    @QtCore.pyqtSlot(bool, bool)
    def _set_buttons(self, trans_enabled, cancel_enabled):
        self.btn_translate.setEnabled(trans_enabled)
        self.btn_cancel.setEnabled(cancel_enabled)

    # ----- helpers -----
    def _fill_langs(self, combo: QtWidgets.QComboBox, default: str):
        for n,c in LANGS: combo.addItem(n,c)
        for i in range(combo.count()):
            if combo.itemData(i)==default: combo.setCurrentIndex(i); break

    def _toggle_ct2_box(self):
        is_ct2 = (self.provider.currentIndex()==1)
        for g in self.findChildren(QtWidgets.QGroupBox):
            if g.title()=="CTranslate2 Settings":
                g.setVisible(is_ct2)

    def _toggle_model_fields(self):
        mt = self.ct2_type.currentText().strip().lower()
        show_hf = mt in ("nllb","m2m100")
        show_spm = mt == "opennmt"
        self.ct2_tokenizer.parentWidget().setVisible(show_hf)
        self.src_spm.parentWidget().setVisible(show_spm)
        self.tgt_spm.parentWidget().setVisible(show_spm)

    def _update_counts(self):
        self.lbl_counts.setText(f"{len(self.in_edit.toPlainText())} chars")

    def _log(self, s: str):
        # keep for local use on main thread if needed
        self.log.appendPlainText(s)

    def _clear_all(self):
        self.in_edit.clear(); self.out_main.clear(); self.out_alt1.clear(); self.out_alt2.clear(); self._update_counts()

    def _copy_output(self):
        QtWidgets.QApplication.clipboard().setText(self.out_main.toPlainText()); self._log("Copied main output.")

    def _load_text(self):
        p,_ = QtWidgets.QFileDialog.getOpenFileName(self, "Open text", "", "Text (*.txt);;All files (*.*)")
        if p:
            with open(p,"r",encoding="utf-8",errors="ignore") as f: self.in_edit.setPlainText(f.read())

    def _save_output(self):
        p,_ = QtWidgets.QFileDialog.getSaveFileName(self, "Save output", "", "Text (*.txt)")
        if p:
            with open(p,"w",encoding="utf-8") as f: f.write(self.out_main.toPlainText()); self._log(f"Saved: {p}")

    def _pick_ct2_model_dir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self,"Select CTranslate2 model directory")
        if d: self.ct2_model_dir.setText(d)

    def _pick_ct2_tokenizer(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self,"Select tokenizer folder (local HF tokenizer)")
        if d: self.ct2_tokenizer.setText(d)

    def _pick_src_spm(self):
        p,_ = QtWidgets.QFileDialog.getOpenFileName(self, "Select source SentencePiece model", "", "SentencePiece (*.model)")
        if p: self.src_spm.setText(p)

    def _pick_tgt_spm(self):
        p,_ = QtWidgets.QFileDialog.getOpenFileName(self, "Select target SentencePiece model", "", "SentencePiece (*.model)")
        if p: self.tgt_spm.setText(p)

    # ----- translate (now fully thread-safe) -----
    def _start_translate(self):
        text = self.in_edit.toPlainText().strip()
        if not text:
            QtWidgets.QMessageBox.information(self,"Translate","Enter some text first."); return

        # capture UI state before worker starts (no reads from widgets in thread)
        src = self.source_combo.currentData() or "auto"
        tgt = self.target_combo.currentData() or "en"
        provider = self.provider.currentIndex()  # 0=Argos, 1=CT2
        ct2_model_dir  = self.ct2_model_dir.text().strip()
        ct2_tokenizer  = self.ct2_tokenizer.text().strip()
        ct2_type       = self.ct2_type.currentText().strip()
        ct2_device     = self.ct2_device.currentText().strip()
        ct2_compute    = self.ct2_compute.currentText().strip()
        src_spm_path   = self.src_spm.text().strip()
        tgt_spm_path   = self.tgt_spm.text().strip()

        self.sig_set_buttons.emit(False, True)
        self.sig_clear_log.emit()
        self.pbar.setValue(0)

        def worker():
            try:
                parts = split_text(text, 4500 if provider==0 else 1200)
                total = len(parts) or 1

                if provider == 0:
                    tr = ArgosTranslator(ArgosOptions(source=src, target=tgt))
                else:
                    opts = CT2Options(
                        model_dir=ct2_model_dir,
                        tokenizer_path=ct2_tokenizer,
                        model_type=ct2_type,
                        device=ct2_device,
                        compute_type=ct2_compute,
                        src_spm=src_spm_path,
                        tgt_spm=tgt_spm_path,
                    )
                    tr = CT2Translator(opts)

                outs: List[str] = []
                for i, ck in enumerate(parts, 1):
                    if self._cancel.is_set():
                        self.sig_log.emit("Cancelled.")
                        break
                    seg = tr.translate(ck, source=(src if provider==0 or src!="auto" else "en"), target=tgt)
                    outs.append(seg)
                    self.sig_progress.emit(int(i/total*100))
                    self.sig_log.emit(f"Chunk {i}/{total}: {len(ck)} chars")

                result = "".join(outs)
                self.sig_set_output.emit(result, result, result)
                self.sig_log.emit("Done.")
            except Exception as e:
                self.sig_log.emit(f"ERROR: {e}")
            finally:
                self.sig_set_buttons.emit(True, False)

        t = threading.Thread(target=worker, daemon=True)
        self._worker = t
        t.start()

    def _cancel_now(self):
        self._cancel.set()
