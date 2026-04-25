# tools/script_writer.py
from __future__ import annotations
import os, re, json, glob
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from PyQt5 import QtWidgets, QtCore
from core.jobs import JobManager
from core.logging_utils import get_logger
from .llm_providers import (
    ChatMessage, provider_from_choice, load_api_keys, save_api_keys,
    DEFAULT_OPENAI_MODEL, DEFAULT_XAI_MODEL,
    MODEL_CATALOG, PROVIDER_LABELS,
)

logger = get_logger(__name__)

VID_RE = re.compile(r"[A-Za-z0-9_-]{11}")

@dataclass
class SourceItem:
    video_id: str
    title: str
    views: Optional[int]
    date: Optional[str]
    transcript_text: str
    path: Optional[str] = None

def _find_video_id_in_name(name: str) -> Optional[str]:
    m = re.search(r"\[([A-Za-z0-9_-]{11})\]", name)
    if m: return m.group(1)
    m = VID_RE.search(name)
    return m.group(0) if m else None

def _load_channel_identity_files(folder: str) -> List[dict]:
    out = []
    if not folder or not os.path.isdir(folder): return out
    for pat in ("result_*.json", "channel_identity.json", "*.json"):
        for path in sorted(glob.glob(os.path.join(folder, pat))):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "channel" in data and "videos" in data:
                    out.append(data)
                    logger.debug("Loaded channel identity file %s", path)
            except Exception:
                logger.exception("Failed to read channel identity file %s", path)
    return out

def _load_transcripts_folder(folder: str) -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    if not folder or not os.path.isdir(folder): return out
    for path in glob.glob(os.path.join(folder, "*.txt")):
        try:
            vid = _find_video_id_in_name(os.path.basename(path))
            if not vid: continue
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            out[vid] = (path, txt)
            logger.debug("Loaded transcript %s for %s", path, vid)
        except Exception:
            logger.exception("Failed to load transcript file %s", path)
    return out

def _collect_sources(ch_docs: List[dict], transcripts_map: Dict[str, Tuple[str, str]]) -> List[SourceItem]:
    items: List[SourceItem] = []
    for doc in ch_docs:
        for v in (doc.get("videos") or []):
            vid = v.get("id")
            if not vid or not VID_RE.fullmatch(vid or ""): continue
            txt = v.get("transcript_text") or ""
            tpath = v.get("transcript_path")
            if vid in transcripts_map:
                tpath, txt = transcripts_map[vid]
            items.append(SourceItem(
                video_id=vid, title=v.get("title") or "", views=v.get("view_count"),
                date=v.get("upload_date"), transcript_text=txt or "", path=tpath
            ))
    best: Dict[str, SourceItem] = {}
    for it in items:
        if it.video_id not in best or len(it.transcript_text) > len(best[it.video_id].transcript_text):
            best[it.video_id] = it
    items = list(best.values())
    items.sort(key=lambda s: (s.views or -1), reverse=True)
    logger.info("Collected %s unique sources", len(items))
    return items

def _trim_text(s: str, max_chars: int) -> str:
    if len(s) <= max_chars: return s
    return s[:max_chars].rsplit(" ", 1)[0] + "…"

