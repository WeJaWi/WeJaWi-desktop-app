# scene_images.py
"""
Scenes → Images (GPT/Grok + Freepik Classic/Flux/Mystic + WaveSpeed + fal.ai Seedream)

What’s inside
- Prompt gen: xAI Grok or OpenAI GPT (per scene or “AI Split → N prompts”)
- Style presets (incl. “Animated oil paint (warm candlelit)”) + extra tags
- Image gen:
    • Freepik Classic Fast (sync, base64)
    • Freepik Flux Dev (async task + polling, aspect_ratio)
    • Freepik Mystic (LoRA)  (async task + polling, styling.styles/characters)
    • WaveSpeed (default model: chroma) – configurable base/model/size
    • fal.ai Seedream 4.0 – configurable base/model/size
- UI niceties:
    • Scene details tabs (full scene + full prompt), Thumbnail size slider
    • Hide/show Prompt column, Logs in vertical splitter (smaller by default)
    • Output: read-only path + Browse + Open
    • Double-click thumbnail → 80% screen preview
    • Models & prices dialog (sortable table)
    • Mystic: Fetch LoRAs picker (double-click to insert)
    • DYNAMIC UI: shows/hides rows & panels based on the selected generator; disables “Generate” unless a valid key + output folder are present
    • Right panel is scrollable (vertical scrollbar appears when needed)
- Post-save downscale to Max WxH (default 1920×1080)
- Keys can be set here or via env vars. No MoviePy.
"""

import os, json, base64, threading, time, re
from urllib import request
from PyQt5 import QtWidgets, QtCore, QtGui
from core.logging_utils import get_logger
from odf import opendocument, table, text
from odf.opendocument import load
import requests


logger = get_logger(__name__)

# ============================ CONFIG: PUT YOUR KEYS/HOSTS HERE ============================
OPENAI_API_KEY_CONFIG = ""   
XAI_API_KEY_CONFIG    = ""   
FREEPIK_API_KEY_CONFIG = "" 
WAVESPEED_API_KEY_CONFIG  = ""  
FAL_API_KEY_CONFIG          = ""
WAVESPEED_API_BASE_CONFIG   = "https://api.wavespeed.ai"
WAVESPEED_DEFAULT_MODEL     = "wavespeed-ai/chroma"

# fal.ai (Seedream 4.0)

FAL_API_BASE_CONFIG         = "https://fal.run"
FAL_DEFAULT_MODEL           = "fal-ai/seedream/4.0"

# KIE.ai (Seedream)

KIE_API_KEY_CONFIG          = "b75f233665aa1420d089ecb08dd062e1"
KIE_API_BASE_CONFIG         = "https://api.kie.ai"
KIE_DEFAULT_MODEL           = "bytedance/seedream-v4-text-to-image"
KIE_DEFAULT_IMAGE_SIZE      = "square_hd"
KIE_DEFAULT_RESOLUTION      = "1K"
KIE_IMAGE_SIZE_CHOICES      = ["square_hd", "portrait_hd", "landscape_hd", "portrait", "landscape", "square"]
KIE_RESOLUTION_CHOICES      = ["SD", "HD", "1K", "2K", "4K"]

# TensorART

TENSORART_API_KEY_CONFIG    = ""
TENSORART_DEFAULT_MODEL_ID  = "757279507095956705"
TENSORART_DEFAULT_LORA_ID   = "832298395185001638"
TENSORART_DEFAULT_LORA_WEIGHT = 0.8

def _pick_config(default: str, env_name: str, configured: str) -> str:
    env_val = os.environ.get(env_name)
    if env_val and env_val.strip():
        return env_val.strip()
    if configured and configured.strip():
        return configured.strip()
    return default


def get_openai_key() -> str:   return _pick_config("", "OPENAI_API_KEY", OPENAI_API_KEY_CONFIG)
def get_xai_key()    -> str:   return _pick_config("", "XAI_API_KEY",    XAI_API_KEY_CONFIG)
def get_freepik_key()-> str:   return _pick_config("", "FREEPIK_API_KEY", FREEPIK_API_KEY_CONFIG)
def get_ws_key()     -> str:   return _pick_config("", "WAVESPEED_API_KEY", WAVESPEED_API_KEY_CONFIG)
def get_ws_base()    -> str:   return _pick_config("https://api.wavespeed.ai", "WAVESPEED_API_BASE", WAVESPEED_API_BASE_CONFIG)
def get_fal_key()    -> str:   return _pick_config("", "FAL_API_KEY", FAL_API_KEY_CONFIG)
def get_fal_base()   -> str:   return _pick_config("https://fal.run", "FAL_API_BASE", FAL_API_BASE_CONFIG)
def get_kie_key()    -> str:   return _pick_config("", "KIE_API_KEY", KIE_API_KEY_CONFIG)
def get_kie_base()   -> str:   return _pick_config("https://api.kie.ai", "KIE_API_BASE", KIE_API_BASE_CONFIG)
def get_tensorart_key()->str:  return _pick_config("", "TENSORART_API_KEY", TENSORART_API_KEY_CONFIG)


# ============================ TRANSCRIPT HELPERS ============================
try:
    from .captions import parse_srt, parse_vtt, plain_text_to_segments, Segment
