"""YouTube transcript helpers.

This module reads public caption tracks only. It never downloads video/audio; the
Whisper/audio fallback is owned by the direct command integration layer.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:  # yt-dlp is already a project dependency; tests replace these seams.
    import yt_dlp  # type: ignore
except Exception:  # pragma: no cover - exercised only in missing optional dep envs
    yt_dlp = None

from ..comun.config import DATA_DIR
from ..comun import net

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_MAX_VIDEO_SECONDS = 4 * 60 * 60
_TRANSCRIPT_TTL = 7 * 24 * 3600
_NEGATIVE_TTL = 6 * 3600
_CACHE_MAX = 200
_LIMIT_COOLDOWN = 20 * 60

_CACHE: dict[str, dict] = {}
_LIMIT_UNTIL = 0.0


class Limite(Exception):
    """YouTube rate-limited transcript access."""


@dataclass(frozen=True)
class _ScoreLine:
    score: int
    index: int


def _cache_path() -> Path:
    return DATA_DIR / "youtube_transcripts.json"


def _load_disk_cache() -> dict:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_disk_cache(data: dict) -> None:
    try:
        if len(data) > _CACHE_MAX:
            keep = sorted(data.items(), key=lambda kv: kv[1].get("ts", 0))[-_CACHE_MAX:]
            data = dict(keep)
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


def _cache() -> dict:
    global _CACHE
    if not _CACHE:
        _CACHE = _load_disk_cache()
    return _CACHE


def _reset_estado() -> None:
    """Reset cache/cooldown state for deterministic tests."""
    global _CACHE, _LIMIT_UNTIL
    _CACHE = {}
    _LIMIT_UNTIL = 0.0
    try:
        _cache_path().unlink(missing_ok=True)
    except Exception:
        pass


def id_de_url(texto: str | None) -> str | None:
    """Return a YouTube video id from a URL or raw 11-char id."""
    s = (texto or "").strip()
    if _VIDEO_ID_RE.match(s):
        return s

    m = re.search(r"https?://[^\s)]+", s)
    url = m.group(0) if m else s
    try:
        p = urlparse(url)
    except Exception:
        return None
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"youtube.com", "m.youtube.com", "youtu.be"}:
        return None

    if host == "youtu.be":
        cand = p.path.strip("/").split("/")[0]
        return cand if _VIDEO_ID_RE.match(cand) else None

    if p.path == "/watch":
        cand = parse_qs(p.query).get("v", [None])[0]
        return cand if cand and _VIDEO_ID_RE.match(cand) else None
    if p.path.startswith("/shorts/") or p.path.startswith("/embed/"):
        cand = p.path.strip("/").split("/")[1]
        return cand if _VIDEO_ID_RE.match(cand) else None
    return None


def es_url_youtube(texto: str | None) -> bool:
    return id_de_url(texto) is not None


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def _parse_json3(data: dict | str | bytes) -> list[tuple[float, str]]:
    """Parse a YouTube json3 caption track into (seconds, text) lines."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    if isinstance(data, str):
        data = json.loads(data)
    out: list[tuple[float, str]] = []
    for ev in (data or {}).get("events", []) or []:
        segs = ev.get("segs") or []
        text = _clean_text("".join(str(seg.get("utf8", "")) for seg in segs))
        if not text:
            continue
        out.append((float(ev.get("tStartMs", 0)) / 1000.0, text))
    return out


def _idioma_base(code: str | None) -> str:
    return (code or "").split("-", 1)[0].lower()


def _json3_url(entries: list[dict] | None) -> str | None:
    for e in entries or []:
        if (e.get("ext") or "").lower() == "json3" and e.get("url"):
            return str(e["url"])
    return None


def _matches_requested(code: str, idiomas: tuple[str, ...]) -> bool:
    base = _idioma_base(code)
    wanted = {_idioma_base(i) for i in idiomas if i}
    return not wanted or base in wanted


def _is_auto_translation(code: str, video_lang: str) -> bool:
    c = (code or "").lower()
    base = _idioma_base(c)
    v = _idioma_base(video_lang)
    # Accept original automatic variants only. Reject e.g. es-en / en-de-DE.
    if c.endswith("-orig"):
        return False
    if v and base == v and (c == v or c.startswith(v + "-")):
        return False
    return "-" in c


