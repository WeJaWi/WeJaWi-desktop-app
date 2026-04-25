# core/jobs.py
# Global background job manager + JSONL logging for FFmpeg-like processes (PyQt5).

from __future__ import annotations
import os, json, time, uuid, shutil, datetime, platform
from typing import Dict, Any, Optional
from PyQt5 import QtCore

from core.logging_utils import get_logger

logger = get_logger(__name__)

def _app_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def _logs_root():
    p = os.path.join(_app_root(), "logs")
    os.makedirs(p, exist_ok=True)
    return p

def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p

def _now_iso():
    return datetime.datetime.now().astimezone().isoformat()

def _safe_json_dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

def _which(exe: str) -> Optional[str]:
    from shutil import which
    return which(exe)

def _ff_version() -> Dict[str, Any]:
    info = {}
    ff = _which("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    fp = _which("ffprobe.exe" if os.name == "nt" else "ffprobe")
    for tag, path in (("ffmpeg", ff), ("ffprobe", fp)):
        if path:
            try:
                p = QtCore.QProcess()
                p.start(path, ["-version"])
                p.waitForFinished(3000)
                out = bytes(p.readAllStandardOutput()).decode("utf-8", "ignore")
                info[tag] = {"path": path, "version_line": out.splitlines()[0] if out else ""}
            except Exception:
                info[tag] = {"path": path, "version_line": ""}
    info["python"] = platform.python_version()
    info["platform"] = {"system": platform.system(), "release": platform.release(), "machine": platform.machine()}
    return info

class JSONLogWriter:
    def __init__(self, folder: str, tag: str):
        _ensure_dir(folder)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(folder, f"{tag}_{ts}_{uuid.uuid4().hex[:8]}.jsonl")
        self._fh = open(self.path, "a", encoding="utf-8", buffering=1)
        logger.debug("Created JSON log file %s", self.path)

    def append(self, event: Dict[str, Any]):
        event["ts"] = _now_iso()
        self._fh.write(_safe_json_dump(event) + "\n")

    def close(self):
        try:
            self._fh.close()
            logger.debug("Closed JSON log file %s", self.path)
        except Exception:
            logger.exception("Failed to close log file %s", self.path)

class BackgroundJob(QtCore.QObject):
    progress = QtCore.pyqtSignal(str, int)   # (job_id, pct)
    logline  = QtCore.pyqtSignal(str, str)   # (job_id, text)
    finished = QtCore.pyqtSignal(str, int)   # (job_id, exit_code)

    def __init__(self, job_id: str, cmd: list, duration_s: float, meta: Dict[str, Any], log_writer: JSONLogWriter, parent=None):
        super().__init__(parent)
        self.id = job_id
        self.cmd = cmd
        self.duration_ms = max(1.0, duration_s) * 1000.0
        self.meta = meta
        self.log = log_writer
        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(QtCore.QProcess.SeparateChannels)
        self._proc.readyReadStandardOutput.connect(self._read_out)
        self._proc.readyReadStandardError.connect(self._read_err)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._last_pct = 0
        self._last_logged_bucket = -1

    def start(self):
        self.log.append({"kind": "start", "job_id": self.id, "cmd": self.cmd, "meta": self.meta, "env": _ff_version()})
        cmd_preview = " ".join(str(part) for part in self.cmd)
        logger.info("Job %s starting", self.id)
        logger.debug("Command: %s", cmd_preview)
        logger.debug("Metadata: %s", self.meta)
        self._proc.start(self.cmd[0], self.cmd[1:])

    def cancel(self, wait_ms: int = 0):
        self.log.append({"kind": "cancel", "job_id": self.id})
        logger.info("Cancel requested for job %s", self.id)
        try:
            self._proc.kill()
            if wait_ms and wait_ms > 0:
                self._proc.waitForFinished(wait_ms)
        except Exception:
            logger.exception("Failed to cancel process for job %s", self.id)

    def _read_out(self):
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "ignore")
        for raw in data.splitlines():
            line = raw.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                if k in ("out_time_ms", "bitrate", "total_size", "speed", "dup_frames", "drop_frames", "frame"):
                    self.log.append({"kind": "progress_kv", "job_id": self.id, "k": k, "v": v})
                    if k == "out_time_ms" and v.isdigit():
                        try:
                            ms = float(v)
                            pct = min(99, int(5 + (ms / self.duration_ms) * 93))
                            if pct != self._last_pct:
                                self._last_pct = pct
                                self.progress.emit(self.id, pct)
                        except Exception:
                            pass
                elif k in ("pct", "progress_pct"):
                    self.log.append({"kind": "progress_kv", "job_id": self.id, "k": k, "v": v})
                    try:
                        pct = int(float(v))
                        pct = min(100, max(0, pct))
                        if pct != self._last_pct:
                            self._last_pct = pct
                            if pct // 10 != getattr(self, "_last_logged_bucket", -1):
                                self._last_logged_bucket = pct // 10
                                logger.info("Job %s progress %s%%", self.id, pct)
                            self.progress.emit(self.id, pct)
                    except Exception:
                        logger.exception("Failed to parse progress for job %s: %s=%s", self.id, k, v)
                elif k == "progress" and v == "end":
                    self.progress.emit(self.id, 100)
                    self.log.append({"kind": "progress_end", "job_id": self.id})
                    logger.info("Job %s reported progress end", self.id)
                else:
                    self.log.append({"kind": "progress_kv", "job_id": self.id, "k": k, "v": v})
            else:
                self.log.append({"kind": "stdout", "job_id": self.id, "line": line})
                logger.debug("Job %s stdout: %s", self.id, line)
                self.logline.emit(self.id, line)

    def _read_err(self):
        data = bytes(self._proc.readAllStandardError()).decode("utf-8", "ignore")
        for line in data.splitlines():
            s = line.rstrip()
            if s:
                self.log.append({"kind": "stderr", "job_id": self.id, "line": s})
                if 'error' in s.lower():
                    logger.warning("Job %s stderr: %s", self.id, s)
                else:
                    logger.debug("Job %s stderr: %s", self.id, s)
                self.logline.emit(self.id, s)

    def _on_error(self, error: QtCore.QProcess.ProcessError):
        self.log.append({"kind": "process_error", "job_id": self.id, "error": int(error)})
        logger.error("Job %s process error: %s", self.id, error)

    def _on_finished(self, exitCode, _status):
        self.log.append({"kind": "finish", "job_id": self.id, "exit_code": int(exitCode)})
        exit_code_int = int(exitCode)
        if exit_code_int == 0:
            logger.info("Job %s finished successfully", self.id)
        else:
            logger.warning("Job %s finished with exit code %s", self.id, exit_code_int)
        self.finished.emit(self.id, exit_code_int)
        self.log.close()