def build_prompt(theme: str, target_len: str, tone: str, platform: str, audience: str,
                 include: Dict[str, bool], sources: List[SourceItem], lang: str = "English",
                 per_source_chars: int = 1200, max_total_chars: int = 12000) -> List[ChatMessage]:
    logger.info(
        "Building prompt for theme %s (platform=%s, tone=%s, sources=%s)",
        theme, platform, tone, len(sources)
    )
    picked, total = [], 0
    for s in sources:
        if not s.transcript_text: continue
        chunk = _trim_text(s.transcript_text.strip(), per_source_chars)
        entry = f"- {s.title} [{s.video_id}] (views: {s.views or '—'})\n  {chunk}"
        if total + len(entry) > max_total_chars: break
        picked.append(entry); total += len(entry)
    src_block = "\n".join(picked) if picked else "- (no transcripts provided)"

    inc = []
    if include.get("hook"):       inc.append("a strong 1–2 sentence hook at the top")
    if include.get("sections"):   inc.append("clear section headings with timestamps")
    if include.get("broll"):      inc.append("b-roll suggestions inline in [B-ROLL: …] brackets")
    if include.get("cta"):        inc.append("a natural call-to-action near the end")
    if include.get("hashtags"):   inc.append("3–6 platform-appropriate hashtags at the end")
    if include.get("title_desc"): inc.append("a punchy YouTube title + description after the script")
    extras = ("Also include " + ", ".join(inc) + ".") if inc else ""

    sys = ChatMessage("system", f"You are an award-winning {platform} scriptwriter. Write in {lang}. Be precise, engaging, and structure the script cleanly. Avoid fluff.")
    user = ChatMessage("user", f"""
Create a {platform} script on the theme: "{theme}".
Target length: {target_len}. Tone/style: {tone}. Audience: {audience or 'general'}.
Use the SOURCE MATERIAL below only as research — don't copy; synthesize and attribute concepts generally if needed.

{extras}

SOURCE MATERIAL
{src_block}

Output format:
- Script body with headings and short paragraphs
- If you add timestamps, start from 00:00 and keep them consistent
- Use simple markdown, no HTML
""".strip())
    return [sys, user]

class _Worker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str, str)   # ("ok"/"err", text)
    progress = QtCore.pyqtSignal(int)

    def __init__(self, provider_choice: str, model_name: str, temperature: float,
                 max_tokens: int, messages: List[ChatMessage],
                 keys: Optional[dict] = None):
        super().__init__(None)
        self.provider_choice = provider_choice
        self.model_name      = model_name
        self.temperature     = temperature
        self.max_tokens      = max_tokens
        self.messages        = messages
        self.keys            = keys or {}

    def run(self):
        try:
            logger.info("Worker starting generation (provider=%s, model=%s)",
                        self.provider_choice, self.model_name)
            prov = provider_from_choice(self.provider_choice, keys=self.keys)
            self.progress.emit(10)
            txt = prov.complete(self.messages, model=self.model_name or None,
                                temperature=self.temperature,
                                max_tokens=self.max_tokens, timeout_s=120)
            self.progress.emit(100)
            self.finished.emit("ok", txt)
        except Exception as e:
            logger.exception("Generation failed via provider %s", self.provider_choice)
            self.finished.emit("err", str(e))

class ScriptWriterPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources: List[SourceItem] = []
        logger.info("Initialising ScriptWriterPage")
        self._build_ui()
    def _build_ui(self):
        root = QtWidgets.QHBoxLayout(self); root.setContentsMargins(16,16,16,16); root.setSpacing(12)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("📝 Script Writer", objectName="PageTitle"))

        gsrc = QtWidgets.QGroupBox("1) Pick source folders"); fs = QtWidgets.QFormLayout(gsrc)
        self.edit_ch = QtWidgets.QLineEdit(); b1 = QtWidgets.QPushButton("Browse…"); b1.clicked.connect(lambda: self._pick_folder(self.edit_ch))
        row1 = QtWidgets.QHBoxLayout(); row1.addWidget(self.edit_ch, 1); row1.addWidget(b1)
        w1 = QtWidgets.QWidget(); w1.setLayout(row1); fs.addRow("Channel identities folder:", w1)
        self.edit_tr = QtWidgets.QLineEdit(); b2 = QtWidgets.QPushButton("Browse…"); b2.clicked.connect(lambda: self._pick_folder(self.edit_tr))
        row2 = QtWidgets.QHBoxLayout(); row2.addWidget(self.edit_tr, 1); row2.addWidget(b2)
        w2 = QtWidgets.QWidget(); w2.setLayout(row2); fs.addRow("Transcripts folder:", w2)
        self.btn_scan = QtWidgets.QPushButton("Scan ▶"); self.btn_scan.clicked.connect(self.on_scan)
        fs.addRow("", self.btn_scan)
        left.addWidget(gsrc)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Use", "Title", "Video ID", "Views", "Date"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        left.addWidget(self.table, 1)

        gset = QtWidgets.QGroupBox("2) Script settings"); f2 = QtWidgets.QFormLayout(gset)
        self.theme = QtWidgets.QLineEdit(); self.theme.setPlaceholderText("e.g., 'How to fall asleep faster (science-backed)'"); f2.addRow("Theme:", self.theme)
        self.platform = QtWidgets.QComboBox(); self.platform.addItems(["YouTube (long-form)","YouTube Shorts","TikTok","Instagram Reels","Podcast","Narration/Voiceover"]); f2.addRow("Platform:", self.platform)
        self.tone = QtWidgets.QComboBox(); self.tone.addItems(["Informative","Calm","Dramatic","Funny","Inspiring","Neutral"]); f2.addRow("Tone:", self.tone)
        self.audience = QtWidgets.QLineEdit(); self.audience.setPlaceholderText("e.g., 'busy professionals'"); f2.addRow("Audience:", self.audience)
        self.length = QtWidgets.QLineEdit("4–6 minutes"); f2.addRow("Target length:", self.length)
        self.chk_hook = QtWidgets.QCheckBox("Hook"); self.chk_sections = QtWidgets.QCheckBox("Headings + timestamps"); self.chk_broll = QtWidgets.QCheckBox("B-roll ideas")
        self.chk_cta = QtWidgets.QCheckBox("Call-to-action"); self.chk_hash = QtWidgets.QCheckBox("Hashtags"); self.chk_title_desc = QtWidgets.QCheckBox("Also draft Title + Description")
        self.chk_hook.setChecked(True); self.chk_sections.setChecked(True); self.chk_cta.setChecked(True)
        incrow = QtWidgets.QHBoxLayout()
        for w in (self.chk_hook,self.chk_sections,self.chk_broll,self.chk_cta,self.chk_hash,self.chk_title_desc):
            incrow.addWidget(w)
        # Wrap layout in a QWidget for QFormLayout.addRow
        _extras_wrap = QtWidgets.QWidget(); _extras_wrap.setLayout(incrow)
        f2.addRow("Extras:", _extras_wrap)
        left.addWidget(gset)

        gprov = QtWidgets.QGroupBox("3) Model provider")
        f3 = QtWidgets.QFormLayout(gprov)

        self.provider = QtWidgets.QComboBox()
        for label, key in PROVIDER_LABELS:
            self.provider.addItem(label, key)
        self.provider.currentIndexChanged.connect(self._on_provider_changed)
        f3.addRow("Provider:", self.provider)

        self.model_combo = QtWidgets.QComboBox()
        f3.addRow("Model:", self.model_combo)

        # Inline key override (loads from API Storage; user can override here)
        keys = load_api_keys()
        self._key_fields: dict = {}
        for svc_key, svc_label in [("openai","OpenAI key:"),("xai","xAI key:"),
                                    ("anthropic","Anthropic key:"),("kimi","Kimi key:")]:
            edit = QtWidgets.QLineEdit(keys.get(svc_key, ""))
            edit.setEchoMode(QtWidgets.QLineEdit.Password)
            edit.setPlaceholderText("Leave blank to use key from API Storage")
            f3.addRow(svc_label, edit)
            self._key_fields[svc_key] = edit

        note = QtWidgets.QLabel("💡 Keys saved here are session-only. Use 🔑 API Storage to persist them.")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px; color: #a89cc9;")
        f3.addRow("", note)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_save_keys = QtWidgets.QPushButton("Save to API Storage")
        self.btn_save_keys.clicked.connect(self._save_keys)
        btn_row.addWidget(self.btn_save_keys)
        btn_row.addStretch(1)
        btn_wrap = QtWidgets.QWidget(); btn_wrap.setLayout(btn_row)
        f3.addRow("", btn_wrap)

        left.addWidget(gprov)

        # populate model combo for initial provider
        self._on_provider_changed(0)

        root.addLayout(left, 5)

        right = QtWidgets.QVBoxLayout()
        right.addWidget(QtWidgets.QLabel("Output", objectName="PageTitle"))
        self.btn_generate = QtWidgets.QPushButton("Generate Script ✨"); self.btn_generate.clicked.connect(self.on_generate)
        self.pbar = QtWidgets.QProgressBar(); self.pbar.setRange(0,100); self.pbar.setValue(0)
        self.output = QtWidgets.QPlainTextEdit(); self.output.setPlaceholderText("Your script will appear here…")
        btns = QtWidgets.QHBoxLayout()
        self.btn_copy = QtWidgets.QPushButton("Copy"); self.btn_copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.output.toPlainText() or ""))
        self.btn_save = QtWidgets.QPushButton("Save .md…"); self.btn_save.clicked.connect(self.on_save)
        btns.addWidget(self.btn_copy); btns.addWidget(self.btn_save); btns.addStretch(1)
        right.addWidget(self.btn_generate); right.addWidget(self.pbar); right.addWidget(self.output, 1); right.addLayout(btns)
        root.addLayout(right, 6)

    def _pick_folder(self, edit: QtWidgets.QLineEdit):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Pick folder")
        if d:
            logger.info("Folder selected: %s", d)
            edit.setText(d)

    def _on_provider_changed(self, _idx: int):
        pkey = self.provider.currentData() or "openai"
        self.model_combo.clear()
        for label, model_id in MODEL_CATALOG.get(pkey, []):
            self.model_combo.addItem(label, model_id)

    def _current_keys(self) -> dict:
        """Merge saved keys with any inline overrides the user typed."""
        saved = load_api_keys()
        for svc_key, edit in self._key_fields.items():
            val = edit.text().strip()
            if val:
                saved[svc_key] = val
        return saved

    def _save_keys(self):
        updates = {k: edit.text().strip() for k, edit in self._key_fields.items()}
        save_api_keys({k: v for k, v in updates.items() if v})
        logger.info("API keys saved to storage: %s", [k for k, v in updates.items() if v])
        QtWidgets.QMessageBox.information(self, "API Storage", "Keys saved to API Storage.")

    def on_scan(self):
        ch_path = self.edit_ch.text().strip()
        tr_path = self.edit_tr.text().strip()
        logger.info("Scanning sources", extra={"channel_folder": ch_path, "transcripts_folder": tr_path})
        docs = _load_channel_identity_files(ch_path)
        tmap = _load_transcripts_folder(tr_path)
        logger.info("Loaded %s channel docs and %s transcripts", len(docs), len(tmap))
        self._sources = _collect_sources(docs, tmap)
        self._fill_table(self._sources)

    def _fill_table(self, items: List[SourceItem]):
        self.table.setRowCount(0)
        for it in items:
            r = self.table.rowCount(); self.table.insertRow(r)
            chk = QtWidgets.QTableWidgetItem(); chk.setCheckState(QtCore.Qt.Checked)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(it.title or "—"))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(it.video_id))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(it.views) if it.views is not None else "—"))
            self.table.setItem(r, 4, QtWidgets.QTableWidgetItem(it.date or "—"))
        self.table.resizeColumnsToContents()
        logger.debug("Rendered %s sources in table", self.table.rowCount())

    def _selected_sources(self) -> List[SourceItem]:
        outs = []
        for r in range(self.table.rowCount()):
            if self.table.item(r,0).checkState() == QtCore.Qt.Checked:
                vid = self.table.item(r,2).text()
                for it in self._sources:
                    if it.video_id == vid: outs.append(it); break
        return outs

    def on_generate(self):
        if not self._sources:
            QtWidgets.QMessageBox.information(self, "Sources", "Scan and select sources first."); return
        sel = self._selected_sources()
        if not sel:
            QtWidgets.QMessageBox.information(self, "Sources", "Select at least one source row."); return

        include = {
            "hook": self.chk_hook.isChecked(),
            "sections": self.chk_sections.isChecked(),
            "broll": self.chk_broll.isChecked(),
            "cta": self.chk_cta.isChecked(),
            "hashtags": self.chk_hash.isChecked(),
            "title_desc": self.chk_title_desc.isChecked(),
        }
        logger.info(
            "Generating script (theme=%s, provider=%s, sources=%s, extras=%s)",
            self.theme.text().strip() or "(untitled)",
            self.provider.currentData() or "openai",
            len(sel),
            [k for k, v in include.items() if v]
        )
        msgs = build_prompt(
            theme=self.theme.text().strip() or "General overview",
            target_len=self.length.text().strip() or "3–5 minutes",
            tone=self.tone.currentText(),
            platform=self.platform.currentText(),
            audience=self.audience.text().strip(),
            include=include,
            sources=sel
        )

        prov_choice = self.provider.currentData() or "openai"
        model_name  = self.model_combo.currentData() or ""
        merged_keys = self._current_keys()

        self.btn_generate.setEnabled(False); self.pbar.setValue(0); self.output.setPlainText("")

        self._qthread = QtCore.QThread(self)
        self._worker = _Worker(prov_choice, model_name, 0.7, 1800, msgs, keys=merged_keys)
        self._worker.moveToThread(self._qthread)
        self._worker.progress.connect(self.pbar.setValue)

        # Add to Jobs Center as a manual job
        jm = JobManager.instance()
        meta = {
            "tool": "script_writer",
            "theme": self.theme.text().strip(),
            "platform": self.platform.currentText(),
            "tone": self.tone.currentText(),
            "audience": self.audience.text().strip(),
            "provider": prov_choice,
            "model": model_name,
            "selected_sources": [s.video_id for s in sel],
        }
        job_id = jm.start_manual_job(meta, tag="script_writer")
        logger.debug("Manual job started: %s", job_id)

        # pipe worker progress into JobManager
        self._worker.progress.connect(lambda pct: jm.manual_progress(job_id, int(pct)))

        def _done(status: str, text: str):
            self.btn_generate.setEnabled(True)
            self.pbar.setValue(100 if status=="ok" else 0)
            if status=="ok":
                logger.info("Script generation completed (job=%s)", job_id)
                out = text
                if include.get("title_desc") and ("# Title" not in out and "Title:" not in out):
                    out += "\n\n---\n(If missing, please add a Title and Description.)"
                self.output.setPlainText(out)
                jm.manual_log(job_id, "Generation completed successfully.")
                jm.manual_finish(job_id, 0)
            else:
                logger.error("Script generation failed (job=%s): %s", job_id, text)
                QtWidgets.QMessageBox.critical(self, "Generation failed", text)
                jm.manual_log(job_id, f"Generation failed: {text}")
                jm.manual_finish(job_id, 1)
            self._worker.moveToThread(QtWidgets.QApplication.instance().thread())
            self._qthread.quit(); self._qthread.wait()
            self._worker.deleteLater(); self._qthread.deleteLater()

        self._worker.finished.connect(_done)
        self._qthread.started.connect(self._worker.run)
        self._qthread.start()

    def on_save(self):
        txt = self.output.toPlainText().strip()
        if not txt:
            QtWidgets.QMessageBox.information(self, "Save", "Nothing to save."); return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save script", "", "Markdown (*.md);;Text (*.txt)")
        if not path: return
        if not (path.lower().endswith(".md") or path.lower().endswith(".txt")):
            path += ".md"
        try:
            with open(path, "w", encoding="utf-8") as f: f.write(txt)
            QtWidgets.QMessageBox.information(self, "Saved", f"Saved:\n{path}")
            logger.info("Script saved to %s", path)
        except Exception as e:
            logger.exception("Failed to save script to %s", path)
            QtWidgets.QMessageBox.critical(self, "Save failed", str(e))