def _elegir_pista(info: dict, idiomas: tuple[str, ...] = ("es", "en")) -> dict | None:
    """Pick exactly one json3 caption track.

    Priority: manual captions in requested/video language, then original automatic
    captions. Auto-translations are intentionally rejected to avoid multi-track
    requests and lower-quality translated text.
    """
    video_lang = info.get("language") or ""

    manual: list[tuple[int, str, str]] = []
    for code, entries in (info.get("subtitles") or {}).items():
        url = _json3_url(entries)
        if url and (_matches_requested(code, idiomas) or _idioma_base(code) == _idioma_base(video_lang)):
            score = 0 if _idioma_base(code) == _idioma_base(video_lang) else 1
            manual.append((score, code, url))
    if manual:
        _, code, url = sorted(manual, key=lambda x: x[0])[0]
        return {"url": url, "idioma": code, "tipo": "manual"}

    auto: list[tuple[int, str, str]] = []
    for code, entries in (info.get("automatic_captions") or {}).items():
        url = _json3_url(entries)
        if not url or _is_auto_translation(code, video_lang):
            continue
        if not (_matches_requested(code, idiomas) or _idioma_base(code) == _idioma_base(video_lang)):
            continue
        score = 0 if code.lower().endswith("-orig") else 1
        auto.append((score, code, url))
    if auto:
        _, code, url = sorted(auto, key=lambda x: x[0])[0]
        return {"url": url, "idioma": code, "tipo": "automática"}
    return None


def _ydl_opts(skip_download: bool = True) -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": skip_download,
        "noplaylist": True,
        "extract_flat": False,
    }


def _info_sync(video_id: str) -> dict:
    if yt_dlp is None:
        raise RuntimeError("yt-dlp no está disponible")
    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:  # type: ignore[attr-defined]
        return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)


async def _descargar(url: str):
    r = await net.client().get(url, timeout=12)
    r.raise_for_status()
    return r.text


def _buscar_sync(q: str, n: int) -> list[dict]:
    if yt_dlp is None:
        raise RuntimeError("yt-dlp no está disponible")
    with yt_dlp.YoutubeDL({**_ydl_opts(), "extract_flat": "in_playlist"}) as ydl:  # type: ignore[attr-defined]
        info = ydl.extract_info(f"ytsearch{max(n * 2, n)}:{q}", download=False)
    out: list[dict] = []
    for e in (info or {}).get("entries", []) or []:
        vid = e.get("id") or id_de_url(e.get("url"))
        if not vid:
            continue
        out.append({
            "id": vid,
            "title": e.get("title") or "",
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration": int(e.get("duration") or 0),
        })
        if len(out) >= n * 2:
            break
    return out


def _looks_limited(exc: Exception | str) -> bool:
    s = str(exc).lower()
    return "429" in s or "too many requests" in s or "rate" in s


def _looks_unavailable(exc: Exception | str) -> bool:
    s = str(exc).lower()
    return any(x in s for x in ("unavailable", "private", "removed", "not available", "video unavailable"))


def _set_limited() -> None:
    global _LIMIT_UNTIL
    _LIMIT_UNTIL = time.time() + _LIMIT_COOLDOWN


def _limited_now() -> bool:
    return time.time() < _LIMIT_UNTIL


def _cache_get_video(video_id: str):
    e = _cache().get("v::" + video_id)
    if not e:
        return None
    ttl = _TRANSCRIPT_TTL if e.get("data", {}).get("ok") else _NEGATIVE_TTL
    if time.time() - e.get("ts", 0) < ttl:
        return e.get("data")
    return None


def _cache_put_video(video_id: str, data: dict) -> None:
    d = _cache()
    d["v::" + video_id] = {"ts": time.time(), "data": data}
    _save_disk_cache(d)


