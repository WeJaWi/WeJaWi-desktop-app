from __future__ import annotations

import copy
import json
import threading
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.logging_utils import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
WORKFLOWS_PATH = DATA_DIR / "workflows.json"

# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
ConfigDict = Dict[str, Any]
ConfigFactory = Callable[[], ConfigDict]
ConfigValidator = Callable[[ConfigDict], ConfigDict]
ConfigEditor = Callable[[ConfigDict, Optional[Any]], ConfigDict]


def _default_factory() -> ConfigDict:
    return {}


@dataclass(frozen=True)
class BuildingBlock:
    """Represents a selectable building block that wraps a tool."""

    block_id: str
    title: str
    tool_key: str
    description: str = ""
    category: str = "general"
    default_config_factory: ConfigFactory = _default_factory
    validate_config: Optional[ConfigValidator] = None
    edit_config: Optional[ConfigEditor] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def default_config(self) -> ConfigDict:
        try:
            cfg = self.default_config_factory() if self.default_config_factory else {}
            return copy.deepcopy(cfg)
        except Exception:
            logger.exception("default_config_factory failed for block %s", self.block_id)
            return {}

    def normalize_config(self, cfg: Optional[ConfigDict]) -> ConfigDict:
        cfg = copy.deepcopy(cfg or {})
        if self.validate_config:
            try:
                cfg = self.validate_config(cfg)
            except Exception:
                logger.exception("validate_config failed for block %s", self.block_id)
        return cfg


@dataclass
class WorkflowStep:
    block_id: str
    config: ConfigDict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"block": self.block_id, "config": copy.deepcopy(self.config)}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "WorkflowStep":
        return WorkflowStep(block_id=data.get("block", ""), config=copy.deepcopy(data.get("config") or {}))


