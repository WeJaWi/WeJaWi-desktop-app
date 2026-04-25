from __future__ import annotations
from dataclasses import dataclass
from typing import List
from .text_split import split_text

@dataclass
class CT2Options:
    model_dir: str                 # path to CTranslate2 model dir
    tokenizer_path: str            # local HF tokenizer path/name
    model_type: str = "nllb"       # "nllb" or "m2m100"
    device: str = "cpu"            # "cpu" or "cuda"
    compute_type: str = "default"  # "default"|"int8"|"int8_float16"|"float16"
    max_chunk_chars: int = 1200

# ISO 639-1 -> NLLB tags (extend as needed)
_NLLB_TAGS = {
    "en":"eng_Latn","ar":"arb_Arab","zh":"zho_Hans","cs":"ces_Latn","nl":"nld_Latn",
    "fr":"fra_Latn","de":"deu_Latn","el":"ell_Grek","hi":"hin_Deva","hu":"hun_Latn",
    "it":"ita_Latn","ja":"jpn_Jpan","ko":"kor_Hang","pl":"pol_Latn","pt":"por_Latn",
    "ro":"ron_Latn","ru":"rus_Cyrl","sk":"slk_Latn","es":"spa_Latn","sv":"swe_Latn",
    "tr":"tur_Latn","uk":"ukr_Cyrl",
}
def _m2m_tag(code: str) -> str: return f">>{code}<<"

class CT2Translator:
    def __init__(self, opts: CT2Options):
        self.opts = opts
        try:
            import ctranslate2
        except Exception as e:
            raise RuntimeError("Missing ctranslate2. pip install ctranslate2") from e
        try:
            from transformers import AutoTokenizer
        except Exception as e:
            raise RuntimeError("Missing transformers/sentencepiece. pip install transformers sentencepiece") from e

        self._ct2 = ctranslate2
        self._tokenizer = AutoTokenizer.from_pretrained(self.opts.tokenizer_path, local_files_only=True)
        self._translator = ctranslate2.Translator(
            self.opts.model_dir, device=self.opts.device, compute_type=self.opts.compute_type
        )

        if self.opts.model_type.lower() == "m2m100":
            if hasattr(self._tokenizer, "src_lang"): self._tokenizer.src_lang = "en"
            if hasattr(self._tokenizer, "tgt_lang"): self._tokenizer.tgt_lang = "en"

    def _tags(self, src: str, tgt: str):
        mt = self.opts.model_type.lower()
        if mt == "nllb":
            s, t = _NLLB_TAGS.get(src), _NLLB_TAGS.get(tgt)
            if not s or not t:
                raise RuntimeError(f"NLLB tag missing for {src}->{tgt}. Extend _NLLB_TAGS.")
            return s, t
        if mt == "m2m100":
            return _m2m_tag(src), _m2m_tag(tgt)
        raise RuntimeError("model_type must be 'nllb' or 'm2m100'")

    def translate(self, text: str, source: str, target: str) -> str:
        source = (source or "en").lower()
        target = (target or "en").lower()
        src_tag, tgt_tag = self._tags(source, target)

        outputs: List[str] = []
        for part in split_text(text, self.opts.max_chunk_chars):
            if self.opts.model_type.lower() == "m2m100":
                if hasattr(self._tokenizer, "src_lang"): self._tokenizer.src_lang = source
                if hasattr(self._tokenizer, "tgt_lang"): self._tokenizer.tgt_lang = target
                enc = self._tokenizer(part, return_tensors=None)
                tokens = self._tokenizer.convert_ids_to_tokens(enc["input_ids"])
                res = self._translator.translate_batch(
                    [tokens], beam_size=4, max_decoding_length=512, target_prefix=[[tgt_tag]]
                )
                pred_tokens = res[0].hypotheses[0]
                out = self._tokenizer.decode(self._tokenizer.convert_tokens_to_ids(pred_tokens), skip_special_tokens=True)
            else:
                src_tokens = [src_tag] + self._tokenizer.tokenize(part)
                res = self._translator.translate_batch(
                    [src_tokens], beam_size=4, max_decoding_length=512, target_prefix=[[tgt_tag]]
                )
                pred_tokens = res[0].hypotheses[0]
                out = self._tokenizer.convert_tokens_to_string(pred_tokens)
            outputs.append(out)
        return "".join(outputs)
