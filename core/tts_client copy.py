# core/tts_client.py
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional

class VibeVoiceClient:
    """
    Thin wrapper for a local/remote Gradio Space that serves VibeVoice.

    Usage:
        client = VibeVoiceClient(base="http://127.0.0.1:7860")  # or "wixeli/wexli"
        wav_path = client.synthesize(
            script="Alice: Hello!\nBob: Hey Alice.",
            speaker_names=["Alice", "Bob"],
            sample_rate=24000,
            format_name="wav",
        )
    """
    def __init__(self, base: str, api_name: Optional[str] = None, timeout: int = 600) -> None:
        self.base = base.strip()
        self.api_name = api_name
        self.timeout = int(timeout)
        self._client = None
        self._resolved_api = None

    # ---- gradio_client plumbing ----
    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            from gradio_client import Client  # pip install gradio_client
        except Exception as e:
            raise RuntimeError(
                "gradio_client is required. Install it with:  pip install gradio_client"
            ) from e
        self._client = Client(self.base)  # accepts Space id OR URL

    def _view_api(self):
        if self._resolved_api is not None:
            return self._resolved_api
        self._ensure_client()
        apis = self._client.view_api()
        chosen = None
        for ep in apis:
            outs = ep.get("outputs") or []
            has_audio = any(
                (str(o.get("type","")).lower() in ("audio","file") or "audio" in str(o).lower())
                for o in outs
            )
            if has_audio:
                chosen = ep
                break
        if chosen is None:
            chosen = apis[0] if apis else None
        if not chosen:
            raise RuntimeError("No API endpoints exposed by the Space.")
        self.api_name = self.api_name or chosen.get("api_name") or "/predict"
        self._resolved_api = chosen
        return chosen

    def list_inputs(self) -> List[Dict[str, Any]]:
        return self._view_api().get("inputs", [])

    # ---- high-level call ----
    def _build_args(
        self,
        script: str,
        speaker_names: Optional[List[str]] = None,
        seed: Optional[int] = None,
        sample_rate: Optional[int] = None,
        format_name: Optional[str] = None,
        extra_overrides: Optional[Dict[str, Any]] = None
    ) -> List[Any]:
        """
        Map our fields onto the Space inputs by label/type heuristics.
        Unmatched fields are left as None (server defaults).
        """
        inputs = self.list_inputs()
        args: List[Any] = []

        def lab(x): return (x.get("label") or x.get("name") or "").strip().lower()
        def typ(x): return (x.get("type") or "").strip().lower()

        for spec in inputs:
            l, t = lab(spec), typ(spec)
            val = None
            if t in ("text","textbox","textarea") or "script" in l or "text" in l:
                val = script
            elif "speaker" in l:
                if speaker_names:
                    val = ", ".join(speaker_names)
            elif "seed" in l:
                val = seed if seed is not None else 0
            elif ("sr" in l or "sample rate" in l or "samplerate" in l):
                if sample_rate:
                    val = int(sample_rate)
            elif ("format" in l or "file type" in l):
                val = format_name or "wav"
            else:
                if extra_overrides and (spec.get("label") in extra_overrides or l in extra_overrides):
                    key = spec.get("label") if spec.get("label") in extra_overrides else l
                    val = extra_overrides.get(key)
            args.append(val)
        return args

    def synthesize(
        self,
        script: str,
        speaker_names: Optional[List[str]] = None,
        seed: Optional[int] = None,
        sample_rate: Optional[int] = None,
        format_name: Optional[str] = None,
        extra_overrides: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not (script and script.strip()):
            raise RuntimeError("Empty script. Please provide some text.")
        self._ensure_client()
        self._view_api()

        args = self._build_args(
            script=script,
            speaker_names=speaker_names,
            seed=seed,
            sample_rate=sample_rate,
            format_name=format_name,
            extra_overrides=extra_overrides,
        )
        out = self._client.predict(*args, api_name=self.api_name, timeout=self.timeout)
        path = self._extract_file_from_output(out)
        if not path or not os.path.exists(path):
            raise RuntimeError("Space returned no audio file.")
        suffix = os.path.splitext(path)[1] or ".wav"
        fd, tmp_out = tempfile.mkstemp(suffix=suffix, prefix="vibevoice_")
        os.close(fd)
        shutil.copy2(path, tmp_out)
        return tmp_out

    def _extract_file_from_output(self, out: Any) -> Optional[str]:
        def walk(x):
            if not x:
                return None
            if isinstance(x, (list, tuple)):
                for it in x:
                    p = walk(it)
                    if p:
                        return p
                return None
            if isinstance(x, dict):
                for k in ("name","path","filepath","tempfile"):
                    if k in x and isinstance(x[k], str) and os.path.exists(x[k]):
                        return x[k]
                return None
            if isinstance(x, str) and os.path.exists(x):
                return x
            return None
        return walk(out)