@dataclass
class WorkflowDefinition:
    workflow_id: str
    name: str
    steps: List[WorkflowStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.workflow_id,
            "name": self.name,
            "steps": [step.to_dict() for step in self.steps],
            "meta": copy.deepcopy(self.metadata),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "WorkflowDefinition":
        return WorkflowDefinition(
            workflow_id=data.get("id") or str(uuid.uuid4()),
            name=data.get("name", "Untitled workflow"),
            steps=[WorkflowStep.from_dict(item) for item in data.get("steps") or []],
            metadata=copy.deepcopy(data.get("meta") or {}),
        )


class WorkflowManager:
    """Thread-safe manager for workflows and building blocks."""

    def __init__(self, storage_path: Path = WORKFLOWS_PATH):
        self._lock = threading.RLock()
        self._storage_path = storage_path
        self._blocks: Dict[str, BuildingBlock] = {}
        self._workflows: Dict[str, WorkflowDefinition] = {}
        self._load()

    # ------------------------------------------------------------------
    # Block registry
    # ------------------------------------------------------------------
    def register_block(self, block: BuildingBlock) -> None:
        with self._lock:
            logger.debug("Registering workflow block %s", block.block_id)
            self._blocks[block.block_id] = block

    def unregister_block(self, block_id: str) -> None:
        with self._lock:
            logger.debug("Unregistering workflow block %s", block_id)
            self._blocks.pop(block_id, None)

    def blocks(self, category: Optional[str] = None) -> List[BuildingBlock]:
        with self._lock:
            blocks = list(self._blocks.values())
        if category:
            blocks = [b for b in blocks if b.category == category]
        return sorted(blocks, key=lambda b: (b.category, b.title.lower()))

    def get_block(self, block_id: str) -> Optional[BuildingBlock]:
        with self._lock:
            return self._blocks.get(block_id)

    # ------------------------------------------------------------------
    # Workflow CRUD
    # ------------------------------------------------------------------
    def create_workflow(self, name: str, steps: Optional[List[WorkflowStep]] = None, metadata: Optional[Dict[str, Any]] = None) -> WorkflowDefinition:
        wf = WorkflowDefinition(workflow_id=str(uuid.uuid4()), name=name.strip() or "Untitled workflow")
        wf.steps = self._sanitize_steps(steps or [])
        wf.metadata = copy.deepcopy(metadata or {})
        with self._lock:
            logger.info("Created workflow %s (%s steps)", wf.workflow_id, len(wf.steps))
            self._workflows[wf.workflow_id] = wf
            self._save_locked()
        return wf

    def duplicate_workflow(self, workflow_id: str, new_name: Optional[str] = None) -> Optional[WorkflowDefinition]:
        original = self.get_workflow(workflow_id)
        if not original:
            return None
        clone = WorkflowDefinition(
            workflow_id=str(uuid.uuid4()),
            name=new_name.strip() if new_name else f"{original.name} (copy)",
            steps=[WorkflowStep(step.block_id, copy.deepcopy(step.config)) for step in original.steps],
            metadata=copy.deepcopy(original.metadata),
        )
        with self._lock:
            self._workflows[clone.workflow_id] = clone
            self._save_locked()
        return clone

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            return copy.deepcopy(wf) if wf else None

    def list_workflows(self) -> List[WorkflowDefinition]:
        with self._lock:
            return [copy.deepcopy(wf) for wf in self._workflows.values()]

    def rename_workflow(self, workflow_id: str, name: str) -> bool:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf:
                return False
            wf.name = name.strip() or wf.name
            self._save_locked()
            return True

    def delete_workflow(self, workflow_id: str) -> bool:
        with self._lock:
            removed = self._workflows.pop(workflow_id, None)
            if removed:
                logger.info("Deleted workflow %s", workflow_id)
                self._save_locked()
                return True
            return False

    # ------------------------------------------------------------------
    # Step operations
    # ------------------------------------------------------------------
    def add_step(self, workflow_id: str, block_id: str, config: Optional[ConfigDict] = None, position: Optional[int] = None) -> Optional[WorkflowDefinition]:
        block = self.get_block(block_id)
        if not block:
            logger.warning("Attempted to add unknown block %s", block_id)
            return None
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf:
                return None
            cfg = block.default_config()
            if config:
                cfg.update(config)
            cfg = block.normalize_config(cfg)
            step = WorkflowStep(block_id=block.block_id, config=cfg)
            if position is None or position >= len(wf.steps):
                wf.steps.append(step)
            else:
                wf.steps.insert(max(0, position), step)
            self._save_locked()
            return copy.deepcopy(wf)

    def update_step(self, workflow_id: str, index: int, config: ConfigDict) -> bool:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf or not (0 <= index < len(wf.steps)):
                return False
            step = wf.steps[index]
            block = self._blocks.get(step.block_id)
            if block:
                step.config = block.normalize_config(config)
            else:
                step.config = copy.deepcopy(config)
            self._save_locked()
            return True

    def remove_step(self, workflow_id: str, index: int) -> bool:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf or not (0 <= index < len(wf.steps)):
                return False
            del wf.steps[index]
            self._save_locked()
            return True

    def move_step(self, workflow_id: str, from_index: int, to_index: int) -> bool:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf or not (0 <= from_index < len(wf.steps)):
                return False
            step = wf.steps.pop(from_index)
            to_index = max(0, min(len(wf.steps), to_index))
            wf.steps.insert(to_index, step)
            self._save_locked()
            return True

    def edit_step(self, workflow_id: str, index: int, parent: Optional[Any] = None) -> Optional[WorkflowDefinition]:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf or not (0 <= index < len(wf.steps)):
                return None
            step = wf.steps[index]
            block = self._blocks.get(step.block_id)
        if not block or not block.edit_config:
            logger.debug("No config editor registered for block %s", step.block_id)
            return None
        try:
            new_config = block.edit_config(copy.deepcopy(step.config), parent)
        except Exception:
            logger.exception("Config editor failed for block %s", block.block_id)
            return None
        if new_config is None:
            return None
        self.update_step(workflow_id, index, new_config)
        return self.get_workflow(workflow_id)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _sanitize_steps(self, steps: List[WorkflowStep]) -> List[WorkflowStep]:
        sanitized: List[WorkflowStep] = []
        for step in steps:
            block = self._blocks.get(step.block_id)
            if not block:
                logger.warning("Skipping step with unknown block %s", step.block_id)
                continue
            cfg = block.normalize_config(step.config)
            sanitized.append(WorkflowStep(block_id=block.block_id, config=cfg))
        return sanitized

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding='utf-8'))
        except Exception:
            logger.exception("Failed to load workflows from %s", self._storage_path)
            return
        workflows_data = data.get("workflows") if isinstance(data, dict) else None
        if not isinstance(workflows_data, list):
            return
        with self._lock:
            for item in workflows_data:
                wf = WorkflowDefinition.from_dict(item)
                wf.steps = self._sanitize_steps(wf.steps)
                self._workflows[wf.workflow_id] = wf
        logger.info("Loaded %s stored workflow(s)", len(self._workflows))

    def _save_locked(self) -> None:
        payload = {
            "workflows": [wf.to_dict() for wf in self._workflows.values()]
        }
        try:
            self._storage_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        except Exception:
            logger.exception("Failed to persist workflows to %s", self._storage_path)


# Singleton-style accessor -----------------------------------------------------
workflow_manager = WorkflowManager()


def register_default_block(block_id: str, title: str, tool_key: str, description: str = "", *,
                           category: str = "general",
                           default_config: Optional[ConfigFactory] = None,
                           validator: Optional[ConfigValidator] = None,
                           editor: Optional[ConfigEditor] = None,
                           metadata: Optional[Dict[str, Any]] = None) -> None:
    """Convenience helper for registering simple building blocks."""
    block = BuildingBlock(
        block_id=block_id,
        title=title,
        tool_key=tool_key,
        description=description,
        category=category,
        default_config_factory=default_config or _default_factory,
        validate_config=validator,
        edit_config=editor,
        metadata=metadata or {},
    )
    workflow_manager.register_block(block)