class ManualJob(QtCore.QObject):
    progress = QtCore.pyqtSignal(str, int)   # (job_id, pct)
    logline  = QtCore.pyqtSignal(str, str)   # (job_id, text)
    finished = QtCore.pyqtSignal(str, int)   # (job_id, exit_code)

    def __init__(self, job_id: str, meta: Dict[str, Any], log_writer: JSONLogWriter, parent=None, cancel_cb=None):
        super().__init__(parent)
        self.id = job_id
        self.meta = meta or {}
        self.log = log_writer
        self._last_pct = 0
        self._last_bucket = -1
        self._cancel_cb = cancel_cb

    def start(self):
        self.log.append({"kind": "start", "job_id": self.id, "meta": self.meta, "env": _ff_version()})
        logger.info("Manual job %s starting", self.id)

    def set_progress(self, pct: int):
        pct = min(100, max(0, int(pct)))
        if pct != self._last_pct:
            self._last_pct = pct
            self.log.append({"kind": "progress_kv", "job_id": self.id, "k": "pct", "v": str(pct)})
            if pct // 10 != getattr(self, "_last_bucket", -1):
                self._last_bucket = pct // 10
                logger.info("Manual job %s progress %s%%", self.id, pct)
            self.progress.emit(self.id, pct)

    def write_log(self, line: str):
        s = str(line or "")
        self.log.append({"kind": "stdout", "job_id": self.id, "line": s})
        logger.debug("Manual job %s log: %s", self.id, s)
        self.logline.emit(self.id, s)

    def finish(self, exit_code: int = 0):
        self.log.append({"kind": "finish", "job_id": self.id, "exit_code": int(exit_code)})
        code = int(exit_code)
        if code == 0:
            logger.info("Manual job %s finished successfully", self.id)
        else:
            logger.warning("Manual job %s finished with exit code %s", self.id, code)
        self.finished.emit(self.id, code)
        self.log.close()

    def cancel(self):
        self.log.append({"kind": "cancel", "job_id": self.id})
        logger.info("Cancel requested for manual job %s", self.id)
        try:
            if self._cancel_cb:
                self._cancel_cb()
        except Exception:
            logger.exception("Manual job %s cancel callback failed", self.id)

