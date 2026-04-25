# tools/channel_identity_cli.py
# Requirements: yt-dlp, youtube-transcript-api
# Usage (examples):
#   python -u tools/channel_identity_cli.py --url https://youtube.com/@SleepNomad --out-dir ./logs/channel_identity
#   python -u tools/channel_identity_cli.py --url https://youtube.com/@SleepNomad --sort popular --lang en --category Sleep --out-dir D:/Exports/Sleep

from __future__ import annotations
import os, re, json, sys, argparse, time



_YT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


from yt_dlp import YoutubeDL
import requests, re

def eprint_kv(k: str, v: str): print(f"{k}={v}", flush=True)
def pct(n: int): eprint_kv("pct", str(max(0, min(100, int(n)))))

def norm_base(u: str) -> str:
    u = u.strip().rstrip("/")
    return re.sub(r"/(featured|videos|shorts|streams|playlists).*$", "", u, flags=re.I)

def list_url_for_sort(base: str, sort: str) -> str:
    return f"{base}/videos?view=0&sort={'p' if sort=='popular' else 'dd'}"

def extract_ids(entries: list) -> list:
    out = []
    for e in entries or []:
        u = (e.get("url") or "").strip()
        vid = None
        m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", u)
        if m: vid = m.group(1)
        if not vid and "/shorts/" in u:
            tail = u.rstrip("/").split("/")[-1]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", tail): vid = tail
        if not vid:
            cand = e.get("id") or ""
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", cand): vid = cand
        if vid: out.append(vid)
    seen=set(); ordered=[]
    for v in out:
        if v not in seen: seen.add(v); ordered.append(v)
    return ordered

def sanitize(name: str, keep: int = 120) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:keep]).rstrip(" ._-") or "video"

