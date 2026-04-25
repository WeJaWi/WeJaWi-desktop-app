from typing import List

def split_text(text: str, max_len: int = 4500) -> List[str]:
    text = text or ""
    if len(text) <= max_len:
        return [text]
    out, buf = [], text.strip()

    def take_piece(s: str, limit: int) -> str:
        if len(s) <= limit: return s
        for sep in ["\n\n", "\r\n\r\n"]:
            i = s.rfind(sep, 0, limit)
            if i != -1: return s[:i+len(sep)]
        i = s.rfind("\n", 0, limit)
        if i != -1: return s[:i+1]
        for mk in [". ", "? ", "! "]:
            i = s.rfind(mk, 0, limit)
            if i != -1: return s[:i+len(mk)]
        i = s.rfind(" ", 0, limit)
        if i != -1: return s[:i+1]
        return s[:limit]

    while buf:
        p = take_piece(buf, max_len)
        out.append(p); buf = buf[len(p):]
    return [x.strip() for x in out if x.strip()]
