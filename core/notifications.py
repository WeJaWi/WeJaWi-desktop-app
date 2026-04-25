from __future__ import annotations

import base64
import copy
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


def _config_dir() -> str:
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(root, "WeJaWi")
    import sys as _sys
    if _sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "WeJaWi")
    root = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "wejawi")


def _config_path() -> str:
    return os.path.join(_config_dir(), "notifications.json")


@dataclass
class SMTPConfig:
    host: str = ""
    port: int = 587
    security: str = "starttls"  # starttls | ssl | none
    username: str = ""
    password_b64: str = ""
    from_addr: str = ""
    to_addrs: List[str] = None

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": int(self.port),
            "security": self.security,
            "username": self.username,
            "password_b64": self.password_b64,
            "from_addr": self.from_addr,
            "to_addrs": list(self.to_addrs or []),
        }

    @staticmethod
    def from_dict(data: dict) -> "SMTPConfig":
        cfg = SMTPConfig()
        if not isinstance(data, dict):
            return cfg
        cfg.host = data.get("host", "")
        try:
            cfg.port = int(data.get("port", 587) or 587)
        except Exception:
            cfg.port = 587
        cfg.security = data.get("security", "starttls") or "starttls"
        cfg.username = data.get("username", "")
        cfg.password_b64 = data.get("password_b64", "")
        cfg.from_addr = data.get("from_addr", "")
        cfg.to_addrs = list(data.get("to_addrs") or [])
        return cfg

    def set_password(self, password: str) -> None:
        raw = (password or "").encode("utf-8")
        self.password_b64 = base64.b64encode(raw).decode("ascii")

    def get_password(self) -> str:
        try:
            return base64.b64decode(self.password_b64 or "").decode("utf-8")
        except Exception:
            return ""


