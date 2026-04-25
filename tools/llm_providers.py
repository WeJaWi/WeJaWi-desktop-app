# tools/llm_providers.py
# Provider wrappers for OpenAI, xAI (Grok), Anthropic (Claude), Kimi (Moonshot).
# All use only stdlib + requests — no vendor SDKs needed.

from __future__ import annotations
import os, sys, json
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

try:
    import requests
except Exception as e:
    raise RuntimeError("Please install requests:  pip install requests") from e


# ── defaults (overridable via env) ────────────────────────────────────────────

DEFAULT_OPENAI_MODEL    = os.environ.get("WEJAWI_OPENAI_MODEL",     "gpt-4o-mini")
DEFAULT_XAI_MODEL       = os.environ.get("WEJAWI_XAI_MODEL",        "grok-3")
DEFAULT_ANTHROPIC_MODEL = os.environ.get("WEJAWI_ANTHROPIC_MODEL",  "claude-sonnet-4-6")
DEFAULT_KIMI_MODEL      = os.environ.get("WEJAWI_KIMI_MODEL",       "moonshot-v1-32k")

# ── model catalogue (label, model-id) ─────────────────────────────────────────

MODEL_CATALOG: Dict[str, List[Tuple[str, str]]] = {
    "openai": [
        ("GPT-4o  (latest, fast)",            "gpt-4o"),
        ("GPT-4o mini  (cheap, fast)",        "gpt-4o-mini"),
        ("GPT-4 Turbo",                       "gpt-4-turbo"),
        ("GPT-4",                             "gpt-4"),
        ("o3-mini  (reasoning)",              "o3-mini"),
        ("o1-mini  (reasoning)",              "o1-mini"),
        ("GPT-3.5 Turbo",                     "gpt-3.5-turbo"),
    ],
    "xai": [
        ("Grok 3  (latest)",                  "grok-3"),
        ("Grok 3 Mini",                       "grok-3-mini"),
        ("Grok 2",                            "grok-2"),
        ("Grok 2 Mini",                       "grok-2-mini"),
        ("Grok Beta",                         "grok-beta"),
    ],
    "anthropic": [
        ("Claude Opus 4.7  (most capable)",   "claude-opus-4-7"),
        ("Claude Sonnet 4.6  (balanced)",     "claude-sonnet-4-6"),
        ("Claude Haiku 4.5  (fast)",          "claude-haiku-4-5-20251001"),
        ("Claude 3.5 Sonnet",                 "claude-3-5-sonnet-20241022"),
        ("Claude 3.5 Haiku",                  "claude-3-5-haiku-20241022"),
        ("Claude 3 Opus",                     "claude-3-opus-20240229"),
    ],
    "kimi": [
        ("Kimi 128k  (long context)",         "moonshot-v1-128k"),
        ("Kimi 32k",                          "moonshot-v1-32k"),
        ("Kimi 8k  (fast)",                   "moonshot-v1-8k"),
    ],
}

PROVIDER_LABELS: List[Tuple[str, str]] = [
    ("ChatGPT  (OpenAI)",   "openai"),
    ("Grok  (xAI)",         "xai"),
    ("Claude  (Anthropic)", "anthropic"),
    ("Kimi  (Moonshot AI)", "kimi"),
]


# ── config path — aligned with core/app_settings._config_dir() ───────────────

def _config_dir() -> str:
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(root, "WeJaWi")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "WeJaWi")
    return os.path.join(os.path.expanduser("~"), ".config", "wejawi")

def _keys_path() -> str:
    d = _config_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "api_keys.json")


# ── key persistence ───────────────────────────────────────────────────────────

_PROVIDERS = ("openai", "xai", "anthropic", "kimi", "heygen", "youtube")

def load_api_keys() -> Dict[str, str]:
    keys: Dict[str, str] = {}
    # env vars take priority
    env_map = {
        "openai":    "OPENAI_API_KEY",
        "xai":       "XAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "kimi":      "MOONSHOT_API_KEY",
        "heygen":    "HEYGEN_API_KEY",
        "youtube":   "YOUTUBE_API_KEY",
    }
    for provider, env in env_map.items():
        val = os.environ.get(env)
        if val:
            keys[provider] = val
    try:
        with open(_keys_path(), "r", encoding="utf-8") as f:
            saved = json.load(f)
        for p in _PROVIDERS:
            keys.setdefault(p, saved.get(p) or "")
    except Exception:
        pass
    for p in _PROVIDERS:
        keys.setdefault(p, "")
    return keys

def save_api_keys(updates: Dict[str, Optional[str]]) -> None:
    path = _keys_path()
    data: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        pass
    for k, v in updates.items():
        if v is not None:
            data[k] = v
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── message type ──────────────────────────────────────────────────────────────

@dataclass
class ChatMessage:
    role: str       # "system" | "user" | "assistant"
    content: str


# ── providers ─────────────────────────────────────────────────────────────────

