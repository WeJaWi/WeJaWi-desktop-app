# tools/footage_providers.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Iterable
import requests

@dataclass
class MediaItem:
    id: str
    title: str
    author: str
    duration: Optional[float]
    width: Optional[int]
    height: Optional[int]
    thumb_url: str
    media_url: str
    page_url: str
    license: Optional[str] = None
    extra: Dict[str, Any] = None

def _safe_get(d: Dict, path: Iterable[str], default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur

class PexelsProvider:
    BASE = "https://api.pexels.com"
    def __init__(self, api_key: str):
        self.api_key = api_key
    def search_videos(self, query: str, per_page: int = 15, page: int = 1) -> List[MediaItem]:
        url = f"{self.BASE}/videos/search"
        headers = {"Authorization": self.api_key}
        params = {"query": query, "per_page": per_page, "page": page}
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items: List[MediaItem] = []
        for v in data.get("videos", []):
            files = v.get("video_files", [])
            best = None
            for f in files:
                if f.get("link") and f.get("width") and f.get("height"):
                    if not best or (f["width"] * f["height"] > best["width"] * best["height"]):
                        best = f
            if not best and files:
                best = files[0]
            items.append(MediaItem(
                id=str(v.get("id")),
                title=v.get("url", "").split("/")[-1].replace("-", " ").title() or "Pexels Video",
                author=_safe_get(v, ["user", "name"], ""),
                duration=float(v.get("duration") or 0.0),
                width=(best or {}).get("width"),
                height=(best or {}).get("height"),
                thumb_url=_safe_get(v, ["image"], ""),
                media_url=(best or {}).get("link", ""),
                page_url=v.get("url", ""),
                license="Pexels License",
                extra={"source": "pexels"}
            ))
        return items

class PixabayProvider:
    VIDEO_BASE = "https://pixabay.com/api/videos"
    def __init__(self, api_key: str):
        self.api_key = api_key
    def search_videos(self, query: str, per_page: int = 15, page: int = 1) -> List[MediaItem]:
        params = {"key": self.api_key, "q": query, "per_page": per_page, "page": page}
        r = requests.get(self.VIDEO_BASE, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        items: List[MediaItem] = []
        for hit in data.get("hits", []):
            vids = hit.get("videos", {})
            best = None
            for k in ("large", "medium", "small", "tiny"):
                if k in vids and vids[k].get("url"):
                    best = vids[k]; break
            items.append(MediaItem(
                id=str(hit.get("id")),
                title=(hit.get("tags") or "Pixabay Video").title(),
                author=hit.get("user", ""),
                duration=None,
                width=best.get("width") if best else None,
                height=best.get("height") if best else None,
                thumb_url=hit.get("picture_id", "") and f"https://i.vimeocdn.com/video/{hit['picture_id']}_200x150.jpg" or "",
                media_url=best.get("url", "") if best else "",
                page_url=hit.get("pageURL", ""),
                license="Pixabay License",
                extra={"source": "pixabay"}
            ))
        return items

class YouTubeSearchProvider:
    SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
    def __init__(self, api_key: str | None):
        self.api_key = api_key
    def search(self, query: str, max_results: int = 15) -> List[MediaItem]:
        if not self.api_key:
            return []
        params = {"key": self.api_key, "q": query, "part": "snippet", "type": "video", "maxResults": max_results}
        r = requests.get(self.SEARCH_URL, params=params, timeout=30)
        r.raise_for_status()
        search = r.json()
        video_ids = [it["id"]["videoId"] for it in search.get("items", []) if it.get("id", {}).get("videoId")]
        if not video_ids:
            return []
        params2 = {"key": self.api_key, "id": ",".join(video_ids), "part": "contentDetails,snippet,statistics"}
        r2 = requests.get(self.VIDEOS_URL, params=params2, timeout=30)
        r2.raise_for_status()
        details = {it["id"]: it for it in r2.json().get("items", [])}
        def _parse_iso8601(s: str):
            if not s or not s.startswith("PT"): return None
            total = 0.0; num = ""
            for ch in s[2:]:
                if ch.isdigit() or ch == ".": num += ch
                else:
                    if not num: continue
                    val = float(num)
                    if ch == "H": total += val*3600
                    elif ch == "M": total += val*60
                    elif ch == "S": total += val
                    num = ""
            return total or None
        items: List[MediaItem] = []
        for vid in video_ids:
            d = details.get(vid); 
            if not d: continue
            sn = d.get("snippet", {}); cd = d.get("contentDetails", {})
            items.append(MediaItem(
                id=vid,
                title=sn.get("title", ""),
                author=sn.get("channelTitle", ""),
                duration=_parse_iso8601(cd.get("duration", "")),
                width=None, height=None,
                thumb_url=(sn.get("thumbnails", {}).get("medium", {}) or {}).get("url", ""),
                media_url=f"https://www.youtube.com/watch?v={vid}",
                page_url=f"https://www.youtube.com/watch?v={vid}",
                license=None,
                extra={"source": "youtube"}
            ))
        return items
