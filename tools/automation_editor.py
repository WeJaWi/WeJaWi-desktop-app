from __future__ import annotations

import json
from typing import Dict, Optional

from PyQt5 import QtCore, QtWidgets

from core.workflows import (
    workflow_manager,
    register_default_block,
    BuildingBlock,
    WorkflowDefinition,
)
from core.logging_utils import get_logger

logger = get_logger(__name__)


def _json_config_editor(title: str):
    def _editor(config: Dict, parent: Optional[QtWidgets.QWidget] = None) -> Optional[Dict]:
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle(f"Configure {title}")
        dlg.resize(520, 420)
        layout = QtWidgets.QVBoxLayout(dlg)
        info = QtWidgets.QLabel("Edit the JSON configuration for this block.")
        info.setWordWrap(True)
        layout.addWidget(info)
        text = QtWidgets.QPlainTextEdit()
        text.setPlainText(json.dumps(config or {}, indent=2))
        layout.addWidget(text, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        layout.addWidget(buttons)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return None
        try:
            data = json.loads(text.toPlainText() or "{}")
            if not isinstance(data, dict):
                raise ValueError("Configuration must be a JSON object")
            return data
        except Exception as exc:
            QtWidgets.QMessageBox.critical(parent, "Invalid JSON", str(exc))
            return None
    return _editor


_DEFAULT_BLOCKS = [
    dict(
        block_id="scene_images.generate",
        title="Scene Images",
        tool_key="scene_images",
        description="Generate images per scene using the Scene Images tool.",
        category="Creative",
        default_config=lambda: {
            "variant": "Classic Fast",
            "images_per_scene": 1,
            "output_folder": "",
        },
    ),
    dict(
        block_id="sound_waves.render",
        title="Sound Waves",
        tool_key="sound_waves",
        description="Render waveform overlays using the Sound Waves tool.",
        category="Audio",
        default_config=lambda: {
            "style": "sticks",
            "opacity_pct": 85,
            "bg_opacity_pct": 20,
        },
    ),
    dict(
        block_id="script_writer.generate",
        title="Script Writer",
        tool_key="script_writer",
        description="Draft long-form scripts via AI prompts.",
        category="Creative",
        default_config=lambda: {
            "prompt": "Write a 2 minute script about our topic.",
            "language": "en",
        },
    ),
    dict(
        block_id="txt_to_pdf.convert",
        title="Text to PDF",
        tool_key="txttopdf",
        description="Convert structured text into a PDF document.",
        category="Utility",
        default_config=lambda: {
            "title": "Untitled",
            "author": "",
        },
    ),
]


class _DefaultBlockBootstrap:
    _registered = False

    @classmethod
    def ensure(cls):
        if cls._registered:
            return
        existing = {block.block_id for block in workflow_manager.blocks()}
        for spec in _DEFAULT_BLOCKS:
            if spec["block_id"] in existing:
                continue
            register_default_block(
                block_id=spec["block_id"],
                title=spec["title"],
                tool_key=spec["tool_key"],
                description=spec["description"],
                category=spec.get("category", "general"),
                default_config=spec.get("default_config"),
                editor=_json_config_editor(spec["title"]),
            )
        cls._registered = True


class WorkflowListItem(QtWidgets.QListWidgetItem):
    def __init__(self, workflow: WorkflowDefinition):
        super().__init__(workflow.name)
        self.workflow_id = workflow.workflow_id


class StepListItem(QtWidgets.QListWidgetItem):
    def __init__(self, block: BuildingBlock, config: Dict):
        super().__init__(block.title)
        self.block_id = block.block_id
        self.config_preview = config
        self.setToolTip(block.description)


class AutomationEditorPage(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AutomationEditorPage")
        _DefaultBlockBootstrap.ensure()
        self._current_workflow: Optional[WorkflowDefinition] = None
        self._build_ui()
        self._load_workflows()

    # UI ------------------------------------------------------------------
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("Automation Editor")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        layout.addWidget(splitter, 1)

        # Left column – saved workflows
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        left_layout.addWidget(QtWidgets.QLabel("Workflows"))

        self.workflow_list = QtWidgets.QListWidget()
        self.workflow_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.workflow_list.itemSelectionChanged.connect(self._workflow_selected)
        left_layout.addWidget(self.workflow_list, 1)

        wf_btns = QtWidgets.QHBoxLayout()
        self.btn_new = QtWidgets.QPushButton("New workflow")
        self.btn_new.clicked.connect(self._new_workflow)
        self.btn_duplicate = QtWidgets.QPushButton("Duplicate")
        self.btn_duplicate.clicked.connect(self._duplicate_workflow)
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_delete.clicked.connect(self._delete_workflow)
        wf_btns.addWidget(self.btn_new)
        wf_btns.addWidget(self.btn_duplicate)
        wf_btns.addWidget(self.btn_delete)
        left_layout.addLayout(wf_btns)

        splitter.addWidget(left)
        splitter.setStretchFactor(0, 0)

        # Right column – workflow detail
        detail = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)

        name_layout = QtWidgets.QHBoxLayout()
        name_layout.addWidget(QtWidgets.QLabel("Name:"))
        self.name_edit = QtWidgets.QLineEdit()
        name_layout.addWidget(self.name_edit, 1)
        self.btn_rename = QtWidgets.QPushButton("Save name")
        self.btn_rename.clicked.connect(self._rename_workflow)
        name_layout.addWidget(self.btn_rename)
        detail_layout.addLayout(name_layout)

        body_split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        detail_layout.addWidget(body_split, 1)

        # Steps editor
        steps_box = QtWidgets.QGroupBox("Steps")
        steps_layout = QtWidgets.QVBoxLayout(steps_box)
        self.step_list = QtWidgets.QListWidget()
        self.step_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.step_list.itemDoubleClicked.connect(self._edit_selected_step)
        steps_layout.addWidget(self.step_list, 1)

        buttons_row = QtWidgets.QHBoxLayout()
        self.btn_step_add = QtWidgets.QPushButton("Add block")
        self.btn_step_add.clicked.connect(self._add_selected_block)
        self.btn_step_remove = QtWidgets.QPushButton("Remove")
        self.btn_step_remove.clicked.connect(self._remove_selected_step)
        self.btn_step_up = QtWidgets.QPushButton("Move up")
        self.btn_step_up.clicked.connect(lambda: self._move_step(-1))
        self.btn_step_down = QtWidgets.QPushButton("Move down")
        self.btn_step_down.clicked.connect(lambda: self._move_step(1))
        buttons_row.addWidget(self.btn_step_add)
        buttons_row.addWidget(self.btn_step_remove)
        buttons_row.addStretch(1)
        buttons_row.addWidget(self.btn_step_up)
        buttons_row.addWidget(self.btn_step_down)
        steps_layout.addLayout(buttons_row)

        body_split.addWidget(steps_box)

        # Block catalog
        catalog_box = QtWidgets.QGroupBox("Building blocks")
        catalog_layout = QtWidgets.QVBoxLayout(catalog_box)

        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(QtWidgets.QLabel("Category:"))
        self.category_combo = QtWidgets.QComboBox()
        self.category_combo.currentIndexChanged.connect(self._refresh_block_list)
        filter_layout.addWidget(self.category_combo)
        filter_layout.addStretch(1)
        catalog_layout.addLayout(filter_layout)

        self.block_list = QtWidgets.QListWidget()
        self.block_list.itemDoubleClicked.connect(lambda _: self._add_selected_block())
        catalog_layout.addWidget(self.block_list, 1)

        body_split.addWidget(catalog_box)
        body_split.setStretchFactor(0, 3)
        body_split.setStretchFactor(1, 2)

        splitter.addWidget(detail)
        splitter.setStretchFactor(1, 1)

        self._populate_categories()

    # ------------------------------------------------------------------
    def _populate_categories(self):
        categories = sorted({block.category for block in workflow_manager.blocks()})
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("All", "")
        for cat in categories:
            self.category_combo.addItem(cat, cat)
        self.category_combo.blockSignals(False)
        self._refresh_block_list()

    def _refresh_block_list(self):
        category = self.category_combo.currentData()
        blocks = workflow_manager.blocks(category if category else None)
        self.block_list.clear()
        for block in blocks:
            item = QtWidgets.QListWidgetItem(block.title)
            item.setToolTip(block.description)
            item.setData(QtCore.Qt.UserRole, block.block_id)
            self.block_list.addItem(item)

    # Workflow list -------------------------------------------------------
    def _load_workflows(self):
        self.workflow_list.clear()
        workflows = workflow_manager.list_workflows()
        if not workflows:
            wf = workflow_manager.create_workflow("My first workflow")
            workflows = [wf]
        for wf in workflows:
            item = WorkflowListItem(wf)
            self.workflow_list.addItem(item)
        self.workflow_list.setCurrentRow(0)

    def _workflow_selected(self):
        items = self.workflow_list.selectedItems()
        wf = workflow_manager.get_workflow(items[0].workflow_id) if items else None
        self._current_workflow = wf
        self._render_workflow()

    def _render_workflow(self):
        wf = self._current_workflow
        self.step_list.clear()
        if not wf:
            self.name_edit.clear()
            return
        self.name_edit.setText(wf.name)
        for step in wf.steps:
            block = workflow_manager.get_block(step.block_id)
            if not block:
                continue
            item = StepListItem(block, step.config)
            item.setData(QtCore.Qt.UserRole, step.block_id)
            item.setData(QtCore.Qt.UserRole + 1, step.config)
            self.step_list.addItem(item)

    # Workflow actions ----------------------------------------------------
    def _new_workflow(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New workflow", "Workflow name:")
        if not ok:
            return
        wf = workflow_manager.create_workflow(name)
        self._load_workflows()
        self._select_workflow_by_id(wf.workflow_id)

    def _duplicate_workflow(self):
        wf = self._current_workflow
        if not wf:
            return
        clone = workflow_manager.duplicate_workflow(wf.workflow_id)
        if clone:
            self._load_workflows()
            self._select_workflow_by_id(clone.workflow_id)

    def _delete_workflow(self):
        wf = self._current_workflow
        if not wf:
            return
        if QtWidgets.QMessageBox.question(self, "Delete workflow", f"Delete '{wf.name}'?") != QtWidgets.QMessageBox.Yes:
            return
        if workflow_manager.delete_workflow(wf.workflow_id):
            self._load_workflows()

    def _rename_workflow(self):
        wf = self._current_workflow
        if not wf:
            return
        if workflow_manager.rename_workflow(wf.workflow_id, self.name_edit.text()):
            self._load_workflows()
            self._select_workflow_by_id(wf.workflow_id)

    def _select_workflow_by_id(self, workflow_id: str):
        for i in range(self.workflow_list.count()):
            item = self.workflow_list.item(i)
            if isinstance(item, WorkflowListItem) and item.workflow_id == workflow_id:
                self.workflow_list.setCurrentRow(i)
                break

    # Step operations -----------------------------------------------------
    def _current_block_selection(self) -> Optional[str]:
        item = self.block_list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def _add_selected_block(self):
        wf = self._current_workflow
        if not wf:
            return
        block_id = self._current_block_selection()
        if not block_id:
            QtWidgets.QMessageBox.information(self, "Add block", "Select a block from the catalog first.")
            return
        updated = workflow_manager.add_step(wf.workflow_id, block_id)
        if updated:
            self._current_workflow = updated
            self._render_workflow()

    def _remove_selected_step(self):
        wf = self._current_workflow
        idx = self.step_list.currentRow()
        if not wf or idx < 0:
            return
        if workflow_manager.remove_step(wf.workflow_id, idx):
            self._current_workflow = workflow_manager.get_workflow(wf.workflow_id)
            self._render_workflow()

    def _move_step(self, delta: int):
        wf = self._current_workflow
        idx = self.step_list.currentRow()
        if not wf or idx < 0:
            return
        target = idx + delta
        if workflow_manager.move_step(wf.workflow_id, idx, target):
            self._current_workflow = workflow_manager.get_workflow(wf.workflow_id)
            self._render_workflow()
            self.step_list.setCurrentRow(max(0, min(self.step_list.count() - 1, target)))

    def _edit_selected_step(self):
        wf = self._current_workflow
        idx = self.step_list.currentRow()
        if not wf or idx < 0:
            return
        updated = workflow_manager.edit_step(wf.workflow_id, idx, self)
        if updated:
            self._current_workflow = workflow_manager.get_workflow(wf.workflow_id)
            self._render_workflow()
            self.step_list.setCurrentRow(idx)