class BaseProvider:
    name: str = "base"

    def complete(self, messages: List[ChatMessage], model: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1200,
                 timeout_s: int = 60) -> str:
        raise NotImplementedError

    def test(self) -> str:
        """Return 'ok' or raise with a descriptive error."""
        self.complete([ChatMessage("user", "Hi — respond with one word: 'ok'")],
                      max_tokens=10, timeout_s=15)
        return "ok"


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, api_key: Optional[str] = None,
                 base_url: str = "https://api.openai.com/v1"):
        self.api_key  = api_key or load_api_keys().get("openai") or ""
        self.base_url = base_url.rstrip("/")

    def complete(self, messages: List[ChatMessage], model: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1200,
                 timeout_s: int = 60) -> str:
        if not self.api_key:
            raise RuntimeError("OpenAI API key missing — add it in 🔑 API Storage.")
        model = model or DEFAULT_OPENAI_MODEL
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": model, "temperature": float(temperature),
                  "max_tokens": int(max_tokens),
                  "messages": [m.__dict__ for m in messages]},
            timeout=timeout_s,
        )
        if r.status_code != 200:
            raise RuntimeError(f"OpenAI {r.status_code}: {r.text[:400]}")
        try:
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return r.text


class XAIProvider(BaseProvider):
    name = "xai"

    def __init__(self, api_key: Optional[str] = None,
                 base_url: str = "https://api.x.ai/v1"):
        self.api_key  = api_key or load_api_keys().get("xai") or ""
        self.base_url = base_url.rstrip("/")

    def complete(self, messages: List[ChatMessage], model: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1200,
                 timeout_s: int = 60) -> str:
        if not self.api_key:
            raise RuntimeError("xAI (Grok) API key missing — add it in 🔑 API Storage.")
        model = model or DEFAULT_XAI_MODEL
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": model, "temperature": float(temperature),
                  "max_tokens": int(max_tokens),
                  "messages": [m.__dict__ for m in messages]},
            timeout=timeout_s,
        )
        if r.status_code != 200:
            raise RuntimeError(f"xAI {r.status_code}: {r.text[:400]}")
        try:
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return r.text


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API — NOT OpenAI-compatible, uses its own format."""
    name = "anthropic"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: Optional[str] = None,
                 base_url: str = "https://api.anthropic.com"):
        self.api_key  = api_key or load_api_keys().get("anthropic") or ""
        self.base_url = base_url.rstrip("/")

    def complete(self, messages: List[ChatMessage], model: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1200,
                 timeout_s: int = 60) -> str:
        if not self.api_key:
            raise RuntimeError("Anthropic API key missing — add it in 🔑 API Storage.")
        model = model or DEFAULT_ANTHROPIC_MODEL

        # Anthropic separates the system prompt from conversation messages
        system_parts = [m.content for m in messages if m.role == "system"]
        conv = [{"role": m.role, "content": m.content}
                for m in messages if m.role != "system"]
        if not conv:
            conv = [{"role": "user", "content": "Hi"}]

        payload: dict = {
            "model": model,
            "max_tokens": int(max_tokens),
            "messages": conv,
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        # temperature not supported on some reasoning models — send only if valid
        if 0.0 <= temperature <= 1.0:
            payload["temperature"] = float(temperature)

        r = requests.post(
            f"{self.base_url}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
                "content-type": "application/json",
            },
            json=payload,
            timeout=timeout_s,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Anthropic {r.status_code}: {r.text[:400]}")
        data = r.json()
        try:
            return (data["content"][0]["text"] or "").strip()
        except Exception:
            return json.dumps(data, ensure_ascii=False, indent=2)


class KimiProvider(OpenAIProvider):
    """Moonshot AI (Kimi) — OpenAI-compatible endpoint, different base URL."""
    name = "kimi"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            api_key=api_key or load_api_keys().get("kimi") or "",
            base_url="https://api.moonshot.cn/v1",
        )

    def complete(self, messages: List[ChatMessage], model: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1200,
                 timeout_s: int = 60) -> str:
        if not self.api_key:
            raise RuntimeError("Kimi (Moonshot) API key missing — add it in 🔑 API Storage.")
        model = model or DEFAULT_KIMI_MODEL
        return super().complete(messages, model=model, temperature=temperature,
                                max_tokens=max_tokens, timeout_s=timeout_s)


# ── factory ───────────────────────────────────────────────────────────────────

def provider_from_choice(choice: str,
                         keys: Optional[Dict[str, str]] = None) -> BaseProvider:
    """Return an instantiated provider for the given choice string.

    ``keys`` is a dict with optional entries for openai, xai, anthropic, kimi.
    If omitted, each provider loads from the saved config file.
    """
    keys = keys or {}
    c = (choice or "").lower()
    if c in ("openai", "chatgpt", "gpt", "oai"):
        return OpenAIProvider(api_key=keys.get("openai") or None)
    if c in ("xai", "grok"):
        return XAIProvider(api_key=keys.get("xai") or None)
    if c in ("anthropic", "claude"):
        return AnthropicProvider(api_key=keys.get("anthropic") or None)
    if c in ("kimi", "moonshot"):
        return KimiProvider(api_key=keys.get("kimi") or None)
    raise ValueError(f"Unknown provider '{choice}'. Use: openai, xai, anthropic, kimi.")
