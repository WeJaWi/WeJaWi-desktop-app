# core/key_store.py
from __future__ import annotations
import os, json, pathlib
from typing import Optional, Dict

CONFIG_PATH = pathlib.Path.home() / ".wejawi_keys.json"

class KeyStore:
    def __init__(self):
        self._cache: Dict[str, str] = {}
        self.reload()

    def reload(self):
        self._cache = {}
        for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "UNSPLASH_ACCESS_KEY", "YOUTUBE_API_KEY"):
            v = os.getenv(k) or ""
            if v:
                self._cache[k] = v
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if k not in self._cache and isinstance(v, str) and v:
                        self._cache[k] = v
            except Exception:
                pass

    def get(self, key: str) -> Optional[str]:
        return self._cache.get(key)

    def save_many(self, mapping: Dict[str, str]) -> None:
        existing = {}
        if CONFIG_PATH.exists():
            try:
                existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        for k, v in mapping.items():
            if isinstance(v, str) and v.strip():
                existing[k] = v.strip()
        CONFIG_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        self.reload()