except Exception:
    from dataclasses import dataclass
    @dataclass
    class Segment:
        start: float; end: float; text: str
    def parse_srt(text: str): return [Segment(0.0, 0.0, text)]
    def parse_vtt(text: str): return [Segment(0.0, 0.0, text)]
    def plain_text_to_segments(txt: str, total_sec: float):
        words = (txt or '').split()
        chunk = max(10, len(words)//8 or 10)
        out, t = [], 0.0
        for i in range(0, len(words), chunk):
            seg = ' '.join(words[i:i+chunk]); out.append(Segment(t, t+2.0, seg)); t += 2.0
        return out


# ============================ PROMPT PROVIDERS ============================
PROMPT_PROVIDERS = {
    "xAI Grok": {
        "endpoint": "https://api.x.ai/v1/chat/completions",
        "models": ["grok-3-mini", "grok-4-0709", "grok-3"],
        "get_key": get_xai_key,
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "OpenAI GPT": {
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "models": ["gpt-4o-mini", "gpt-4.1-mini", "gpt-3.5-turbo-0125"],
        "get_key": get_openai_key,
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
}


# ============================ FREEPIK ============================
FREEPIK_ENDPOINT_BASE = "https://api.freepik.com/v1/ai/text-to-image"

# Classic sizes (also used to derive Flux/Mystic aspect_ratio tokens)
FREEPIK_SIZES = ["square_1_1", "portrait_4_5", "landscape_16_9"]

# Flux/Mystic expect: "square_1_1", "portrait_4_5", or "widescreen_16_9"
_ASPECT_FROM_SIZE = {
    "square_1_1":     "square_1_1",
    "portrait_4_5":   "portrait_4_5",
    "landscape_16_9": "widescreen_16_9",
}

# Generator choices in this tool
GENERATOR_VARIANTS = [
    "Classic Fast",          # Freepik
    "Flux Dev",              # Freepik
    "Mystic (LoRA)",         # Freepik
    "WaveSpeed",             # WaveSpeed (default chroma)
    "FAL Seedream 4.0",      # fal.ai Seedream
    "KIE Seedream 4.0",      # kie.ai Seedream
    "TensorART",             # TensorART with ODS prompts
]

# Reference table for Models & Prices dialog (credits / image in Freepik app)
FREEPIK_MODEL_PRICES = {
    "Flux 1.0 Fast": 5,
    "Flux 1.0": 10,
    "Flux 1.0 Realism": 40,
    "Flux 1.1": 50,
    "Flux Kontext [Pro]": 70,
    "Flux Kontext [Max]": 150,
    "Mystic 1.0": 45,
    "Mystic 2.5": 50,
    "Mystic 2.5 Flexible": 80,
    "Mystic 2.5 Fluid": 80,
    "Classic Fast": 1,
    "Classic": 1,
    "Google Imagen 3": 50,
    "Google Imagen 4": 150,
    "Ideogram 3": 60,
    "Runway Gen-4 References": 200,
    "GPT": 150,
    "GPT 1 HQ": 500,
    "AI Assistant – GPT4o": 150,
    "AI Assistant – GPT4o High": 500,
    "Seedream 3.0": 100,
}


# ============================ STYLE PRESETS ============================
STYLE_PRESETS = {
    "Cinematic film still": "cinematic still, shallow depth of field, 35mm lens, moody lighting, high dynamic range",
    "Photorealistic": "ultra-photorealistic, detailed textures, natural lighting, true-to-life colors",
    "Studio portrait": "studio portrait, softbox lighting, 85mm lens, crisp focus, skin tone fidelity",
    "Anime": "anime, cel shading, clean lineart, expressive eyes, dynamic action lines",
    "3D render": "high quality 3D render, global illumination, physically based materials, ray traced reflections",
    "Watercolor": "watercolor painting, soft gradients, paper texture, loose brushwork",
    "Oil painting": "oil painting, impasto brush strokes, rich pigments, canvas texture",
    "Cyberpunk neon": "cyberpunk, neon glow, rain-soaked streets, holograms, high contrast",
    "Film noir": "noir, monochrome, hard light shadows, dramatic contrast",
    "Pixar-like 3D": "Pixar style, stylized characters, subsurface scattering, soft lighting",
    "Isometric low-poly": "isometric, low-poly, minimal shading, clean geometric shapes",
    "Botanical illustration": "botanical plate, scientific illustration, fine ink lines, accurate morphology",
    "Architectural viz": "architectural visualization, photoreal interiors, natural daylight, wide-angle lens",
    "Fantasy concept art": "epic fantasy concept art, dramatic lighting, detailed environment, dynamic composition",
    "Ink sketch": "ink sketch, crosshatching, hand-drawn lines, minimal wash",
    "Vaporwave": "vaporwave, retro-futuristic, pastel gradients, Memphis patterns, CRT glow",
    "Retro 90s": "1990s retro aesthetic, VHS scanlines, saturated colors, tape artifacts",
    "Paper cutout": "paper cutout, layered cardstock, shadows between layers, tactile look",
    "Minimal flat": "minimal flat design, vector shapes, simple palette, negative space",
    "Line art": "clean line art, black ink, uniform stroke width, white background",
    # Requested preset:
    "Animated oil paint (warm candlelit)": (
        "animated oil painting, hand-painted frames look, soft impasto brush strokes, "
        "subtle toon/ink outlines, painterly shading, warm candlelight glow, golden hour color grade, "
        "soft bloom, gentle vignette, filmic grain, shallow depth of field"
    ),
}


# ============================ HTTP HELPERS ============================
def _post_json(url: str, payload: dict, headers: dict, timeout=120):
    data = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json", "User-Agent": "WeJaWi/SceneImages/2.1", **headers}
    req = request.Request(url, data=data, headers=merged, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except Exception as e:
        from urllib import error as _urlerr
        if isinstance(e, _urlerr.HTTPError):
            body = e.read().decode("utf-8", errors="ignore")
            try:
                j = json.loads(body)
                msg = (j.get("error", {}).get("message") or j.get("message") or body)
            except Exception:
                msg = body or str(e)
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        raise

def _get_json(url: str, headers: dict, timeout=60):
    req = request.Request(url, headers={"User-Agent":"WeJaWi/SceneImages/2.1", **headers}, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except Exception as e:
        from urllib import error as _urlerr
        if isinstance(e, _urlerr.HTTPError):
            body = e.read().decode("utf-8", errors="ignore")
            try:
                j = json.loads(body)
                msg = (j.get("error", {}).get("message") or j.get("message") or body)
            except Exception:
                msg = body or str(e)
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        raise

def _is_retryable_server_error(msg: str) -> bool:
    if not msg:
        return False
    msg_lower = msg.lower()
    if any(code in msg_lower for code in ("http 500", "http 502", "http 503", "http 504")):
        return True
    return "temporarily unavailable" in msg_lower or "server error" in msg_lower



def _download_to(path: str, url: str):
    with request.urlopen(request.Request(url, headers={"User-Agent":"WeJaWi/SceneImages/2.1"}), timeout=120) as r:
        raw = r.read()
    with open(path, "wb") as f:
        f.write(raw)

def _downscale_png_if_needed(path: str, max_w: int, max_h: int, downscale_only: bool=True):
    """Downscale (never upscale if downscale_only=True) using Qt; keeps aspect ratio."""
    if max_w <= 0 or max_h <= 0: return
    img = QtGui.QImage(path)
    if img.isNull(): return
    w, h = img.width(), img.height()
    if downscale_only and (w <= max_w and h <= max_h): return
    scale = min(max_w / w, max_h / h)
    if downscale_only and scale >= 1.0: return
    new_w, new_h = max(1, int(w*scale)), max(1, int(h*scale))
    scaled = img.scaled(new_w, new_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    scaled.save(path, "PNG")


# ============================ WORKERS ============================
class PromptWorker(QtCore.QObject):
    """Per-scene prompt generator."""
    progress = QtCore.pyqtSignal(int)
    error = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal(list)

    def __init__(self, provider_name: str, model: str, scenes, style_hint: str, temperature: float):
        super().__init__()
        self.provider_name = provider_name
        self.model = model
        self.scenes = scenes
        self.style = style_hint or ""
        self.temp = max(0.0, min(1.0, float(temperature)))

    def start(self): threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        prov = PROMPT_PROVIDERS[self.provider_name]
        key = prov["get_key"]()
        if not key:
            self.error.emit(f"{self.provider_name} key is not set. Edit scene_images.py (or env var).")
            return
        out = []
        try:
            for i, s in enumerate(self.scenes, 1):
                sys_msg = (
                    "You are an expert visual prompt engineer. "
                    "Given a short scene from a transcript, craft ONE concise text-to-image prompt. "
                    "Be concrete: subject, setting, composition, camera lens, lighting, mood, style. "
                    "Return ONLY the prompt string."
                )
                user_msg = f"Scene:\n{s}\n\nStyle hint: {self.style}"
                body = {
                    "model": self.model, "temperature": self.temp,
                    "messages":[{"role":"system","content":sys_msg},{"role":"user","content":user_msg}]
                }
                try:
                    resp = _post_json(prov["endpoint"], body, headers={prov["auth_header"]: prov["auth_prefix"] + key})
                    prompt = (resp.get("choices",[{}])[0].get("message",{}).get("content","")).strip()
                    if not prompt: raise RuntimeError("Empty response from provider.")
                    out.append(prompt)
                except Exception as e:
                    self.error.emit(f"{self.provider_name} error on scene {i}: {e}")
                    return
                self.progress.emit(int(i / max(1, len(self.scenes)) * 100))
            self.done.emit(out)
        except Exception as e:
            self.error.emit(str(e))


class BulkPromptWorker(QtCore.QObject):
    """AI Split → Prompts: feed the whole script and get N prompts back."""
    progress = QtCore.pyqtSignal(int)
    error = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal(list)

    def __init__(self, provider_name: str, model: str, full_text: str, target_n: int, style_hint: str, temperature: float):
        super().__init__()
        self.provider_name=provider_name; self.model=model; self.full_text=full_text or ""
        self.target_n=max(1,int(target_n)); self.style=style_hint or ""; self.temp=max(0.0,min(1.0,float(temperature)))

    def start(self): threading.Thread(target=self._run, daemon=True).start()

    def _parse_prompts(self, content: str):
        try:
            data=json.loads(content)
            if isinstance(data,list):
                out=[]
                for item in data:
                    if isinstance(item,str): out.append(item)
                    elif isinstance(item,dict) and "prompt" in item: out.append(str(item["prompt"]))
                return [s.strip() for s in out if s]
        except Exception:
            pass
        lines=[re.sub(r'^\s*[\-\*\d\.\)]\s*','',x).strip() for x in content.splitlines()]
        return [l for l in lines if l]

    def _run(self):
        prov=PROMPT_PROVIDERS[self.provider_name]; key=prov["get_key"]()
        if not key:
            self.error.emit(f"{self.provider_name} key is not set. Edit scene_images.py (or env var)."); return
        sys_msg=("You are an expert visual director and prompt engineer. "
                 "Given a full video script/transcript, identify the most visually distinct N moments and craft ONE concise text-to-image prompt for each. "
                 "Prompts must be concrete: subject, setting, composition, camera lens, lighting, mood, style tags. "
                 "Respond ONLY with a JSON array of strings.")
        user_msg=f"""N = {self.target_n}
STYLE_HINT = "{self.style}"
SCRIPT:
{self.full_text[:40000]}"""
        body={"model":self.model,"temperature":self.temp,
              "messages":[{"role":"system","content":sys_msg},{"role":"user","content":user_msg}]}
        try:
            resp=_post_json(prov["endpoint"], body, headers={prov["auth_header"]: prov["auth_prefix"] + key})
            content=(resp.get("choices",[{}])[0].get("message",{}).get("content","")).strip()
            prompts=self._parse_prompts(content)
            if not prompts: raise RuntimeError("Provider returned no prompts.")
            if len(prompts)>self.target_n: prompts=prompts[:self.target_n]
            elif len(prompts)<self.target_n: prompts+=[""]*(self.target_n-len(prompts))
            self.done.emit(prompts)
        except Exception as e:
            self.error.emit(f"{self.provider_name} bulk prompting error: {e}")


class GenWorker(QtCore.QObject):
    """
    Handles Classic Fast, Flux Dev, Mystic (LoRA), WaveSpeed (chroma default), fal.ai Seedream 4.0, and KIE Seedream 4.0.
    """
    progress = QtCore.pyqtSignal(int)
    error = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal(list)
    log = QtCore.pyqtSignal(str)

    def __init__(self, prompts, out_dir: str,
                 variant: str, size: str, num_per_prompt: int,
                 max_w: int, max_h: int, downscale_only: bool,
                 fp_key: str,
                 mystic_styles: list, mystic_style_strength: float,
                 mystic_chars: list, mystic_char_strength: float,
                 ws_base: str, ws_key: str, ws_model: str, ws_w: int, ws_h: int,
                 fal_base: str, fal_key: str, fal_model: str, fal_w: int, fal_h: int,
                 kie_base: str, kie_key: str, kie_model: str,
                 kie_w: int, kie_h: int, kie_image_size: str, kie_resolution: str):
        super().__init__()
        self.prompts=prompts; self.out_dir=out_dir
        self.variant=variant; self.size=size; self.num=max(1,int(num_per_prompt))
        self.max_w=max_w; self.max_h=max_h; self.downscale_only=downscale_only

        self.fp_key=fp_key
        self.mystic_styles=mystic_styles; self.mystic_style_strength=mystic_style_strength
        self.mystic_chars=mystic_chars; self.mystic_char_strength=mystic_char_strength

        self.ws_base=ws_base; self.ws_key=ws_key; self.ws_model=ws_model; self.ws_w=ws_w; self.ws_h=ws_h
        self.fal_base=fal_base; self.fal_key=fal_key; self.fal_model=fal_model; self.fal_w=fal_w; self.fal_h=fal_h
        self.kie_base=kie_base; self.kie_key=kie_key; self.kie_model=kie_model
        self.kie_w=kie_w; self.kie_h=kie_h
        self.kie_image_size=kie_image_size
        self.kie_resolution=kie_resolution

    def start(self): threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        os.makedirs(self.out_dir, exist_ok=True)
        saved=[]
        try:
            for i, p in enumerate(self.prompts, 1):
                if not p:
                    self.progress.emit(int(i / max(1, len(self.prompts)) * 100))
                    continue

                if self.variant == "Flux Dev":
                    url = FREEPIK_ENDPOINT_BASE + "/flux-dev"
                    body = {"prompt": p, "aspect_ratio": _ASPECT_FROM_SIZE.get(self.size, "widescreen_16_9")}
                    try:
                        resp=_post_json(url, body, headers={"x-freepik-api-key": self.fp_key})
                        task_id=(resp.get("data") or {}).get("task_id")
                        if not task_id: raise RuntimeError("No task_id returned.")
                    except Exception as e:
                        self.error.emit(f"Freepik Flux Dev create-task error on prompt {i}: {e}"); return
                    poll=FREEPIK_ENDPOINT_BASE + f"/flux-dev/{task_id}"
                    for _ in range(120):
                        try:
                            st=_get_json(poll, headers={"x-freepik-api-key": self.fp_key})
                            data=st.get("data") or {}; status=data.get("status")
                            if status=="COMPLETED":
                                urls=data.get("generated") or []
                                if not urls: raise RuntimeError("Task completed with no images.")
                                for j,u in enumerate(urls,1):
                                    fn=os.path.join(self.out_dir,f"scene_{i:02d}_{j:02d}.png")
                                    _download_to(fn,u)
                                    _downscale_png_if_needed(fn,self.max_w,self.max_h,self.downscale_only)
                                    saved.append(fn)
                                break
                            elif status in ("FAILED","ERROR"): raise RuntimeError(f"Task {task_id} failed.")
                        except Exception as e:
                            msg = str(e)
                            if _is_retryable_server_error(msg):
                                self.log.emit(f"Freepik Flux Dev status warning on prompt {i}: {msg}; retrying...")
                                time.sleep(2.0)
                                continue
                            self.error.emit(f"Freepik Flux Dev status error on prompt {i}: {e}"); return
                        time.sleep(1.0)
                    else:
                        self.error.emit(f"Freepik Flux Dev timeout for task {task_id}."); return

                elif self.variant == "Classic Fast":
                    url=FREEPIK_ENDPOINT_BASE
                    body={"prompt": p, "num_images": self.num, "image":{"size": self.size}, "filter_nsfw": True}
                    try:
                        resp=_post_json(url, body, headers={"x-freepik-api-key": self.fp_key})
                        for j, item in enumerate(resp.get("data") or [], 1):
                            b64=item.get("base64")
                            if not b64: continue
                            raw=base64.b64decode(b64)
                            fn=os.path.join(self.out_dir,f"scene_{i:02d}_{j:02d}.png")
                            with open(fn,"wb") as f: f.write(raw)
                            _downscale_png_if_needed(fn,self.max_w,self.max_h,self.downscale_only)
                            saved.append(fn)
                    except Exception as e:
                        self.error.emit(f"Freepik Classic Fast error on prompt {i}: {e}"); return

                elif self.variant == "Mystic (LoRA)":
                    url = FREEPIK_ENDPOINT_BASE + "/mystic"
                    styling={}
                    if self.mystic_styles:
                        styling["styles"]=[{"name": s.strip(), "strength": float(self.mystic_style_strength)} for s in self.mystic_styles if s.strip()]
                    if self.mystic_chars:
                        styling["characters"]=[{"id": c.strip(), "strength": float(self.mystic_char_strength)} for c in self.mystic_chars if c.strip()]
                    body={"prompt": p, "aspect_ratio": _ASPECT_FROM_SIZE.get(self.size, "widescreen_16_9")}
                    if styling: body["styling"]=styling
                    try:
                        resp=_post_json(url, body, headers={"x-freepik-api-key": self.fp_key})
                        task_id=(resp.get("data") or {}).get("task_id")
                        if not task_id: raise RuntimeError("No task_id returned.")
                    except Exception as e:
                        self.error.emit(f"Freepik Mystic create-task error on prompt {i}: {e}"); return
                    poll=FREEPIK_ENDPOINT_BASE + f"/mystic/{task_id}"
                    for _ in range(120):
                        try:
                            st=_get_json(poll, headers={"x-freepik-api-key": self.fp_key})
                            data=st.get("data") or {}; status=data.get("status")
                            if status=="COMPLETED":
                                urls=data.get("generated") or []
                                if not urls: raise RuntimeError("Task completed with no images.")
                                for j,u in enumerate(urls,1):
                                    fn=os.path.join(self.out_dir,f"scene_{i:02d}_{j:02d}.png")
                                    _download_to(fn,u)
                                    _downscale_png_if_needed(fn,self.max_w,self.max_h,self.downscale_only)
                                    saved.append(fn)
                                break
                            elif status in ("FAILED","ERROR"): raise RuntimeError(f"Task {task_id} failed.")
                        except Exception as e:
                            msg = str(e)
                            if _is_retryable_server_error(msg):
                                self.log.emit(f"Freepik Mystic status warning on prompt {i}: {msg}; retrying...")
                                time.sleep(2.0)
                                continue
                            self.error.emit(f"Freepik Mystic status error on prompt {i}: {e}"); return
                        time.sleep(1.0)
                    else:
                        self.error.emit(f"Freepik Mystic timeout for task {task_id}."); return

                elif self.variant == "WaveSpeed":
                    # Text-to-image endpoint (WaveSpeed accounts differ; this path is generic)
                    base = self.ws_base.rstrip("/")
                    url = base + "/v1/images/generations"
                    body = {
                        "model": self.ws_model, "prompt": p,
                        "width": int(self.ws_w), "height": int(self.ws_h),
                        "n": int(self.num)
                    }
                    try:
                        resp = _post_json(url, body, headers={"Authorization": "Bearer " + self.ws_key})
                    except Exception as e:
                        self.error.emit(f"WaveSpeed request error on prompt {i}: {e}"); return

                    def _extract_images(obj):
                        if isinstance(obj, list): return obj
                        if isinstance(obj, dict):
                            if isinstance(obj.get("data"), list): return obj["data"]
                            if isinstance(obj.get("images"), list): return obj["images"]
                            if isinstance(obj.get("result"), dict) and isinstance(obj["result"].get("images"), list):
                                return obj["result"]["images"]
                        return []

                    items = _extract_images(resp)
                    job_id = None
                    if isinstance(resp, dict):
                        job_id = resp.get("id") or (isinstance(resp.get("data"), dict) and resp["data"].get("id"))

                    if (not items) and job_id:
                        poll_url = f"{base}/v1/images/generations/{job_id}"
                        t0 = time.time()
                        for _ in range(240):
                            try:
                                st = _get_json(poll_url, headers={"Authorization": "Bearer " + self.ws_key})
                            except Exception as e:
                                self.error.emit(f"WaveSpeed poll error on prompt {i}: {e}"); return
                            st_status = (st.get("status") or "").lower() if isinstance(st, dict) else ""
                            if st_status in ("succeeded","completed","done","success"):
                                items = _extract_images(st); break
                            elif st_status in ("failed","error","cancelled","canceled"):
                                self.error.emit(f"WaveSpeed job {job_id} failed."); return
                            else:
                                elapsed = int(time.time() - t0)
                                self.log.emit(f"WaveSpeed still running… {elapsed}s")
                                time.sleep(1.0)
                        else:
                            self.error.emit(f"WaveSpeed job {job_id} timeout."); return

                    if not items:
                        self.error.emit(f"WaveSpeed returned no images for prompt {i}."); return

                    idx = 1
                    for it in items:
                        fn = os.path.join(self.out_dir, f"scene_{i:02d}_{idx:02d}.png")
                        try:
                            if isinstance(it,dict) and it.get("b64"):
                                raw=base64.b64decode(it["b64"]); open(fn,"wb").write(raw)
                            elif isinstance(it,dict) and it.get("base64"):
                                raw=base64.b64decode(it["base64"]); open(fn,"wb").write(raw)
                            elif isinstance(it,dict) and it.get("b64_json"):
                                raw=base64.b64decode(it["b64_json"]); open(fn,"wb").write(raw)
                            elif isinstance(it,dict) and it.get("url"):
                                _download_to(fn, it["url"])
                            elif isinstance(it,str) and it.startswith("http"):
                                _download_to(fn, it)
                            else:
                                self.log.emit("WaveSpeed unknown image item format: " + json.dumps(it)[:200])
                                continue
                            _downscale_png_if_needed(fn,self.max_w,self.max_h,self.downscale_only)
                            saved.append(fn); idx += 1
                        except Exception as e:
                            self.error.emit(f"WaveSpeed save error on prompt {i}: {e}"); return

                elif self.variant == "FAL Seedream 4.0":
                    preferred = (self.fal_base or "").strip()
                    attempts: list[str] = []
                    if preferred:
                        attempts.append(preferred)
                    # Fallback sequence tries the documented fal.run host first, then legacy API host + serverless mirror.
                    attempts.extend([
                        "https://fal.run",
                        "https://fal.run/api",
                        "https://fal-serverless-prod-us-central1.run.app",
                        "https://api.fal.ai",
                    ])

                    body = {
                        "input": {
                            "prompt": p,
                            # Many fal models accept either a string "WxH" or width/height ints. We provide both patterns.
                            "image_size": f"{int(self.fal_w)}x{int(self.fal_h)}",
                            "width": int(self.fal_w),
                            "height": int(self.fal_h),
                            "num_images": int(self.num)
                        }
                    }

                    resp = None
                    base = None
                    last_err = None
                    tried = set()
                    for candidate in attempts:
                        cand = (candidate or "").strip()
                        if not cand or cand in tried:
                            continue
                        tried.add(cand)
                        base_candidate = cand.rstrip("/")
                        # Try known endpoint patterns for the current base.
                        model_slug = self.fal_model.strip()
                        endpoint_patterns = []

                        # Primary patterns (run endpoints)
                        endpoint_patterns.append(f"{base_candidate}/{model_slug}")
                        endpoint_patterns.append(f"{base_candidate}/run/{model_slug}")
                        endpoint_patterns.append(f"{base_candidate}/api/run/{model_slug}")
                        endpoint_patterns.append(f"{base_candidate}/api/v1/run/{model_slug}")
                        endpoint_patterns.append(f"{base_candidate}/v1/run/{model_slug}")

                        # Alternative forms (apps prefix, dashed version removal, versionless)
                        endpoint_patterns.append(f"{base_candidate}/apps/{model_slug}")

                        if "/" in model_slug:
                            org, app_and_ver = model_slug.split("/", 1)
                            if "/" in app_and_ver:
                                app, ver = app_and_ver.rsplit("/", 1)
                            else:
                                app, ver = app_and_ver, ""
                            if ver:
                                endpoint_patterns.append(f"{base_candidate}/{org}/{app}")
                                endpoint_patterns.append(f"{base_candidate}/run/{org}/{app}")
                                endpoint_patterns.append(f"{base_candidate}/apps/{org}/{app}")

                                # Try replacing dots in version with hyphen or removing dot
                                ver_dash = ver.replace(".", "-")
                                ver_nodot = ver.replace(".", "")
                                endpoint_patterns.append(f"{base_candidate}/{org}/{app}-{ver_dash}")
                                endpoint_patterns.append(f"{base_candidate}/{org}/{app}-{ver_nodot}")
                                endpoint_patterns.append(f"{base_candidate}/{org}/{app}/v{ver_nodot}")
                                endpoint_patterns.append(f"{base_candidate}/{org}/{app}/v{ver_dash}")

                        # Deduplicate while preserving order
                        seen_urls = set()
                        endpoint_patterns = [u for u in endpoint_patterns if not (u in seen_urls or seen_urls.add(u))]

                        for url in endpoint_patterns:
                            try:
                                resp = _post_json(url, body, headers={"Authorization": "Key " + self.fal_key})
                                base = base_candidate
                                break
                            except Exception as e:
                                last_err = e
                                msg = str(e).lower()
                                retriable = (
                                    "getaddrinfo failed" in msg or
                                    "name or service not known" in msg or
                                    "http 404" in msg or
                                    "application" in msg and "not found" in msg
                                )
                                if retriable:
                                    try:
                                        self.log.emit(f"fal.ai endpoint '{url}' failed ({e}); trying fallback…")
                                    except Exception:
                                        pass
                                    continue
                                else:
                                    self.error.emit(f"fal.ai request error on prompt {i}: {e}"); return
                        if resp is not None:
                            break

                    if resp is None:
                        self.error.emit(f"fal.ai request error on prompt {i}: {last_err}"); return

                    def _extract_images(obj):
                        if isinstance(obj, list): return obj
                        if isinstance(obj, dict):
                            # Common fal outputs:
                            # {"images":[{"url":...}, ...]} or {"output":{"images":[...]}}
                            if isinstance(obj.get("images"), list): return obj["images"]
                            if isinstance(obj.get("data"), list): return obj["data"]
                            if isinstance(obj.get("output"), dict) and isinstance(obj["output"].get("images"), list):
                                return obj["output"]["images"]
                            if isinstance(obj.get("result"), dict) and isinstance(obj["result"].get("images"), list):
                                return obj["result"]["images"]
                        return []

                    items = _extract_images(resp)
                    # Some fal endpoints return an id and require polling a status url.
                    job_id = resp.get("request_id") or resp.get("id") if isinstance(resp, dict) else None
                    status_url = None
                    if isinstance(resp, dict):
                        status_url = resp.get("status_url") or resp.get("response_url")
                    if (not items) and (status_url or job_id):
                        poll_url = status_url or f"{base}/v1/get/{job_id}"
                        t0 = time.time()
                        for _ in range(240):
                            try:
                                st = _get_json(poll_url, headers={"Authorization": "Key " + self.fal_key})
                            except Exception as e:
                                self.error.emit(f"fal.ai poll error on prompt {i}: {e}"); return
                            st_status = (st.get("status") or "").lower() if isinstance(st, dict) else ""
                            if st_status in ("succeeded","completed","done","success","ready"):
                                items = _extract_images(st); break
                            elif st_status in ("failed","error","cancelled","canceled"):
                                self.error.emit("fal.ai job failed."); return
                            else:
                                elapsed = int(time.time() - t0)
                                self.log.emit(f"fal.ai still running… {elapsed}s")
                                time.sleep(1.0)
                        else:
                            self.error.emit("fal.ai job timeout."); return

                    if not items:
                        self.error.emit(f"fal.ai returned no images for prompt {i}."); return

                    idx = 1
                    for it in items:
                        fn = os.path.join(self.out_dir, f"scene_{i:02d}_{idx:02d}.png")
                        try:
                            if isinstance(it,dict) and it.get("b64"):
                                raw=base64.b64decode(it["b64"]); open(fn,"wb").write(raw)
                            elif isinstance(it,dict) and it.get("base64"):
                                raw=base64.b64decode(it["base64"]); open(fn,"wb").write(raw)
                            elif isinstance(it,dict) and it.get("b64_json"):
                                raw=base64.b64decode(it["b64_json"]); open(fn,"wb").write(raw)
                            elif isinstance(it,dict) and it.get("url"):
                                _download_to(fn, it["url"])
                            elif isinstance(it,str) and it.startswith("http"):
                                _download_to(fn, it)
                            else:
                                self.log.emit("fal.ai unknown image item format: " + json.dumps(it)[:200])
                                continue
                            _downscale_png_if_needed(fn,self.max_w,self.max_h,self.downscale_only)
                            saved.append(fn); idx += 1
                        except Exception as e:
                            self.error.emit(f"fal.ai save error on prompt {i}: {e}"); return

                elif self.variant == "KIE Seedream 4.0":
                    preferred = (self.kie_base or "").strip()
                    base = preferred.rstrip("/") if preferred else "https://api.kie.ai"

                    create_url = f"{base}/api/v1/jobs/createTask"
                    payload = {
                        "model": self.kie_model.strip() or KIE_DEFAULT_MODEL,
                        "input": {
                            "prompt": p,
                            "image_size": (self.kie_image_size or "").strip() or KIE_DEFAULT_IMAGE_SIZE,
                            "image_resolution": (self.kie_resolution or "").strip() or KIE_DEFAULT_RESOLUTION,
                            "max_images": int(self.num),
                        }
                    }
                    # Provide width/height for services that accept custom geometry
                    payload["input"]["width"] = int(self.kie_w)
                    payload["input"]["height"] = int(self.kie_h)

                    headers = {
                        "Authorization": f"Bearer {self.kie_key}",
                        "x-api-key": self.kie_key,
                    }

                    try:
                        resp = _post_json(create_url, payload, headers=headers)
                    except Exception as e:
                        self.error.emit(f"kie.ai request error on prompt {i}: {e}\nVerify the API key/base/model settings.")
                        return

                    def _maybe_json(val):
                        if isinstance(val, str):
                            s = val.strip()
                            if s and s[0] in "{[":
                                try:
                                    return json.loads(s)
                                except Exception:
                                    return val
                        return val

                    def _extract_kie_images(obj):
                        obj = _maybe_json(obj)
                        if isinstance(obj, list):
                            return obj
                        if isinstance(obj, dict):
                            # direct lists first
                            for direct in ("resultUrls", "result_urls", "urls", "images", "outputUrls"):
                                if isinstance(obj.get(direct), list):
                                    return obj[direct]
                            # recurse through known containers
                            for key in ("resultUrls", "result_urls", "urls", "images", "result", "output", "outputs", "data", "resultJson", "result_json"):
                                if key in obj:
                                    imgs = _extract_kie_images(obj[key])
                                    if imgs:
                                        return imgs
                        if isinstance(obj, str) and obj.strip().startswith("http"):
                            return [obj]
                        return []

                    def _extract_kie_status(obj):
                        obj = _maybe_json(obj)
                        if isinstance(obj, str):
                            return obj.lower()
                        if isinstance(obj, dict):
                            for key in ("status", "state", "jobStatus", "taskStatus"):
                                val = obj.get(key)
                                val = _maybe_json(val)
                                if isinstance(val, str):
                                    return val.lower()
                            for key in ("data", "job", "result", "output", "outputs"):
                                if key in obj:
                                    status = _extract_kie_status(obj[key])
                                    if status:
                                        return status
                        return ""

                    def _candidate(value, *suffixes):
                        out = []
                        if value:
                            val = value.rstrip("/")
                            for suf in suffixes:
                                out.append(f"{val}{suf}")
                        return out

                    images = _extract_kie_images(resp)
                    data_block = resp.get("data") if isinstance(resp, dict) else {}
                    job_id = None
                    task_id = None
                    status_url = None
                    if isinstance(data_block, dict):
                        task_id = data_block.get("taskId") or data_block.get("task_id")
                        job_id = data_block.get("jobId") or data_block.get("job_id") or data_block.get("id") or task_id
                        status_url = data_block.get("statusUrl") or data_block.get("resultUrl") or data_block.get("pollUrl")
                        if isinstance(status_url, str) and "?" not in status_url and task_id:
                            status_url = f"{status_url}?taskId={task_id}"
                    if job_id is None and isinstance(resp, dict):
                        job_id = resp.get("jobId") or resp.get("id")

                    poll_urls = []
                    poll_urls.extend(_candidate(status_url, ""))
                    ids_for_query = [x for x in {job_id, task_id} if x]
                    for ident in ids_for_query:
                        poll_urls.extend([
                            f"{base}/api/v1/jobs/recordInfo",
                            f"{base}/api/v1/jobs/getTask",
                            f"{base}/api/v1/jobs/recordInfo?taskId={ident}",
                            f"{base}/api/v1/jobs/getTask?taskId={ident}",
                            f"{base}/api/v1/jobs/getTask?jobId={ident}",
                            f"{base}/api/v1/jobs/{ident}",
                            f"{base}/api/v1/jobs/{ident}/result",
                        ])

                    # Deduplicate while preserving order
                    seen = set()
                    poll_urls = [u for u in poll_urls if u and not (u in seen or seen.add(u))]

                    if not images:
                        success = False
                        for poll_url in poll_urls:
                            try:
                                for _ in range(240):
                                    try:
                                        st = _get_json(poll_url, headers=headers)
                                    except Exception as e:
                                        msg = str(e)
                                        if "404" in msg:
                                            self.log.emit(f"kie.ai status endpoint '{poll_url}' returned 404; trying alternate endpoint.")
                                            break
                                        if "Missing taskId" in msg and "taskId=" not in poll_url and ids_for_query:
                                            break
                                        self.error.emit(f"kie.ai poll error on prompt {i}: {e}")
                                        return
                                    status = _extract_kie_status(st)
                                    imgs = _extract_kie_images(st)
                                    if status in ("success", "succeeded", "completed", "done", "ready") and imgs:
                                        images = imgs
                                        success = True
                                        break
                                    if status in ("failed", "error", "cancelled", "canceled"):
                                        self.error.emit("kie.ai job failed.")
                                        return
                                    time.sleep(1.0)
                                if success:
                                    break
                            except Exception as e:
                                self.error.emit(f"kie.ai poll error on prompt {i}: {e}")
                                return

                        if not images:
                            self.error.emit(f"kie.ai returned no images for prompt {i}.")
                            return

                    idx = 1
                    for it in images:
                        fn = os.path.join(self.out_dir, f"scene_{i:02d}_{idx:02d}.png")
                        try:
                            if isinstance(it, dict):
                                if it.get("b64"):
                                    raw = base64.b64decode(it["b64"]); open(fn, "wb").write(raw)
                                elif it.get("base64"):
                                    raw = base64.b64decode(it["base64"]); open(fn, "wb").write(raw)
                                elif it.get("url"):
                                    _download_to(fn, it["url"])
                                else:
                                    self.log.emit("kie.ai unknown image item format: " + json.dumps(it)[:200])
                                    continue
                            elif isinstance(it, str) and it.startswith("http"):
                                _download_to(fn, it)
                            else:
                                self.log.emit("kie.ai unknown image entry: " + json.dumps(it)[:200])
                                continue
                            _downscale_png_if_needed(fn,self.max_w,self.max_h,self.downscale_only)
                            saved.append(fn); idx += 1
                        except Exception as e:
                            self.error.emit(f"kie.ai save error on prompt {i}: {e}")
                            return

                    def _extract_kie(obj):
                        if isinstance(obj, list):
                            return obj
                        if isinstance(obj, dict):
                            if isinstance(obj.get("images"), list):
                                return obj["images"]
                            if isinstance(obj.get("data"), list):
                                return obj["data"]
                            if isinstance(obj.get("result"), dict):
                                inner = obj["result"]
                                if isinstance(inner.get("images"), list):
                                    return inner["images"]
                            if isinstance(obj.get("output"), dict):
                                inner = obj["output"]
                                if isinstance(inner.get("images"), list):
                                    return inner["images"]
                        return []

                    items = _extract_kie(resp)
                    job_id = None
                    status_url = None
                    if isinstance(resp, dict):
                        job_id = resp.get("id") or resp.get("job_id")
                        status_url = resp.get("status_url") or resp.get("poll_url") or resp.get("result_url")
                    if (not items) and (status_url or job_id):
                        poll_url = status_url or (f"{base}/v1/jobs/{job_id}" if base and job_id else None)
                        if poll_url:
                            t0 = time.time()
                            for _ in range(240):
                                try:
                                    st = _get_json(poll_url, headers=headers)
                                except Exception as e:
                                    self.error.emit(f"kie.ai poll error on prompt {i}: {e}"); return
                                st_status = (st.get("status") or "").lower() if isinstance(st, dict) else ""
                                if st_status in ("succeeded","completed","done","success","ready"):
                                    items = _extract_kie(st)
                                    break
                                elif st_status in ("failed","error","cancelled","canceled"):
                                    self.error.emit("kie.ai job failed."); return
                                else:
                                    elapsed = int(time.time() - t0)
                                    self.log.emit(f"kie.ai still running… {elapsed}s")
                                    time.sleep(1.0)
                            else:
                                self.error.emit("kie.ai job timeout."); return

                    if not items:
                        self.error.emit(f"kie.ai returned no images for prompt {i}."); return

                    idx = 1
                    for it in items:
                        fn = os.path.join(self.out_dir, f"scene_{i:02d}_{idx:02d}.png")
                        try:
                            if isinstance(it, dict):
                                if it.get("b64"):
                                    raw = base64.b64decode(it["b64"]); open(fn, "wb").write(raw)
                                elif it.get("base64"):
                                    raw = base64.b64decode(it["base64"]); open(fn, "wb").write(raw)
                                elif it.get("b64_json"):
                                    raw = base64.b64decode(it["b64_json"]); open(fn, "wb").write(raw)
                                elif it.get("url"):
                                    _download_to(fn, it["url"])
                                else:
                                    self.log.emit("kie.ai unknown image item format: " + json.dumps(it)[:200])
                                    continue
                            elif isinstance(it, str) and it.startswith("http"):
                                _download_to(fn, it)
                            else:
                                self.log.emit("kie.ai unknown image entry: " + json.dumps(it)[:200])
                                continue
                            _downscale_png_if_needed(fn,self.max_w,self.max_h,self.downscale_only)
                            saved.append(fn); idx += 1
                        except Exception as e:
                            self.error.emit(f"kie.ai save error on prompt {i}: {e}"); return

                else:
                    self.error.emit(f"Unknown variant: {self.variant}"); return

                self.progress.emit(int(i / max(1, len(self.prompts)) * 100))
            self.done.emit(saved)
        except Exception as e:
            self.error.emit(str(e))


# ============================ UI ============================
class SceneImagesPage(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SceneImagesPage")
        self._build_ui()
        self._scenes=[]; self._prompts=[]

    # ---------- utility popups / helpers ----------
    def _show_image_dialog(self, path: str):
        if not os.path.exists(path):
            QtWidgets.QMessageBox.warning(self, "Missing file", f"Cannot find image:\n{path}")
            return
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle(os.path.basename(path)); dlg.setModal(True)
        layout=QtWidgets.QVBoxLayout(dlg); scroll=QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        lbl=QtWidgets.QLabel(); lbl.setAlignment(QtCore.Qt.AlignCenter)
        pm=QtGui.QPixmap(path); screen=QtWidgets.QApplication.primaryScreen().availableGeometry()
        max_w=int(screen.width()*0.8); max_h=int(screen.height()*0.8)
        if not pm.isNull(): pm=pm.scaled(max_w,max_h,QtCore.Qt.KeepAspectRatio,QtCore.Qt.SmoothTransformation); lbl.setPixmap(pm)
        scroll.setWidget(lbl); layout.addWidget(scroll)
        btns=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close); btns.rejected.connect(dlg.reject); layout.addWidget(btns)
        dlg.resize(min(max_w,1200), min(max_h,800)); dlg.exec_()

    def _open_output_folder(self):
        path=self.out_dir.text().strip()
        if not path or not os.path.isdir(path):
            QtWidgets.QMessageBox.information(self,"Output","No valid output folder selected."); return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def _row(self,*widgets):
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0,0,0,0)
        h.setSpacing(8)
        for x in widgets:
            h.addWidget(x)
        h.addStretch(1)
        return w

    def _build_ui(self):
        # Root vertical splitter: main content (top) + logs (bottom)
        root_split=QtWidgets.QSplitter(QtCore.Qt.Vertical,self)

        top=QtWidgets.QWidget()
        root=QtWidgets.QVBoxLayout(top); root.setContentsMargins(16,16,16,8); root.setSpacing(10)
        title=QtWidgets.QLabel("🎬 Scenes → Images"); title.setObjectName("PageTitle"); root.addWidget(title)

        split=QtWidgets.QSplitter(QtCore.Qt.Horizontal); root.addWidget(split,1)

        # LEFT pane
        left=QtWidgets.QWidget(); lv=QtWidgets.QVBoxLayout(left); lv.setSpacing(8)

        # RIGHT pane (scrollable)
        right_content=QtWidgets.QWidget()
        rv=QtWidgets.QVBoxLayout(right_content); rv.setSpacing(8)
        right_scroll=QtWidgets.QScrollArea(); right_scroll.setWidgetResizable(True); right_scroll.setWidget(right_content)

        # --- Transcript (left)
        g1=QtWidgets.QGroupBox("1) Transcript"); v1=QtWidgets.QVBoxLayout(g1)
        row=QtWidgets.QHBoxLayout(); self.in_edit=QtWidgets.QLineEdit(); self.in_edit.setPlaceholderText("Paste or load a transcript…")
        b=QtWidgets.QPushButton("Load .srt/.vtt/.txt…"); b.clicked.connect(self._pick_file)
        row.addWidget(self.in_edit,1); row.addWidget(b); v1.addLayout(row)
        self.in_text=QtWidgets.QPlainTextEdit(); self.in_text.setPlaceholderText("…or paste transcript here")
        v1.addWidget(self.in_text,1); lv.addWidget(g1,2)

        # --- Scenes controls (left)
        g2=QtWidgets.QGroupBox("2) Make scenes"); f2=QtWidgets.QFormLayout(g2)
        self.target_n=QtWidgets.QSpinBox(); self.target_n.setRange(1,200); self.target_n.setValue(8)
        self.method=QtWidgets.QComboBox(); self.method.addItems(["Auto (timestamps→text)", "Equal by time", "Equal by text length"])
        self.total_secs=QtWidgets.QDoubleSpinBox(); self.total_secs.setRange(1.0,100000.0); self.total_secs.setValue(60.0); self.total_secs.setDecimals(1)
        self.toggle_prompt_col=QtWidgets.QCheckBox("Show Prompt column"); self.toggle_prompt_col.setChecked(False)
        f2.addRow("Target scenes:",self.target_n); f2.addRow("Split method:",self.method); f2.addRow("Total duration (s):",self.total_secs); f2.addRow("",self.toggle_prompt_col)
        self.btn_split=QtWidgets.QPushButton("Split Scenes"); self.btn_split.clicked.connect(self._split)
        lv.addWidget(g2); lv.addWidget(self.btn_split,0)

        # --- Scenes table (left)
        self.table=QtWidgets.QTableWidget(0,4)
        self.table.setHorizontalHeaderLabels(["#","Time","Excerpt","Prompt"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        lv.addWidget(self.table,1)
        self.table.setColumnHidden(3,True)
        self.toggle_prompt_col.stateChanged.connect(lambda s: self.table.setColumnHidden(3, not self.toggle_prompt_col.isChecked()))

        # --- Scene Details (left)
        g2b=QtWidgets.QGroupBox("Scene details (selected row)"); v2b=QtWidgets.QVBoxLayout(g2b)
        self.details_tabs=QtWidgets.QTabWidget()
        self.scene_full=QtWidgets.QPlainTextEdit(); self.scene_full.setReadOnly(True)
        self.prompt_full=QtWidgets.QPlainTextEdit(); self.prompt_full.setReadOnly(True)
        self.details_tabs.addTab(self.scene_full,"Scene text"); self.details_tabs.addTab(self.prompt_full,"Prompt")
        v2b.addWidget(self.details_tabs); lv.addWidget(g2b,1)

        # --- Prompt generation (right)
        g3=QtWidgets.QGroupBox("3) Prompt generation"); f3=QtWidgets.QFormLayout(g3)
        self.provider=QtWidgets.QComboBox(); self.provider.addItems(list(PROMPT_PROVIDERS.keys()))
        self.model=QtWidgets.QComboBox()
        self.style_preset=QtWidgets.QComboBox(); self.style_preset.addItems(list(STYLE_PRESETS.keys()))
        self.style_extra=QtWidgets.QLineEdit("")
        self.temp=QtWidgets.QDoubleSpinBox(); self.temp.setRange(0.0,1.0); self.temp.setSingleStep(0.1); self.temp.setValue(0.4)
        self.key_state=QtWidgets.QLabel("")
        self.btn_prompts=QtWidgets.QPushButton("Generate Prompts (per selected scenes)"); self.btn_prompts.clicked.connect(self._gen_prompts)
        f3.addRow("Provider:",self.provider); f3.addRow("Model:",self.model); f3.addRow("Style preset:",self.style_preset)
        f3.addRow("Extra style tags:",self.style_extra); f3.addRow("Temperature:",self.temp); f3.addRow("Key status:",self.key_state); f3.addRow("",self.btn_prompts)
        rv.addWidget(g3)

        # --- AI Split → Prompts (right)
        g3b=QtWidgets.QGroupBox("3b) AI Split → Prompts"); f3b=QtWidgets.QFormLayout(g3b)
        self.btn_bulk=QtWidgets.QPushButton("AI Split full script into N prompts"); self.btn_bulk.clicked.connect(self._bulk_prompts)
        self.bulk_note=QtWidgets.QLabel("Uses the full transcript and the selected style to auto-create N prompts."); self.bulk_note.setWordWrap(True)
        f3b.addRow(self.bulk_note); f3b.addRow("",self.btn_bulk); rv.addWidget(g3b)

        # --- Image generation (right)
        g4=QtWidgets.QGroupBox("4) Image generation"); f4=QtWidgets.QFormLayout(g4)

        # Variant + "Models & prices" button
        self.fp_variant=QtWidgets.QComboBox(); self.fp_variant.addItems(GENERATOR_VARIANTS); self.fp_variant.currentTextChanged.connect(self._on_variant_changed)
        self.btn_prices = QtWidgets.QPushButton("Models & prices…"); self.btn_prices.clicked.connect(self._show_models_prices)
        h_variant = QtWidgets.QHBoxLayout(); h_variant.addWidget(self.fp_variant); h_variant.addStretch(1); h_variant.addWidget(self.btn_prices)
        row_variant = QtWidgets.QWidget(); row_variant.setLayout(h_variant)

        self.per_scene=QtWidgets.QSpinBox(); self.per_scene.setRange(1,8); self.per_scene.setValue(1)
        self.img_size=QtWidgets.QComboBox(); self.img_size.addItems(FREEPIK_SIZES)

        # Output folder row
        self.out_dir=QtWidgets.QLineEdit(); self.out_dir.setReadOnly(True); self.out_dir.setPlaceholderText("Select output folder…")
        b2=QtWidgets.QPushButton("Browse…"); b2.clicked.connect(self._pick_out_dir)
        b3=QtWidgets.QPushButton("Open"); b3.clicked.connect(self._open_output_folder)
        row_out=QtWidgets.QHBoxLayout(); row_out.addWidget(self.out_dir,1); row_out.addWidget(b2); row_out.addWidget(b3)
        out_wrap=QtWidgets.QWidget(); out_wrap.setLayout(row_out)

        # Max dims and key states
        self.max_w=QtWidgets.QSpinBox(); self.max_w.setRange(128,8192); self.max_w.setValue(1920)
        self.max_h=QtWidgets.QSpinBox(); self.max_h.setRange(128,8192); self.max_h.setValue(1080)
        self.downscale_only=QtWidgets.QCheckBox("Downscale only"); self.downscale_only.setChecked(True)
        self.fp_key_state=QtWidgets.QLabel("")
        self.ws_key_state=QtWidgets.QLabel("")
        self.fal_key_state=QtWidgets.QLabel("")
        self.kie_key_state=QtWidgets.QLabel("")

        # Mystic (LoRA) section
        self.mystic_box=QtWidgets.QGroupBox("Mystic LoRA"); formM=QtWidgets.QFormLayout(self.mystic_box)
        self.btn_fetch_loras=QtWidgets.QPushButton("Fetch LoRAs…"); self.btn_fetch_loras.clicked.connect(self._fetch_loras)
        self.mystic_styles=QtWidgets.QLineEdit(); self.mystic_styles.setPlaceholderText("style names, comma-separated")
        self.mystic_style_strength=QtWidgets.QDoubleSpinBox(); self.mystic_style_strength.setRange(0.0,1.0); self.mystic_style_strength.setSingleStep(0.05); self.mystic_style_strength.setValue(0.8)
        self.mystic_chars=QtWidgets.QLineEdit(); self.mystic_chars.setPlaceholderText("character IDs, comma-separated")
        self.mystic_char_strength=QtWidgets.QDoubleSpinBox(); self.mystic_char_strength.setRange(0.0,1.0); self.mystic_char_strength.setSingleStep(0.05); self.mystic_char_strength.setValue(0.8)
        formM.addRow(self.btn_fetch_loras); formM.addRow("Style LoRAs:", self.mystic_styles)
        formM.addRow("Style strength:", self.mystic_style_strength); formM.addRow("Character LoRAs:", self.mystic_chars)
        formM.addRow("Character strength:", self.mystic_char_strength)

        # WaveSpeed section
        self.ws_box=QtWidgets.QGroupBox("WaveSpeed"); formW=QtWidgets.QFormLayout(self.ws_box)
        self.ws_base=QtWidgets.QLineEdit(get_ws_base())
        self.ws_model=QtWidgets.QComboBox(); self.ws_model.setEditable(True)
        self.ws_model.addItems([WAVESPEED_DEFAULT_MODEL, "wavespeed-ai/seedream-4.0"])
        self.ws_model.setCurrentText(WAVESPEED_DEFAULT_MODEL)
        self.ws_w=QtWidgets.QSpinBox(); self.ws_w.setRange(128, 2048); self.ws_w.setValue(1024)
        self.ws_h=QtWidgets.QSpinBox(); self.ws_h.setRange(128, 2048); self.ws_h.setValue(768)
        formW.addRow("API base:", self.ws_base); formW.addRow("Model:", self.ws_model)
        formW.addRow("Width × Height:", self._row(self.ws_w, self.ws_h))
        self.ws_key_state.setText("WaveSpeed key: " + ("✔ set in code/env" if get_ws_key() else "✖ missing"))

        # fal.ai section
        self.fal_box=QtWidgets.QGroupBox("fal.ai Seedream"); formF=QtWidgets.QFormLayout(self.fal_box)
        self.fal_base=QtWidgets.QLineEdit(get_fal_base())
        self.fal_model=QtWidgets.QLineEdit(FAL_DEFAULT_MODEL)
        self.fal_w=QtWidgets.QSpinBox(); self.fal_w.setRange(128, 2048); self.fal_w.setValue(1024)
        self.fal_h=QtWidgets.QSpinBox(); self.fal_h.setRange(128, 2048); self.fal_h.setValue(768)
        formF.addRow("API base:", self.fal_base); formF.addRow("Model:", self.fal_model)
        formF.addRow("Width × Height:", self._row(self.fal_w, self.fal_h))
        self.fal_key_state.setText("✔ set in code/env" if get_fal_key() else "✖ missing")

        # KIE.ai section
        self.kie_box=QtWidgets.QGroupBox("KIE.ai Seedream"); formK=QtWidgets.QFormLayout(self.kie_box)
        self.kie_base=QtWidgets.QLineEdit(get_kie_base())
        self.kie_model=QtWidgets.QLineEdit(KIE_DEFAULT_MODEL)
        self.kie_image_size=QtWidgets.QComboBox(); self.kie_image_size.setEditable(True)
        self.kie_image_size.addItems(KIE_IMAGE_SIZE_CHOICES)
        self.kie_image_size.setCurrentText(KIE_DEFAULT_IMAGE_SIZE)
        self.kie_resolution=QtWidgets.QComboBox(); self.kie_resolution.setEditable(True)
        self.kie_resolution.addItems(KIE_RESOLUTION_CHOICES)
        self.kie_resolution.setCurrentText(KIE_DEFAULT_RESOLUTION)
        self.kie_w=QtWidgets.QSpinBox(); self.kie_w.setRange(128, 4096); self.kie_w.setValue(1024)
        self.kie_h=QtWidgets.QSpinBox(); self.kie_h.setRange(128, 4096); self.kie_h.setValue(1024)
        formK.addRow("API base:", self.kie_base)
        formK.addRow("Model:", self.kie_model)
        formK.addRow("Image size:", self.kie_image_size)
        formK.addRow("Resolution:", self.kie_resolution)
        formK.addRow("Width × Height:", self._row(self.kie_w, self.kie_h))
        self.kie_key_state.setText("✔ set in code/env" if get_kie_key() else "✖ missing")

        # Generate button
        self.btn_images=QtWidgets.QPushButton("Generate Selected"); self.btn_images.clicked.connect(self._gen_images)

        # ---------- Build image-gen form (labels stored for dynamic show/hide) ----------
        self.lbl_variant   = QtWidgets.QLabel("Variant:")
        f4.addRow(self.lbl_variant, row_variant)

        self.lbl_per_scene = QtWidgets.QLabel("Images / scene:")
        f4.addRow(self.lbl_per_scene, self.per_scene)

        self.lbl_img_size  = QtWidgets.QLabel("Aspect / Size:")
        f4.addRow(self.lbl_img_size, self.img_size)

        self.lbl_output    = QtWidgets.QLabel("Output:")
        f4.addRow(self.lbl_output, out_wrap)

        self.lbl_max       = QtWidgets.QLabel("Max width × height:")
        f4.addRow(self.lbl_max, self._row(self.max_w, self.max_h))

        f4.addRow("", self.downscale_only)

        self.lbl_fpkey     = QtWidgets.QLabel("Freepik key:")
        f4.addRow(self.lbl_fpkey, self.fp_key_state)

        self.lbl_wskey     = QtWidgets.QLabel("WaveSpeed key:")
        f4.addRow(self.lbl_wskey, self.ws_key_state)

        self.lbl_falkey    = QtWidgets.QLabel("fal.ai key:")
        f4.addRow(self.lbl_falkey, self.fal_key_state)

        self.lbl_kiekey    = QtWidgets.QLabel("kie.ai key:")
        f4.addRow(self.lbl_kiekey, self.kie_key_state)

        f4.addRow(self.mystic_box)
        f4.addRow(self.ws_box)
        f4.addRow(self.fal_box)
        f4.addRow(self.kie_box)
        f4.addRow("", self.btn_images)
        rv.addWidget(g4)

        # --- Preview (with thumbnail size slider) (right)
        g5=QtWidgets.QGroupBox("Saved / Preview"); v5=QtWidgets.QVBoxLayout(g5)
        self.list=QtWidgets.QListWidget()
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setIconSize(QtCore.QSize(160,160))
        self.list.setResizeMode(QtWidgets.QListView.Adjust)
        self.list.setSpacing(8)
        self.list.itemDoubleClicked.connect(lambda it: self._show_image_dialog(it.data(QtCore.Qt.UserRole) or it.text()))

        self.thumb_size = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.thumb_size.setRange(96, 256)
        self.thumb_size.setValue(self.list.iconSize().width())
        self.thumb_size.valueChanged.connect(lambda v: self.list.setIconSize(QtCore.QSize(v, v)))
        lbl_th = QtWidgets.QLabel("Thumbnail size")
        th_row = QtWidgets.QHBoxLayout(); th_row.addWidget(lbl_th); th_row.addWidget(self.thumb_size)
        th_w = QtWidgets.QWidget(); th_w.setLayout(th_row)

        v5.addWidget(th_w, 0)
        v5.addWidget(self.list,1)
        rv.addWidget(g5,1)

        # --- Logs (bottom)
        log_wrap=QtWidgets.QWidget(); log_v=QtWidgets.QVBoxLayout(log_wrap); log_v.setContentsMargins(16,0,16,12)
        self.log=QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(2000); self.log.setPlaceholderText("Logs…")
        log_v.addWidget(self.log)

        # Put panes into splitter
        split.addWidget(left)
        split.addWidget(right_scroll)  # scrollable right side
        split.setStretchFactor(0,3); split.setStretchFactor(1,2)

        # Compose
        root_split.addWidget(top); root_split.addWidget(log_wrap); root_split.setSizes([800,160])
        outer=QtWidgets.QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.addWidget(root_split)

        # dynamic wiring
        self.provider.currentTextChanged.connect(self._on_provider_changed)
        self._on_provider_changed(self.provider.currentText())
        self._update_key_states()
        self._on_variant_changed(self.fp_variant.currentText())
        self.out_dir.textChanged.connect(lambda *_: self._apply_dynamic_ui())

    # ---------- dynamic UI brains ----------
    def _apply_dynamic_ui(self):
        name = self.fp_variant.currentText()
        is_freepik = name in ("Classic Fast", "Flux Dev", "Mystic (LoRA)")
        is_classic = name == "Classic Fast"
        is_mystic  = name == "Mystic (LoRA)"
        is_ws      = name == "WaveSpeed"
        is_fal     = name == "FAL Seedream 4.0"
        is_kie     = name == "KIE Seedream 4.0"

        # Per-scene images: Classic, WaveSpeed, fal.ai, kie.ai
        show_per = is_classic or is_ws or is_fal or is_kie
        self.lbl_per_scene.setVisible(show_per)
        self.per_scene.setVisible(show_per)
        self.lbl_per_scene.setText("Images per prompt:")

        # Size/aspect: Freepik (Classic/Flux/Mystic) only
        show_size = is_freepik
        self.lbl_img_size.setVisible(show_size)
        self.img_size.setVisible(show_size)

        # Keys visibility
        self.lbl_fpkey.setVisible(is_freepik); self.fp_key_state.setVisible(is_freepik)
        self.lbl_wskey.setVisible(is_ws);      self.ws_key_state.setVisible(is_ws)
        self.lbl_falkey.setVisible(is_fal);    self.fal_key_state.setVisible(is_fal)
        self.lbl_kiekey.setVisible(is_kie);    self.kie_key_state.setVisible(is_kie)

        # Sub-panels
        self.mystic_box.setVisible(is_mystic)
        self.ws_box.setVisible(is_ws)
        self.fal_box.setVisible(is_fal)
        self.kie_box.setVisible(is_kie)

        # Enable/disable Generate based on key + output
        if is_freepik:
            key_ok = bool(get_freepik_key())
        elif is_ws:
            key_ok = bool(get_ws_key())
        elif is_fal:
            key_ok = bool(get_fal_key())
        elif is_kie:
            key_ok = bool(get_kie_key())
        else:
            key_ok = True
        out_ok = bool(self.out_dir.text().strip())
        self.btn_images.setEnabled(key_ok and out_ok)

    # ---------- dialogs / pickers ----------
    def _show_models_prices(self):
        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle("Models & Prices (reference)")
        layout=QtWidgets.QVBoxLayout(dlg)
        table=QtWidgets.QTableWidget(0,3); table.setHorizontalHeaderLabels(["Model","Credits / image","API supported here?"])
        table.horizontalHeader().setStretchLastSection(True); table.setSortingEnabled(True)
        supported={"Classic Fast","Flux Dev","Mystic 1.0","Mystic 2.5","Mystic 2.5 Flexible","Mystic 2.5 Fluid"}
        for model,cred in FREEPIK_MODEL_PRICES.items():
            r=table.rowCount(); table.insertRow(r)
            table.setItem(r,0,QtWidgets.QTableWidgetItem(model))
            table.setItem(r,1,QtWidgets.QTableWidgetItem(str(cred)))
            sup = "Yes" if (model in supported or model.startswith("Classic") or model.startswith("Flux")) else "—"
            table.setItem(r,2,QtWidgets.QTableWidgetItem(sup))
        layout.addWidget(table)
        close=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close); close.rejected.connect(dlg.reject); layout.addWidget(close)
        dlg.resize(700, 480); dlg.exec_()

    def _fetch_loras(self):
        key=get_freepik_key()
        if not key:
            QtWidgets.QMessageBox.warning(self,"Freepik key","Set your Freepik API key in code/env first."); return
        try:
            j=_get_json("https://api.freepik.com/v1/ai/loras", headers={"x-freepik-api-key": key})
        except Exception as e:
            QtWidgets.QMessageBox.critical(self,"LoRA fetch error", str(e)); return

        styles = (j.get("styles") or [])
        chars  = (j.get("characters") or [])
        if (not styles and not chars) and isinstance(j.get("data"), list):
            styles = [x for x in j["data"] if isinstance(x,dict) and x.get("type")=="style"]
            chars  = [x for x in j["data"] if isinstance(x,dict) and x.get("type")=="character"]

        dlg=QtWidgets.QDialog(self); dlg.setWindowTitle("Available LoRAs")
        layout=QtWidgets.QVBoxLayout(dlg); tabs=QtWidgets.QTabWidget()
        wS=QtWidgets.QListWidget()
        for s in styles:
            name=s.get("name") or s.get("id") or ""
            if name: wS.addItem(name)
        wC=QtWidgets.QListWidget()
        for c in chars:
            cid=c.get("id") or c.get("name") or ""
            if cid: wC.addItem(cid)
        tabs.addTab(wS,"Styles"); tabs.addTab(wC,"Characters"); layout.addWidget(tabs)
        tip=QtWidgets.QLabel("Double-click to insert into the corresponding field."); tip.setWordWrap(True); layout.addWidget(tip)
        def ins_style(it):
            cur=self.mystic_styles.text().strip(); val=it.text()
            self.mystic_styles.setText( (cur + ", " if cur else "") + val )
        def ins_char(it):
            cur=self.mystic_chars.text().strip(); val=it.text()
            self.mystic_chars.setText( (cur + ", " if cur else "") + val )
        wS.itemDoubleClicked.connect(ins_style); wC.itemDoubleClicked.connect(ins_char)
        close=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close); close.rejected.connect(dlg.reject); layout.addWidget(close)
        dlg.resize(560, 420); dlg.exec_()

    # ---------- selection / status ----------
    def _on_variant_changed(self, name: str):
        self._apply_dynamic_ui()

    def _on_table_selection_changed(self):
        rows=self.table.selectionModel().selectedRows()
        if not rows:
            self.scene_full.setPlainText(""); self.prompt_full.setPlainText(""); return
        r=rows[0].row()
        scene_txt=self._scenes[r] if 0<=r<len(self._scenes) else ""
        prompt_txt=self.table.item(r,3).text() if self.table.item(r,3) else ""
        self.scene_full.setPlainText(scene_txt); self.prompt_full.setPlainText(prompt_txt)

    def _log(self,s:str):
        msg = str(s)
        if msg:
            logger.info("SceneImages: %s", msg)
        self.log.appendPlainText(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _pick_file(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,"Choose transcript","","Subtitles/Transcript (*.srt *.vtt *.txt)")
        if not path: return
        self.in_edit.setText(path)
        try:
            with open(path,"r",encoding="utf-8",errors="ignore") as f: self.in_text.setPlainText(f.read())
        except Exception as e:
            QtWidgets.QMessageBox.critical(self,"Read error",str(e))

    def _pick_out_dir(self):
        d=QtWidgets.QFileDialog.getExistingDirectory(self,"Choose output folder")
        if d: self.out_dir.setText(d)

    def _on_provider_changed(self, name: str):
        self.model.clear()
        for m in PROMPT_PROVIDERS[name]["models"]: self.model.addItem(m)
        self._update_key_states()

    def _update_key_states(self):
        prov=PROMPT_PROVIDERS[self.provider.currentText()]
        self.key_state.setText("✔ set in code/env" if prov["get_key"]() else "✖ missing (edit scene_images.py or env var)")
        self.fp_key_state.setText("✔ set in code/env" if get_freepik_key() else "✖ missing")
        self.ws_key_state.setText("✔ set in code/env" if get_ws_key() else "✖ missing")
        self.fal_key_state.setText("✔ set in code/env" if get_fal_key() else "✖ missing")
        self.kie_key_state.setText("✔ set in code/env" if get_kie_key() else "✖ missing")
        try:
            self._apply_dynamic_ui()
        except Exception:
            pass

    def _current_style_hint(self)->str:
        base=STYLE_PRESETS.get(self.style_preset.currentText(),""); extra=self.style_extra.text().strip()
        return f"{base}, {extra}" if extra else base

    # ---------- split & prompt ----------
    def _split(self):
        raw=self.in_text.toPlainText().strip()
        if not raw:
            QtWidgets.QMessageBox.information(self,"Transcript","Paste or load a transcript first."); return
        want=int(self.target_n.value()); method=self.method.currentIndex()

        segs=[]
        try:
            p=(self.in_edit.text() or "").lower()
            if p.endswith(".srt"): segs=parse_srt(raw)
            elif p.endswith(".vtt"): segs=parse_vtt(raw)
            else: segs=plain_text_to_segments(raw,float(self.total_secs.value()))
        except Exception:
            segs=plain_text_to_segments(raw,float(self.total_secs.value()))

        chunks=[]
        if method in (0,1) and segs and hasattr(segs[0],"start"):
            total=segs[-1].end if segs else float(self.total_secs.value()); step=max(0.01,total/want); cur_end=step; buf=[]
            for s in segs:
                if s.start <= cur_end: buf.append(s.text)
                else: chunks.append(" ".join(buf).strip()); buf=[s.text]; cur_end+=step
            if buf: chunks.append(" ".join(buf).strip())
        else:
            words=raw.split(); per=max(1,len(words)//want)
            for i in range(0,len(words),per): chunks.append(" ".join(words[i:i+per]))

        chunks=[c.strip() for c in chunks if c.strip()]
        if len(chunks)>want: chunks=chunks[:want]
        self._scenes=chunks; self._prompts=[""]*len(chunks)
        self._reload_table(); self._log(f"Split into {len(chunks)} scene(s).")

    def _reload_table(self):
        self.table.setRowCount(0)
        for i,c in enumerate(self._scenes,1):
            r=self.table.rowCount(); self.table.insertRow(r)
            self.table.setItem(r,0,QtWidgets.QTableWidgetItem(str(i)))
            self.table.setItem(r,1,QtWidgets.QTableWidgetItem("—"))
            excerpt=(c[:120]+"…") if len(c)>120 else c
            self.table.setItem(r,2,QtWidgets.QTableWidgetItem(excerpt))
            self.table.setItem(r,3,QtWidgets.QTableWidgetItem(""))
        self.table.setColumnHidden(3, not self.toggle_prompt_col.isChecked())
        self.table.resizeColumnsToContents()

    def _gen_prompts(self):
        if self.table.rowCount()==0:
            QtWidgets.QMessageBox.information(self,"Scenes","Create scenes first (or use AI Split)."); return
        rows=sorted({i.row() for i in self.table.selectionModel().selectedRows()}) or list(range(self.table.rowCount()))
        scenes=[]
        for r in rows:
            sc=self._scenes[r] if 0<=r<len(self._scenes) else (self.table.item(r,2).text() if self.table.item(r,2) else "")
            scenes.append(sc)
        prov=self.provider.currentText()
        if not PROMPT_PROVIDERS[prov]["get_key"]():
            QtWidgets.QMessageBox.warning(self,"API key",f"{prov} key is not set."); return
        style=self._current_style_hint()
        self.btn_prompts.setEnabled(False); self._log(f"Contacting {prov} for {len(scenes)} prompt(s)…")
        w=PromptWorker(prov,self.model.currentText(),scenes,style,self.temp.value())
        def _ok(prompts):
            self.btn_prompts.setEnabled(True)
            for idx,r in enumerate(rows):
                if idx<len(prompts): self.table.setItem(r,3,QtWidgets.QTableWidgetItem(prompts[idx]))
            self._prompts=[self.table.item(r,3).text() if self.table.item(r,3) else "" for r in range(self.table.rowCount())]
            self._on_table_selection_changed(); self._log(f"Generated {len(prompts)} prompt(s).")
        def _err(msg):
            self.btn_prompts.setEnabled(True); self._log(msg); QtWidgets.QMessageBox.critical(self,"Prompt error",msg)
        w.done.connect(_ok); w.error.connect(_err); w.start()

    def _bulk_prompts(self):
        script=self.in_text.toPlainText().strip()
        if not script:
            QtWidgets.QMessageBox.information(self,"Transcript","Paste or load a transcript first."); return
        prov=self.provider.currentText()
        if not PROMPT_PROVIDERS[prov]["get_key"]():
            QtWidgets.QMessageBox.warning(self,"API key",f"{prov} key is not set."); return
        n=int(self.target_n.value()); style=self._current_style_hint()
        self.btn_bulk.setEnabled(False); self._log(f"AI splitting full script into {n} prompts via {prov}…")
        w=BulkPromptWorker(prov,self.model.currentText(),script,n,style,self.temp.value())
        def _ok(prompts):
            self.btn_bulk.setEnabled(True); self._scenes=[""]*len(prompts); self._prompts=prompts
            self._reload_table()
            for r,p in enumerate(prompts): self.table.setItem(r,3,QtWidgets.QTableWidgetItem(p))
            self._on_table_selection_changed(); self._log(f"AI created {len(prompts)} prompt(s).")
        def _err(msg):
            self.btn_bulk.setEnabled(True); self._log(msg); QtWidgets.QMessageBox.critical(self,"AI Split error",msg)
        w.done.connect(_ok); w.error.connect(_err); w.start()

    # ---------- generation ----------
    def _gen_images(self):
        rows=sorted({i.row() for i in self.table.selectionModel().selectedRows()}) or list(range(self.table.rowCount()))
        prompts=[self.table.item(r,3).text().strip() for r in rows if self.table.item(r,3) and self.table.item(r,3).text().strip()]
        if not prompts:
            QtWidgets.QMessageBox.information(self,"Prompts","No prompts to generate. Use per-scene or AI Split first."); return

        variant=self.fp_variant.currentText()
        out_dir=self.out_dir.text().strip()
        if not out_dir: QtWidgets.QMessageBox.warning(self,"Output folder","Pick an output folder."); return

        # Keys
        fp_key=get_freepik_key()
        ws_key=get_ws_key()
        fal_key=get_fal_key()
        kie_key=get_kie_key()

        if variant in ("Classic Fast","Flux Dev","Mystic (LoRA)") and not fp_key:
            QtWidgets.QMessageBox.warning(self,"Freepik key","Set your Freepik API key in code/env."); return
        if variant=="WaveSpeed" and not ws_key:
            QtWidgets.QMessageBox.warning(self,"WaveSpeed key","Set your WaveSpeed API key in code/env."); return
        if variant=="FAL Seedream 4.0" and not fal_key:
            QtWidgets.QMessageBox.warning(self,"fal.ai key","Set your fal.ai API key in code/env."); return
        if variant=="KIE Seedream 4.0" and not kie_key:
            QtWidgets.QMessageBox.warning(self,"kie.ai key","Set your kie.ai API key in code/env."); return

        self.btn_images.setEnabled(False); self._log(f"Requesting {variant} images…")
        mystic_styles=[s.strip() for s in self.mystic_styles.text().split(",") if s.strip()]
        mystic_chars=[c.strip() for c in self.mystic_chars.text().split(",") if c.strip()]
        w=GenWorker(
            prompts=prompts, out_dir=out_dir,
            variant=variant, size=self.img_size.currentText(), num_per_prompt=self.per_scene.value(),
            max_w=self.max_w.value(), max_h=self.max_h.value(), downscale_only=self.downscale_only.isChecked(),
            fp_key=fp_key,
            mystic_styles=mystic_styles, mystic_style_strength=self.mystic_style_strength.value(),
            mystic_chars=mystic_chars, mystic_char_strength=self.mystic_char_strength.value(),
            ws_base=self.ws_base.text().strip(), ws_key=ws_key, ws_model=self.ws_model.currentText().strip(),
            ws_w=self.ws_w.value(), ws_h=self.ws_h.value(),
            fal_base=self.fal_base.text().strip(), fal_key=fal_key, fal_model=self.fal_model.text().strip(),
            fal_w=self.fal_w.value(), fal_h=self.fal_h.value(),
            kie_base=self.kie_base.text().strip(), kie_key=kie_key, kie_model=self.kie_model.text().strip(),
            kie_w=self.kie_w.value(), kie_h=self.kie_h.value(),
            kie_image_size=self.kie_image_size.currentText().strip(),
            kie_resolution=self.kie_resolution.currentText().strip()
        )
        try:
            w.log.connect(self._log)
        except Exception:
            pass

        def _ok(paths):
            self.btn_images.setEnabled(True); self.list.clear()
            for p in paths:
                item=QtWidgets.QListWidgetItem(QtGui.QIcon(p), os.path.basename(p)); item.setData(QtCore.Qt.UserRole,p); self.list.addItem(item)
            self._log(f"Saved {len(paths)} image(s).")
        def _err(msg):
            self.btn_images.setEnabled(True); self._log(msg); QtWidgets.QMessageBox.critical(self,"Generation error",msg)
        w.done.connect(_ok); w.error.connect(_err); w.start()
