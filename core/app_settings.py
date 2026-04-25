from __future__ import annotations
import os, sys, json, datetime, shutil
from dataclasses import dataclass, asdict, field
from typing import Dict, Any
from .logging_utils import get_logger

logger = get_logger(__name__)

def _config_dir() -> str:
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(root, "WeJaWi")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "WeJaWi")
    root = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "wejawi")

def _settings_path() -> str:
    return os.path.join(_config_dir(), "settings.json")

@dataclass
class UISettings:
    theme: str = "system"             # system | light | dark
    scale_percent: int = 100          # 75-200
    start_on_boot: bool = False
    startup_tool: str = "stitch"      # key of the first page
    accent: str = "blue"              # future use

@dataclass
class PathSettings:
    default_video_out: str = ""
    default_audio_out: str = ""
    default_image_out: str = ""
    default_captions_out: str = ""

@dataclass
class PerformanceSettings:
    max_threads: int = 0              # 0 = auto
    prefer_gpu: bool = False
    enable_nvenc: bool = True
    stt_model: str = "tiny"           # tiny, base, small, medium

@dataclass
class NotificationSettings:
    enabled: bool = True
    debounce_minutes: int = 0         # optional mirror of notifications manager

@dataclass
class NetworkSettings:
    use_system_proxy: bool = True
    http_proxy: str = ""              # host:port or URL
    timeout_sec: int = 20

@dataclass
class PrivacySettings:
    delete_temp_on_close: bool = True
    strip_metadata_outputs: bool = False

@dataclass
class UpdateSettings:
    auto_check: bool = True
    channel: str = "stable"           # stable | beta

@dataclass
class LoggingSettings:
    level: str = "info"               # debug|info|warning|error
    log_dir: str = ""

@dataclass
class HotkeysSettings:
    shortcuts: Dict[str, str] = field(default_factory=lambda: {
        "open": "Ctrl+O",
        "save": "Ctrl+S",
        "convert_start": "Ctrl+Enter",
        "cancel_task": "Esc",
    })

@dataclass
class AppSettings:
    ui: UISettings = field(default_factory=UISettings)
    paths: PathSettings = field(default_factory=PathSettings)
    perf: PerformanceSettings = field(default_factory=PerformanceSettings)
    notify: NotificationSettings = field(default_factory=NotificationSettings)
    net: NetworkSettings = field(default_factory=NetworkSettings)
    privacy: PrivacySettings = field(default_factory=PrivacySettings)
    update: UpdateSettings = field(default_factory=UpdateSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    hotkeys: HotkeysSettings = field(default_factory=HotkeysSettings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ui": asdict(self.ui),
            "paths": asdict(self.paths),
            "perf": asdict(self.perf),
            "notify": asdict(self.notify),
            "net": asdict(self.net),
            "privacy": asdict(self.privacy),
            "update": asdict(self.update),
            "logging": asdict(self.logging),
            "hotkeys": asdict(self.hotkeys),
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AppSettings":
        a = AppSettings()
        if not isinstance(d, dict):
            return a
        a.ui = UISettings(**{**asdict(a.ui), **(d.get("ui") or {})})
        a.paths = PathSettings(**{**asdict(a.paths), **(d.get("paths") or {})})
        a.perf = PerformanceSettings(**{**asdict(a.perf), **(d.get("perf") or {})})
        a.notify = NotificationSettings(**{**asdict(a.notify), **(d.get("notify") or {})})
        a.net = NetworkSettings(**{**asdict(a.net), **(d.get("net") or {})})
        a.privacy = PrivacySettings(**{**asdict(a.privacy), **(d.get("privacy") or {})})
        a.update = UpdateSettings(**{**asdict(a.update), **(d.get("update") or {})})
        a.logging = LoggingSettings(**{**asdict(a.logging), **(d.get("logging") or {})})
        a.hotkeys = HotkeysSettings(**{**asdict(a.hotkeys), **(d.get("hotkeys") or {})})
        return a

class SettingsStore:
    def __init__(self):
        self._settings = AppSettings()
        self._loaded = False
        self._config_dir = _config_dir()
        self._settings_path = _settings_path()
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        try:
            os.makedirs(self._config_dir, exist_ok=True)
        except Exception:
            logger.exception("Failed to create settings directory %s", self._config_dir)

    @property
    def data(self) -> AppSettings:
        self.load()
        return self._settings

    def load(self) -> None:
        if self._loaded:
            return
        path = self._settings_path
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    raw = json.load(fh)
                self._settings = AppSettings.from_dict(raw)
            except json.JSONDecodeError:
                logger.warning("Settings file %s is corrupt; restoring defaults", path)
                self._backup_corrupt_file(path)
                self._settings = AppSettings()
            except Exception:
                logger.exception("Failed to load settings from %s", path)
        self._loaded = True

    def save(self) -> None:
        data = self._settings.to_dict()
        try:
            os.makedirs(self._config_dir, exist_ok=True)
        except Exception:
            logger.exception("Unable to ensure settings directory %s", self._config_dir)
            return
        tmp_path = self._settings_path + '.tmp'
        try:
            with open(tmp_path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._settings_path)
        except Exception:
            logger.exception("Failed to write settings to %s", self._settings_path)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
        else:
            self._loaded = True

    def reset(self) -> None:
        self._settings = AppSettings()
        self._loaded = True
        self.save()

    def _backup_corrupt_file(self, path: str) -> None:
        try:
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup = f"{path}.{ts}.bak"
            shutil.copy2(path, backup)
            logger.warning("Backed up corrupt settings to %s", backup)
        except Exception:
            logger.exception("Failed to back up corrupt settings file %s", path)
# singleton
settings = SettingsStore()
