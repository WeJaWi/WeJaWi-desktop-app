from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from .text_split import split_text

@dataclass
class ArgosOptions:
    source: str = "auto"   # ISO 639-1; "auto" supported via langdetect if installed
    target: str = "en"
    max_chunk_chars: int = 4500

class ArgosTranslator:
    def __init__(self, opts: ArgosOptions | None = None):
        self.opts = opts or ArgosOptions()
        try:
            import argostranslate.translate as at  # type: ignore
            import argostranslate.package as ap    # type: ignore
        except Exception as e:
            raise RuntimeError(
                "Argos Translate not installed. Use: pip install argostranslate==1.9.6 (Python 3.12 recommended)."
            ) from e
        self._at = at
        self._ap = ap

    def _auto_detect(self, text: str) -> str:
        if self.opts.source != "auto":
            return self.opts.source
        try:
            from langdetect import detect  # optional
            return detect(text[:4000])
        except Exception:
            return "en"

    def translate(self, text: str, source: Optional[str] = None, target: Optional[str] = None) -> str:
        source = (source or self.opts.source or "auto").lower()
        target = (target or self.opts.target or "en").lower()
        if source == "auto":
            source = self._auto_detect(text)

        installed = self._at.get_installed_languages()
        by_code = {lang.code: lang for lang in installed}
        if source not in by_code:
            raise RuntimeError(f"Argos pair missing: source '{source}'. Install the ({source}->{target}) model.")
        if target not in by_code:
            raise RuntimeError(f"Argos pair missing: target '{target}'. Install the ({source}->{target}) model.")

        pair = by_code[source].get_translation(by_code[target])
        if pair is None:
            raise RuntimeError(f"Argos model for {source}->{target} not installed.")

        out: List[str] = []
        for part in split_text(text, self.opts.max_chunk_chars):
            out.append(pair.translate(part))
        return "".join(out)