def yt_base_opts():
    cookiefile = os.environ.get("WEJAWI_YT_COOKIES", "").strip()
    opts = {
        "quiet": True, "skip_download": True, "noplaylist": True,
        "socket_timeout": 20, "retries": 3, "http_headers": _YT_HEADERS,
        "check_formats": False, "ignore_no_formats_error": True,
        "extractor_args": {"youtube": {"player_client": ["android","web"]}},
    }
    if cookiefile: opts["cookiefile"] = cookiefile
    return opts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--sort", choices=["latest","popular"], default="latest")
    ap.add_argument("--lang", default="")
    ap.add_argument("--category", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max", type=int, default=10)
    args = ap.parse_args()

    from yt_dlp import YoutubeDL
    from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    txt_dir = os.path.join(out_dir, "transcripts")
    os.makedirs(txt_dir, exist_ok=True)
    out_json = os.path.join(out_dir, f"result_{int(time.time())}.json")

    flat = {**yt_base_opts(), "extract_flat": True, "playlistend": 120}
    full = {**yt_base_opts()}

    base = norm_base(args.url)
    tab = list_url_for_sort(base, args.sort)

    eprint_kv("stage", "list"); pct(3)
    with YoutubeDL(flat) as ydl:
        info = ydl.extract_info(tab, download=False)

    channel_title = info.get("channel") or info.get("title") or info.get("uploader") or "Channel"
    channel_id = info.get("channel_id") or info.get("uploader_id")
    channel_url = info.get("channel_url") or base
    description = info.get("description")
    follower_count = info.get("channel_follower_count") or info.get("uploader_subscriber_count")

    vids = extract_ids(info.get("entries") or [])
    if len(vids) < args.max:
        try:
            with YoutubeDL(full) as ydl:
                ch = ydl.extract_info(base, download=False)
            cid = ch.get("channel_id") or ch.get("uploader_id")
            if cid and cid.startswith("UC"):
                uploads_pl = "UU" + cid[2:]
                with YoutubeDL(flat) as ydl:
                    pli = ydl.extract_info(f"https://www.youtube.com/playlist?list={uploads_pl}", download=False)
                vids += extract_ids(pli.get("entries") or [])
                vids = list(dict.fromkeys(vids))
        except Exception as e:
            eprint_kv("warn", f"fallback_uploads_failed:{e}")

    eprint_kv("info", f"candidates={len(vids)}"); pct(10)

    # per-video meta
    eprint_kv("stage", "video_meta")
    metas = []
    fetch_n = min(60, len(vids))
    with YoutubeDL(full) as ydl:
        for i, vid in enumerate(vids[:fetch_n], 1):
            url = f"https://www.youtube.com/watch?v={vid}"
            v = None
            try:
                v = ydl.extract_info(url, download=False)
            except Exception as e:
                eprint_kv("warn", f"video_rich_fail:{vid}:{e}")
                try:
                    with YoutubeDL(flat) as y2:
                        vflat = y2.extract_info(url, download=False)
                        if isinstance(vflat, dict):
                            v = {"id": vflat.get("id") or vid,
                                 "title": vflat.get("title") or vid,
                                 "webpage_url": url,
                                 "upload_date": vflat.get("upload_date"),
                                 "duration": vflat.get("duration"),
                                 "view_count": vflat.get("view_count")}
                except Exception as e2:
                    eprint_kv("warn", f"video_flat_fail:{vid}:{e2}")
            if v: metas.append(v)
            if i % 4 == 0: pct(10 + int(30 * i / max(1, fetch_n)))

    # sort & trim
    def key_latest(v): d=v.get("upload_date"); return int(d) if d and str(d).isdigit() else -1
    def key_pop(v): c=v.get("view_count"); return int(c) if isinstance(c,int) else -1
    metas.sort(key=key_pop if args.sort=="popular" else key_latest, reverse=True)
    metas = metas[: args.max]

   # transcripts (save .txt + include full text in JSON)
    eprint_kv("stage", "transcripts")
    out_rows = []
    langs_pref = [args.lang, f"{args.lang}-US", f"{args.lang}-GB"] if args.lang and args.lang!="auto" else ["en","en-US","en-GB"]

    def pick_url_from_caps(caps: dict, prefer_codes: list):
        # return (label_prefix, lang_code, url) where prefix is "manual"/"auto"
        def pick(caps_dict):
            for code in prefer_codes + [k for k in (caps_dict or {}).keys() if k not in prefer_codes]:
                lst = (caps_dict or {}).get(code) or []
                if not lst: continue
                lst_sorted = sorted(lst, key=lambda x: (x.get("ext") != "vtt"))
                url = lst_sorted[0].get("url")
                if url: return code, url
            return None, None
        lang, url = pick(caps.get("subtitles") or {})
        if url: return "manual", lang, url
        lang, url = pick(caps.get("automatic_captions") or {})
        if url: return "auto", lang, url
        return None, None, None

    def vtt_to_text(vtt: str) -> str:
        out = []
        for line in vtt.splitlines():
            L = line.strip()
            if not L: continue
            if L.startswith(("WEBVTT","Kind:","Language:","NOTE","STYLE","REGION")): continue
            if "-->" in L: continue
            if re.match(r"^\d+$", L): continue
            out.append(L)
        return " ".join(out)

    # base yt-dlp opts (same as earlier)
    base_opts = yt_base_opts()

    for i, v in enumerate(metas, 1):
        vid = v.get("id"); title = v.get("title") or vid or "Untitled"
        url = v.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
        upload_date = v.get("upload_date"); duration = v.get("duration"); view_count = v.get("view_count")

        tlabel = "none"; ttext = None; tpath = None

        # A) try youtube-transcript-api first
        try:
            from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
            listed = YouTubeTranscriptApi.list_transcripts(vid)
            transcript = None
            for kind, langs in (("manual", langs_pref), ("generated", langs_pref), ("any", [])):
                try:
                    if kind=="manual": transcript = listed.find_manually_created(langs)
                    elif kind=="generated": transcript = listed.find_generated(langs)
                    else:
                        for t in listed: transcript = t; break
                    if transcript:
                        tlabel = f"{'auto' if transcript.is_generated else 'manual'}:{transcript.language_code}"
                        break
                except Exception: pass
            if transcript:
                segs = transcript.fetch()
                ttext = " ".join(s.get("text","").replace("\n"," ").strip() for s in segs if s.get("text"))
        except Exception:
            pass  # fall back below

        # B) fallback via yt-dlp captions if needed
        if not ttext:
            try:
                with YoutubeDL(base_opts) as ydl:
                    info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
                caps = {"subtitles": info.get("subtitles") or {}, "automatic_captions": info.get("automatic_captions") or {}}
                prefix, lang_code, cap_url = pick_url_from_caps(caps, langs_pref)
                if cap_url:
                    _YT_HEADERS = {"User-Agent": base_opts["http_headers"]["User-Agent"], "Accept-Language": base_opts["http_headers"]["Accept-Language"]}
                    resp = requests.get(cap_url, headers=_YT_HEADERS, timeout=25); resp.raise_for_status()
                    ttext = vtt_to_text(resp.text)
                    tlabel = f"{prefix}:{lang_code}"
            except Exception as e:
                eprint_kv("warn", f"subs_fallback:{vid}:{e}")

        if ttext:
            base = sanitize(f"{title} [{vid}]")
            tpath = os.path.join(txt_dir, base + ".txt")
            try:
                with open(tpath, "w", encoding="utf-8") as f:
                    f.write(ttext or "")
            except Exception:
                pass

        out_rows.append({
            "id": vid, "title": title, "url": url,
            "upload_date": upload_date, "duration": duration, "view_count": view_count,
            "transcript_lang": tlabel, "transcript_chars": len(ttext or ""),
            "transcript_text": ttext, "transcript_path": tpath,
        })
        pct(40 + int(60 * i / max(1, len(metas))))

        out_rows.append({
            "id": vid, "title": title, "url": url,
            "upload_date": upload_date,
            "duration": duration, "view_count": view_count,
            "transcript_lang": tlabel,
            "transcript_chars": len(ttext or ""),
            "transcript_text": ttext,            # full text in JSON
            "transcript_path": tpath,            # file path too
        })
        pct(40 + int(60 * i / max(1, len(metas))))

    payload = {
        "channel": {
            "title": channel_title, "id": channel_id, "url": channel_url,
            "subscribers": follower_count, "description": description,
            "category": args.category or ""
        },
        "created_at": int(time.time()),
        "sort": args.sort, "lang": args.lang or "auto",
        "videos": [
            {
                "id": r["id"], "title": r["title"], "url": r["url"],
                "upload_date": (f"{r['upload_date'][:4]}-{r['upload_date'][4:6]}-{r['upload_date'][6:]}"
                                if r.get("upload_date") and len(str(r["upload_date"]))==8 else None),
                "duration": r["duration"], "view_count": r["view_count"],
                "transcript_lang": r["transcript_lang"],
                "transcript_chars": r["transcript_chars"],
                "transcript_text": r["transcript_text"],
                "transcript_path": r["transcript_path"],
            } for r in out_rows
        ],
    }

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    eprint_kv("json_path", out_json); pct(100); eprint_kv("progress", "end")

if __name__ == "__main__":
    main()