async def transcripcion(video: str, idiomas: tuple[str, ...] = ("es", "en")) -> dict:
    video_id = id_de_url(video)
    if not video_id:
        return {"ok": False, "motivo": "no_disponible"}
    if _limited_now():
        return {"ok": False, "id": video_id, "motivo": "limite"}

    cached = _cache_get_video(video_id)
    if cached is not None:
        return cached

    try:
        info = await asyncio.to_thread(_info_sync, video_id)
    except Exception as e:
        if _looks_limited(e):
            _set_limited()
            return {"ok": False, "id": video_id, "motivo": "limite"}
        motivo = "no_disponible" if _looks_unavailable(e) else "error"
        return {"ok": False, "id": video_id, "motivo": motivo}

    title = info.get("title") or ""
    pista = _elegir_pista(info, idiomas)
    if not pista:
        data = {"ok": False, "id": video_id, "title": title, "motivo": "sin_subtitulos"}
        _cache_put_video(video_id, data)
        return data

    try:
        raw = await _descargar(pista["url"])
        lineas = _parse_json3(raw)
    except Exception as e:
        if isinstance(e, Limite) or _looks_limited(e):
            _set_limited()
            return {"ok": False, "id": video_id, "title": title, "motivo": "limite"}
        return {"ok": False, "id": video_id, "title": title, "motivo": "error"}

    if not lineas:
        data = {"ok": False, "id": video_id, "title": title, "motivo": "sin_subtitulos"}
        _cache_put_video(video_id, data)
        return data

    data = {
        "ok": True,
        "id": video_id,
        "title": title,
        "canal": info.get("channel") or info.get("uploader") or "",
        "idioma": pista["idioma"],
        "tipo": pista["tipo"],
        "lineas": lineas,
        "texto": "\n".join(txt for _, txt in lineas),
    }
    _cache_put_video(video_id, data)
    return data


def _terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[\wáéíóúüñ]{3,}", (query or "").lower())]


def _format_window(lineas: list[tuple[float, str]], start: int, max_chars: int) -> str:
    chunks: list[str] = []
    total = 0
    for sec, txt in lineas[start:]:
        m = int(sec // 60)
        s = int(sec % 60)
        piece = f"[{m:02d}:{s:02d}] {txt}"
        if chunks and total + len(piece) + 1 > max_chars:
            break
        chunks.append(piece)
        total += len(piece) + 1
    return "\n".join(chunks)


def ventanas_relevantes(lineas: list[tuple[float, str]], query: str, max_chars: int = 1800) -> tuple[str, float]:
    if not lineas:
        return "", 0.0
    terms = _terms(query)
    best = 0
    if terms:
        scores: list[_ScoreLine] = []
        for i, (_, txt) in enumerate(lineas):
            low = txt.lower()
            score = sum(1 for t in terms if t in low)
            if score:
                scores.append(_ScoreLine(score, i))
        if scores:
            best = max(scores, key=lambda s: (s.score, -s.index)).index
            best = max(0, best - 5)
    texto = _format_window(lineas, best, max_chars)
    if not texto and best != 0:
        texto = _format_window(lineas, 0, max_chars)
        best = 0
    return texto, float(lineas[best][0] if lineas else 0.0)


async def buscar_videos(query: str, n: int = 5) -> list[dict]:
    try:
        raw = await asyncio.to_thread(_buscar_sync, query, max(n, 1))
    except Exception:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for v in raw or []:
        vid = v.get("id") or id_de_url(v.get("url"))
        if not vid or vid in seen:
            continue
        dur = int(v.get("duration") or 0)
        if dur > _MAX_VIDEO_SECONDS:
            continue
        seen.add(vid)
        out.append({
            "id": vid,
            "title": v.get("title") or "",
            "channel": v.get("channel") or v.get("uploader") or "",
            "duration": dur,
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
        if len(out) >= n:
            break
    return out


def _motivo_humano(r: dict) -> str:
    m = r.get("motivo")
    if m == "sin_subtitulos":
        return "sin subtítulos"
    if m == "limite":
        return "límite temporal de YouTube"
    if m == "no_disponible":
        return "no disponible"
    return "error al leer la transcripción"


async def fuentes_video(query: str, n: int = 2, max_chars: int = 1200) -> tuple[list[dict], list[str]]:
    fuentes: list[dict] = []
    omitidos: list[str] = []
    candidatos = await buscar_videos(query, max(n * 3, n))
    for v in candidatos:
        if len(fuentes) >= n:
            break
        r = await transcripcion(v["id"])
        titulo = r.get("title") or v.get("title") or v["id"]
        if not r.get("ok"):
            omitidos.append(f"{titulo}: {_motivo_humano(r)}")
            if r.get("motivo") == "limite":
                break
            continue
        texto, inicio = ventanas_relevantes(r.get("lineas") or [], query, max_chars=max_chars)
        if not texto:
            omitidos.append(f"{titulo}: transcripción vacía")
            continue
        sec = int(inicio)
        fuentes.append({
            "kind": "youtube",
            "title": titulo,
            "url": f"https://www.youtube.com/watch?v={r['id']}&t={sec}s",
            "canal": r.get("canal") or v.get("channel") or "",
            "tipo": r.get("tipo") or "",
            "idioma": r.get("idioma") or "",
            "text": texto[:max_chars + 20],
        })
    return fuentes, omitidos