class NotificationManager:
    """Multi-channel notification routing for WeJaWi."""

    DEFAULT_RULES: Dict[str, Dict[str, Any]] = {
        "browse": {"success": False, "failure": False},
        "stitch": {"success": True, "failure": True},
        "convert": {"success": True, "failure": True},
        "transcribe": {"success": True, "failure": True},
        "footage": {"success": False, "failure": True},
        "mouse_auto": {"success": False, "failure": True},
        "api_storage": {"success": False, "failure": True},
        "automation_editor": {"success": False, "failure": True},
        "captions": {"success": True, "failure": True},
        "more": {"success": False, "failure": False},
    }

    DEFAULT_CHANNEL_OPTIONS: Dict[str, Dict[str, Any]] = {
        "email": {
            "enabled": False,
            "subject_prefix": "[WeJaWi]",
            "include_tool": True,
            "include_event_tag": True,
            "include_timestamp": True,
            "extra_footer": "",
        },
    "windows": {
        "enabled": True,
        "play_sound": True,
        "duration_sec": 8,
        "max_body_length": 220,
        "append_tool": True,
        "append_event": True,
        "show_body": True,
        "keep_on_screen": False,
        "category": "info",  # info | success | warning | error
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": "",
        "parse_mode": "Markdown",
        "include_body": True,
        "include_tool": True,
        "include_event": True,
        "include_timestamp": True,
        "disable_link_preview": True,
        "silent": False,
    },
}

    def __init__(self) -> None:
        self.smtp: SMTPConfig = SMTPConfig()
        self.rules: Dict[str, Dict[str, Any]] = copy.deepcopy(NotificationManager.DEFAULT_RULES)
        self.channel_options: Dict[str, Dict[str, Any]] = copy.deepcopy(NotificationManager.DEFAULT_CHANNEL_OPTIONS)
        self.debounce_minutes: int = 0
        self._channel_callbacks: Dict[str, Callable[[str, str, Dict[str, Any]], None]] = {}
        self._last_sent: Dict[str, float] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def load(self) -> None:
        if self._loaded:
            return
        path = _config_path()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except Exception:
                data = None
            if isinstance(data, dict):
                self.smtp = SMTPConfig.from_dict(data.get("smtp", {}))
                raw_rules = data.get("rules")
                if isinstance(raw_rules, dict):
                    for tool, events in raw_rules.items():
                        if isinstance(events, dict):
                            self.rules.setdefault(tool, {}).update(events)
                raw_channels = data.get("channels")
                if isinstance(raw_channels, dict):
                    for name, defaults in NotificationManager.DEFAULT_CHANNEL_OPTIONS.items():
                        merged = copy.deepcopy(defaults)
                        merged.update(raw_channels.get(name) or {})
                        self.channel_options[name] = merged
                    for name, options in raw_channels.items():
                        if name not in self.channel_options and isinstance(options, dict):
                            self.channel_options[name] = copy.deepcopy(options)
                try:
                    self.debounce_minutes = int(data.get("debounce_minutes", 0) or 0)
                except Exception:
                    self.debounce_minutes = 0
        self._normalize_rules()
        self._loaded = True

    def save(self) -> None:
        os.makedirs(_config_dir(), exist_ok=True)
        data = {
            "smtp": self.smtp.to_dict(),
            "rules": self.rules,
            "channels": self.channel_options,
            "debounce_minutes": int(self.debounce_minutes),
        }
        with open(_config_path(), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def available_channels(self) -> List[str]:
        return list(self.channel_options.keys())

    def register_channel_callback(
        self,
        channel: str,
        callback: Optional[Callable[[str, str, Dict[str, Any]], None]],
    ) -> None:
        if callback is None:
            self._channel_callbacks.pop(channel, None)
        else:
            self._channel_callbacks[channel] = callback

    def set_channel_enabled(self, channel: str, enabled: bool, persist: bool = True) -> None:
        opts = self.channel_options.setdefault(channel, {})
        opts["enabled"] = bool(enabled)
        if persist:
            self.save()

    def set_channel_option(self, channel: str, key: str, value: Any, persist: bool = True) -> None:
        opts = self.channel_options.setdefault(channel, {})
        opts[key] = value
        if persist:
            self.save()

    def set_debounce_minutes(self, minutes: int, persist: bool = True) -> None:
        try:
            minutes = max(0, int(minutes))
        except Exception:
            minutes = 0
        self.debounce_minutes = minutes
        if persist:
            self.save()

    def set_smtp(self, cfg: SMTPConfig, persist: bool = True) -> None:
        self.smtp = cfg
        if persist:
            self.save()

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------
    def _normalize_rules(self) -> None:
        for tool, defaults in NotificationManager.DEFAULT_RULES.items():
            if tool not in self.rules or not isinstance(self.rules[tool], dict):
                self.rules[tool] = copy.deepcopy(defaults)
        for tool, events in list(self.rules.items()):
            if not isinstance(events, dict):
                events = {}
                self.rules[tool] = events
            defaults = NotificationManager.DEFAULT_RULES.get(tool, {})
            for event, default_value in defaults.items():
                events.setdefault(event, default_value)
            for event, raw_value in list(events.items()):
                events[event] = self._normalize_rule_value(raw_value)

    def _normalize_rule_value(self, raw: Any) -> Dict[str, bool]:
        normalized: Dict[str, bool] = {}
        if isinstance(raw, dict):
            for channel in self.channel_options:
                normalized[channel] = bool(raw.get(channel, False))
        else:
            for channel in self.channel_options:
                normalized[channel] = bool(raw) if channel == "email" else False
        return normalized


    def reset_rules(self, persist: bool = True) -> None:
        """Restore channel rules to packaged defaults."""
        self.rules = copy.deepcopy(NotificationManager.DEFAULT_RULES)
        self._normalize_rules()
        if persist:
            self.save()

    def get_rule(self, tool: str, event: str, channel: str = "email") -> bool:
        self.load()
        events = self.rules.get(tool, {})
        value = events.get(event)
        if not isinstance(value, dict):
            value = self._normalize_rule_value(value)
            events[event] = value
        return bool(value.get(channel, False))

    def set_rule(
        self,
        tool: str,
        event: str,
        channel: str = "email",
        enabled: bool = True,
        persist: bool = True,
    ) -> None:
        self.load()
        events = self.rules.setdefault(tool, {})
        value = events.get(event)
        if not isinstance(value, dict):
            value = self._normalize_rule_value(value)
            events[event] = value
        value[channel] = bool(enabled)
        if persist:
            self.save()

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def notify(
        self,
        tool: str,
        event: str,
        subject: str,
        body: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self.load()
        metadata = metadata or {}
        dispatched = False
        for channel_name, options in self.channel_options.items():
            if not isinstance(options, dict):
                continue
            if not options.get("enabled", False):
                continue
            if channel_name == "email" and not self._email_is_configured():
                continue
            if not self._should_send(tool, event, channel_name):
                continue
            if channel_name == "email":
                if self._dispatch_email(subject, body, tool, event, metadata, options):
                    dispatched = True
            elif channel_name == "telegram":
                if not self._telegram_is_configured(options):
                    continue
                if self._dispatch_telegram(subject, body, tool, event, metadata, options):
                    dispatched = True
            else:
                if self._dispatch_callback(channel_name, subject, body, tool, event, metadata, options):
                    dispatched = True
        return dispatched

    def send_test(self, channel: str) -> bool:
        self.load()
        subject = "WeJaWi test notification"
        body = "This is a test message from WeJaWi."
        metadata = {"tool_label": "System", "event_label": "test"}
        if channel == "email":
            if not self._email_is_configured():
                return False
            return self._dispatch_email(
                subject,
                body,
                "test",
                "manual",
                metadata,
                self.channel_options.get("email", {}),
                bypass_rules=True,
            )
        if channel == "telegram":
            options = self.channel_options.get("telegram", {})
            if not self._telegram_is_configured(options):
                return False
            return self._dispatch_telegram(
                subject,
                body,
                "test",
                "manual",
                metadata,
                options,
            )
        return self._dispatch_callback(
            channel,
            subject,
            body,
            "test",
            "manual",
            metadata,
            self.channel_options.get(channel, {}),
            bypass_rules=True,
        )

    def _email_is_configured(self) -> bool:
        cfg = self.smtp
        return bool(cfg.host and cfg.from_addr and cfg.to_addrs)

    def _telegram_is_configured(self, options: Dict[str, Any]) -> bool:
        token = (options.get("bot_token") or "").strip()
        chat_id = str(options.get("chat_id") or "").strip()
        return bool(token and chat_id)

    def _should_send(self, tool: str, event: str, channel: str) -> bool:
        if not self.get_rule(tool, event, channel):
            return False
        if self.debounce_minutes > 0:
            key = f"{channel}:{tool}:{event}"
            now = time.time()
            last = self._last_sent.get(key, 0.0)
            if now - last < self.debounce_minutes * 60:
                return False
            self._last_sent[key] = now
        return True

    def _dispatch_telegram(
        self,
        subject: str,
        body: str,
        tool: str,
        event: str,
        metadata: Dict[str, Any],
        options: Dict[str, Any],
    ) -> bool:
        token = (options.get("bot_token") or "").strip()
        chat_id = str(options.get("chat_id") or "").strip()
        if not token or not chat_id:
            return False
        tool_label = metadata.get("tool_label") or tool
        event_label = metadata.get("event_label") or event
        title = subject.strip() or "Notification"
        if options.get("include_event", True):
            title = f"{title} [{event_label}]"
        lines: List[str] = []
        body_text = body.strip()
        if options.get("include_body", True) and body_text:
            lines.append(body_text)
        if options.get("include_tool", True):
            lines.append(f"Tool: {tool_label}")
        if options.get("include_event", True):
            lines.append(f"Event: {event_label}")
        if options.get("include_timestamp", True):
            lines.append(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        payload_text = title
        if lines:
            payload_text += "\n\n" + "\n".join(lines)
        data = {
            "chat_id": chat_id,
            "text": payload_text,
            "disable_web_page_preview": bool(options.get("disable_link_preview", True)),
            "disable_notification": bool(options.get("silent", False)),
        }
        parse_mode = (options.get("parse_mode") or "").strip()
        if parse_mode:
            data["parse_mode"] = parse_mode
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_text = resp.read()
            parsed = json.loads(resp_text.decode("utf-8") or "{}")
            if isinstance(parsed, dict):
                return bool(parsed.get("ok", False))
            return False
        except (urllib.error.URLError, ValueError, TimeoutError, socket.timeout):
            return False

    def _dispatch_email(
        self,
        subject: str,
        body: str,
        tool: str,
        event: str,
        metadata: Dict[str, Any],
        options: Dict[str, Any],
        bypass_rules: bool = False,
    ) -> bool:
        if not self._email_is_configured():
            return False
        tool_label = metadata.get("tool_label") or tool
        event_label = metadata.get("event_label") or event
        subject_components: List[str] = []
        prefix = (options.get("subject_prefix") or "").strip()
        if prefix:
            subject_components.append(prefix)
        base_subject = subject.strip()
        if base_subject:
            subject_components.append(base_subject)
        if options.get("include_event_tag", True):
            subject_components.append(f"[{event_label}]")
        final_subject = " ".join(part for part in subject_components if part).strip()
        body_sections: List[str] = []
        body_text = body.strip()
        if body_text:
            body_sections.append(body_text)
        if options.get("include_tool", True):
            body_sections.append(f"Tool: {tool_label}")
        if options.get("include_event_tag", True):
            body_sections.append(f"Event: {event_label}")
        if options.get("include_timestamp", True):
            body_sections.append(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        extra = (options.get("extra_footer") or "").strip()
        if extra:
            body_sections.append(extra)
        final_body = "\n\n".join(section for section in body_sections if section)
        self._queue_email(final_subject or subject, final_body or body)
        return True

    def _dispatch_callback(
        self,
        channel: str,
        subject: str,
        body: str,
        tool: str,
        event: str,
        metadata: Dict[str, Any],
        options: Dict[str, Any],
        bypass_rules: bool = False,
    ) -> bool:
        callback = self._channel_callbacks.get(channel)
        if not callback:
            return False
        tool_label = metadata.get("tool_label") or tool
        event_label = metadata.get("event_label") or event
        title = subject.strip() or "Notification"
        if options.get("append_event", True):
            title = f"{title} [{event_label}]"
        lines: List[str] = []
        body_text = body.strip()
        if options.get("show_body", True) and body_text:
            lines.append(body_text)
        if options.get("append_tool", True):
            lines.append(f"Tool: {tool_label}")
        if options.get("append_event", False):
            lines.append(f"Event: {event_label}")
        final_body = "\n".join(line for line in lines if line).strip()
        max_len = options.get("max_body_length")
        if isinstance(max_len, int) and max_len > 0 and len(final_body) > max_len:
            final_body = final_body[: max_len - 1].rstrip() + "…"
        payload = {
            "tool": tool,
            "tool_label": tool_label,
            "event": event,
            "event_label": event_label,
            "options": options,
            "metadata": metadata,
            "raw_subject": subject,
            "raw_body": body,
            "bypass_rules": bypass_rules,
        }
        try:
            callback(title, final_body, payload)
            return True
        except Exception:
            return False

    def _queue_email(self, subject: str, body: str) -> None:
        thread = threading.Thread(target=self._send_email_safe, args=(subject, body), daemon=True)
        thread.start()

    def _send_email_safe(self, subject: str, body: str) -> None:
        try:
            self._send_email(subject, body)
        except Exception:
            pass

    def _send_email(self, subject: str, body: str) -> None:
        cfg = self.smtp
        msg = (
            f"From: {cfg.from_addr}\r\n"
            f"To: {', '.join(cfg.to_addrs)}\r\n"
            f"Subject: {subject}\r\n"
            f"\r\n{body}"
        )
        if cfg.security == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg.host, cfg.port, context=context, timeout=20) as server:
                if cfg.username:
                    server.login(cfg.username, cfg.get_password())
                server.sendmail(cfg.from_addr, cfg.to_addrs, msg.encode("utf-8"))
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=20) as server:
                server.ehlo()
                if cfg.security == "starttls":
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if cfg.username:
                    server.login(cfg.username, cfg.get_password())
                server.sendmail(cfg.from_addr, cfg.to_addrs, msg.encode("utf-8"))


notifier = NotificationManager()
try:
    notifier.load()
except Exception:
    pass