class JobManager(QtCore.QObject):
    jobAdded   = QtCore.pyqtSignal(str, dict)
    jobProgress= QtCore.pyqtSignal(str, int)
    jobLog     = QtCore.pyqtSignal(str, str)
    jobFinished= QtCore.pyqtSignal(str, int)

    _instance: "JobManager" = None

    def __init__(self):
        logger.info("Initialising JobManager")
        super().__init__()
        self.jobs: Dict[str, BackgroundJob] = {}
        self._root = _logs_root()
        _ensure_dir(os.path.join(self._root, "sound_waves"))
        self._prune("sound_waves", keep_last=200)
        _ensure_dir(os.path.join(self._root, "script_writer"))
        self._prune("script_writer", keep_last=200)

    @classmethod
    def instance(cls) -> "JobManager":
        if cls._instance is None:
            cls._instance = JobManager()
        return cls._instance

    def _prune(self, tag: str, keep_last: int = 200):
        folder = os.path.join(self._root, tag)
        if not os.path.isdir(folder): return
        files = sorted([os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".jsonl")], key=os.path.getmtime, reverse=True)
        for p in files[keep_last:]:
            try:
                os.remove(p)
                logger.debug("Pruned old job log %s", p)
            except Exception:
                logger.exception("Failed to prune job log %s", p)

    def start_ffmpeg_job(self, cmd: list, duration_s: float, meta: Dict[str, Any], tag: str = "sound_waves") -> str:
        logger.debug("Starting background job for tag %s", tag)
        job_id = uuid.uuid4().hex
        folder = _ensure_dir(os.path.join(self._root, tag))
        writer = JSONLogWriter(folder, tag)
        meta = dict(meta or {})
        meta["log_path"] = writer.path
        self.jobs[job_id] = BackgroundJob(job_id, cmd, duration_s, meta, writer, parent=self)
        j = self.jobs[job_id]
        j.progress.connect(self.jobProgress)
        j.logline.connect(self.jobLog)
        j.finished.connect(self._on_finished)

        logger.info("Queued background job %s (%s)", job_id, tag)
        logger.debug("Background job %s command: %s", job_id, " ".join(str(part) for part in cmd))
        logger.debug("Background job %s meta: %s", job_id, meta)
        self.jobAdded.emit(job_id, meta)
        j.start()
        return job_id

    def start_process_job(self, cmd: list, meta: Dict[str, Any], tag: str = "general", duration_s: float = 100.0) -> str:
        return self.start_ffmpeg_job(cmd, duration_s, meta, tag)

    def start_manual_job(self, meta: Dict[str, Any], tag: str = "general", cancel_cb=None) -> str:
        """Start a manual (non-process) job that still logs to JSONL and appears in Jobs Center."""
        job_id = uuid.uuid4().hex
        folder = _ensure_dir(os.path.join(self._root, tag))
        writer = JSONLogWriter(folder, tag)
        meta = dict(meta or {})
        meta["log_path"] = writer.path
        j = ManualJob(job_id, meta, writer, parent=self, cancel_cb=cancel_cb)
        self.jobs[job_id] = j
        # pipe manual job signals to global signals
        j.progress.connect(self.jobProgress)
        j.logline.connect(self.jobLog)
        j.finished.connect(self._on_finished)
        # emit added and start
        logger.info("Queued manual job %s (%s)", job_id, tag)
        logger.debug("Manual job %s meta: %s", job_id, meta)
        self.jobAdded.emit(job_id, meta)
        j.start()
        return job_id

    def manual_progress(self, job_id: str, pct: int):
        j = self.jobs.get(job_id)
        if isinstance(j, ManualJob):
            logger.debug("Manual job %s progress update -> %s%%", job_id, pct)
            j.set_progress(pct)

    def manual_log(self, job_id: str, line: str):
        j = self.jobs.get(job_id)
        if isinstance(j, ManualJob):
            logger.debug("Manual job %s log line", job_id)
            j.write_log(line)

    def manual_finish(self, job_id: str, exit_code: int = 0):
        j = self.jobs.get(job_id)
        if isinstance(j, ManualJob):
            logger.debug("Manual job %s finish requested (code=%s)", job_id, exit_code)
            j.finish(exit_code)

    def logs_root(self) -> str:
        return self._root

    def cancel(self, job_id: str):
        j = self.jobs.get(job_id)
        if j:
            logger.info("Cancelling job %s", job_id)
            try:
                if isinstance(j, BackgroundJob):
                    j.cancel(wait_ms=2000)
                else:
                    j.cancel()
            except Exception:
                logger.exception("Failed to cancel job %s", job_id)
        else:
            logger.warning("Cancel requested for unknown job %s", job_id)

    def _on_finished(self, job_id: str, exit_code: int):
        if exit_code == 0:
            logger.info("Job %s completed", job_id)
        else:
            logger.warning("Job %s completed with exit code %s", job_id, exit_code)
        self.jobFinished.emit(job_id, exit_code)
        # self.jobs.pop(job_id, None)

    def shutdown(self, wait_ms: int = 2000):
        logger.info("Shutting down JobManager with %s active jobs", len(self.jobs))
        for job_id, job in list(self.jobs.items()):
            try:
                if isinstance(job, BackgroundJob):
                    logger.debug("Cancelling background job %s", job_id)
                    job.cancel(wait_ms=wait_ms)
                elif isinstance(job, ManualJob):
                    logger.debug("Cancelling manual job %s", job_id)
                    job.cancel()
            except Exception:
                logger.exception("Failed to cancel job %s", job_id)
        self.jobs.clear()
