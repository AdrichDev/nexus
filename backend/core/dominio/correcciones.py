# -*- coding: utf-8 -*-
"""Wrong-answer feedback: re-research, contrast, and confirmed corrections.

When the operator says an answer was wrong, that complaint is NOT a fact and is
NOT a global rule. Nexus itself searches NEW sources (never the ones it already
used for this question), contrasts its previous answer against them and reports
one of three outcomes: the sources confirm it, the sources correct it, or the
evidence is insufficient. A model verdict only counts when it quotes literal
text from a cited source; otherwise it is treated as insufficient, so a
hallucinated contrast cannot pass as verified.

A correction is stored as a fact (read back by the RAG knowledge/fact
retrieval) only after the operator explicitly confirms it. Confirmation records
the operator's acceptance plus the sources; it does not prove they are true.
Repeating the complaint searches further, different sources.

Pure logic: search, fetch, model and storage are injected (offline-testable).
State is per channel and in memory with a TTL; nothing persists until confirmed.
"""
from __future__ import annotations

import json
import re
import time
from itertools import zip_longest
from datetime import datetime, timezone
from urllib.parse import urlparse

_TTL = 30 * 60          # seconds a pending item or proposal stays alive
_MAX_FUENTES = 3        # new sources read per contrast
_TEXTO_FUENTE = 2500    # characters of each source given to the model
_MAX_LECTURAS = 8       # page fetches per contrast (unreadable links cost time)

_QUEJA_RX = re.compile(
    r"^\s*(?:(?:esa|tu|la)\s+respuesta\s+(?:no\s+es\s+correcta|es\s+incorrecta|est[aá]\s+mal)"
    r"|eso\s+(?:no\s+es\s+(?:correcto|cierto|verdad)|est[aá]\s+mal|es\s+(?:falso|incorrecto))"
    r"|no\s+es\s+(?:correcto|cierto)|est[aá]s?\s+equivocad[oa]|te\s+equivocas"
    r"|(?:la\s+)?respuesta\s+(?:es\s+)?incorrecta)\s*[.!¡]*\s*$",
    re.IGNORECASE)

_CORRECCION_RX = re.compile(
    r"^\s*(?:lo\s+correcto\s+es|la\s+respuesta\s+correcta\s+es|en\s+realidad)\s*[:,]?\s+"
    r"(?P<c>.+?)\s*[.!]*\s*$",
    re.IGNORECASE)

_SI_RX = re.compile(r"^\s*(?:s[ií]|confirmo|conf[ií]rmalo|gu[aá]rdal[ao]|vale|correcto)"
                    r"(?:\s*,?\s*(?:gu[aá]rdal[ao]|confirmo|por\s+favor))?\s*[.!]*\s*$",
                    re.IGNORECASE)
_NO_RX = re.compile(r"^\s*(?:no|desc[aá]rtal[ao]|no\s+la\s+guardes|cancela)\s*[.!]*\s*$",
                    re.IGNORECASE)

# Query variants per attempt: each new complaint widens the search.
_VARIANTES = ("", " fuente oficial", " datos verificados", " noticia")

_SISTEMA = (
    "Eres un verificador de hechos. Recibes una PREGUNTA, la RESPUESTA ANTERIOR del "
    "asistente y unas FUENTES numeradas. Usa SOLO las fuentes, nunca tu memoria. "
    "Decide si las fuentes confirman la respuesta anterior, la corrigen, o no bastan. "
    "Responde SOLO un objeto JSON, sin texto alrededor: "
    '{"veredicto": "confirma" | "corrige" | "insuficiente", '
    '"respuesta": "respuesta correcta según las fuentes, breve", '
    '"fuentes": [números de las fuentes que lo respaldan], '
    '"cita": "frase copiada LITERALMENTE de una de esas fuentes que lo demuestra"}')

_estado: dict[str, dict] = {}


def reset() -> None:
    _estado.clear()


def estado(channel: str) -> dict | None:
    st = _estado.get(channel)
    if st and time.time() - st["ts"] > _TTL:
        _estado.pop(channel, None)
        return None
    return st


def diagnostico(channel: str) -> dict | None:
    """Sources read and verdict of the last contrast (for the operator's log)."""
    st = _estado.get(channel)
    return st.get("_diag") if st else None


def es_queja_respuesta(text: str) -> bool:
    return bool(_QUEJA_RX.match(text or ""))


def extraer_correccion(text: str) -> str | None:
    m = _CORRECCION_RX.match(text or "")
    return m.group("c").strip() if m else None


def _rechazada_basica(url: str = "", text: str = "") -> bool:
    """Minimal fallback; the caller injects websearch's full consent filter."""
    host = urlparse(url or "").netloc.lower()
    low = (text or "").lower()
    return (host.startswith("consent.") or "antes de ir a google" in low
            or "before you continue to google" in low)


def _norm(s: str) -> str:
    """Compare quotes on words, not on typography: extracted HTML often has a
    space before punctuation or different quote marks. Content must still match."""
    s = re.sub(r"[\u00ab\u00bb\u201c\u201d\u201e\"\u2018\u2019']", "", s or "")
    s = re.sub(r"\s+([,.;:!?\)])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip(" .").lower()


def _ultimo_par(history: list[dict]) -> tuple[str, str] | None:
    """Last (user question, assistant answer) pair, skipping feedback turns."""
    for i in range(len(history) - 1, 0, -1):
        a, u = history[i], history[i - 1]
        if a.get("role") == "assistant" and u.get("role") == "user":
            q = (u.get("content") or "").strip()
            if q and not es_queja_respuesta(q) and not extraer_correccion(q):
                return q, (a.get("content") or "").strip()
    return None


def _afirmacion(respuesta: str) -> str:
    """The disputed claim: first sentence of the previous answer, no URLs."""
    # Job/Hermes results start with header paragraphs ("\u2714 Trabajo #N terminado
    # (...):", "Ya lo tengo #N \u2014 \u00ab...\u00bb:"); the claim is the first real paragraph.
    partes = [p for p in re.split(r"\n\s*\n", respuesta or "") if p.strip()]
    while len(partes) > 1 and (partes[0].rstrip().endswith(":")
                               or partes[0].lstrip().startswith(("\u2714", "\U0001fab6"))):
        partes.pop(0)
    limpio = re.sub(r"https?://\S+|\s*\u2014\s*\w+\s*$", "", "\n\n".join(partes))
    limpio = re.sub(r"[*_`#>]+", "", limpio).strip()      # markdown is not part of the claim
    frase = re.split(r"[.;:!?](?:\s|$)", limpio, maxsplit=1)[0]
    return " ".join(frase.split()[:14]).strip(" .,")   # short: search engines choke on long claims


def _urls_en(texto: str) -> set[str]:
    return set(re.findall(r"https?://[^\s)»\]>\"']+", texto or ""))


async def _fuentes_nuevas(st: dict, consulta: str, search, fetch, rechazada) -> list[dict]:
    """Up to _MAX_FUENTES usable sources never used before for this question.
    Readable pages win; snippet-only results are a last resort."""
    nuevas: list[dict] = []
    solo_snippet: list[dict] = []
    st["_lecturas"] = 0
    intento = st["intentos"]
    st["intentos"] += 1
    afirmacion = _afirmacion(st["respuesta"])
    for k in range(len(_VARIANTES)):
        variante = _VARIANTES[(intento + k) % len(_VARIANTES)]
        listas = []
        # Search both the question and the disputed claim itself, interleaved.
        for q in dict.fromkeys(x for x in (consulta, afirmacion) if x):
            try:
                listas.append(list(await search(f"{q}{variante}".strip(), 8) or []))
            except Exception:
                listas.append([])
        resultados = [r for fila in zip_longest(*listas) for r in fila if r] if listas else []
        for r in resultados:
            url = (r.get("url") or "").strip()
            snip = (r.get("snippet") or "").strip()
            if not url.startswith("http") or url in st["vistas"]:
                continue
            if rechazada(url=url, text=snip):
                st["vistas"].add(url)
                continue
            texto = ""
            if fetch is not None and st.get("_lecturas", 0) < _MAX_LECTURAS:
                st["_lecturas"] = st.get("_lecturas", 0) + 1
                try:
                    texto = (await fetch(url)) or ""
                except Exception:
                    texto = ""
            if texto and rechazada(url=url, text=texto):
                st["vistas"].add(url)
                continue
            st["vistas"].add(url)
            if texto:
                nuevas.append({"url": url, "texto": texto[:_TEXTO_FUENTE]})
            elif snip:
                solo_snippet.append({"url": url, "texto": snip[:_TEXTO_FUENTE]})
            if len(nuevas) >= _MAX_FUENTES:
                return nuevas
        if nuevas or solo_snippet:
            break
    return (nuevas + solo_snippet)[:_MAX_FUENTES]


def _veredicto(raw: str, fuentes: list[dict]) -> dict:
    """Parse and validate the model verdict; anything unproven is insufficient."""
    malo = {"veredicto": "insuficiente"}
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not m:
        return malo
    try:
        v = json.loads(m.group(0))
    except Exception:
        return malo
    ver = str(v.get("veredicto", "")).strip().lower()
    resp = str(v.get("respuesta", "")).strip()
    cita = str(v.get("cita", "")).strip()
    try:
        idx = [int(i) for i in v.get("fuentes", [])]
    except Exception:
        return malo
    if ver not in ("confirma", "corrige") or not resp or len(_norm(cita)) < 12:
        return malo
    citadas = [fuentes[i - 1] for i in idx if 1 <= i <= len(fuentes)]
    if not citadas or not any(_norm(cita) in _norm(f["texto"]) for f in citadas):
        return malo                      # quote not found literally: not evidence
    return {"veredicto": ver, "respuesta": resp, "cita": cita,
            "urls": [f["url"] for f in citadas]}


async def _contrastar(st: dict, search, fetch, ask, rechazada) -> str:
    consulta = st["pregunta"] if not st.get("propuesta_usuario") else \
        f"{st['propuesta_usuario']} {st['pregunta']}"
    fuentes = await _fuentes_nuevas(st, consulta, search, fetch, rechazada)
    previa = f"Sigue sin resolver (me lo has indicado {st['veces']} veces). " \
        if st["veces"] > 1 else ""
    if not fuentes:
        return (f"{previa}He buscado fuentes nuevas sobre «{st['pregunta']}» y no he "
                "encontrado ninguna utilizable distinta de las ya revisadas. No doy mi "
                "respuesta anterior por buena.")
    bloque = "\n\n".join(f"[{i}] {f['url']}\n{f['texto']}" for i, f in enumerate(fuentes, 1))
    usuario = (f"PREGUNTA: {st['pregunta']}\n\nRESPUESTA ANTERIOR: {st['respuesta']}\n\n"
               + (f"EL USUARIO PROPONE: {st['propuesta_usuario']}\n\n"
                  if st.get("propuesta_usuario") else "")
               + f"FUENTES:\n{bloque}")
    try:
        raw = await ask(_SISTEMA, usuario)
    except Exception:
        raw = ""
    v = _veredicto(raw, fuentes)
    n = len(fuentes)
    st["_diag"] = {"fuentes": [f["url"] for f in fuentes], "veredicto": v["veredicto"],
                   "modelo": (raw or "")[:300]}
    if v["veredicto"] == "corrige":
        st.update(estado="propuesta", correccion=v["respuesta"], fuentes=v["urls"],
                  extracto=v["cita"], ts=time.time())
        return (f"{previa}He contrastado mi respuesta con {n} fuentes nuevas y no era "
                f"correcta. Según las fuentes: {v['respuesta']}\n"
                f"Fuentes: {', '.join(v['urls'])}\nCita: «{v['cita']}»\n"
                "¿Quieres que guarde esta corrección? (sí / no)")
    if v["veredicto"] == "confirma":
        st.update(estado="pendiente", ts=time.time())
        return (f"{previa}He contrastado mi respuesta con {n} fuentes nuevas y la "
                f"respaldan: {v['respuesta']}\nFuentes: {', '.join(v['urls'])}\n"
                f"Cita: «{v['cita']}»\nSi sigues viendo un error, dímelo de nuevo y "
                "buscaré en otras fuentes distintas.")
    st.update(estado="pendiente", ts=time.time())
    return (f"{previa}He revisado {n} fuentes nuevas sobre «{st['pregunta']}» y no "
            "bastan para confirmar ni corregir mi respuesta, así que no la doy por "
            "buena. Si me lo vuelves a indicar, buscaré en otras fuentes.")


async def handle(text: str, channel: str, history: list[dict], *, search, store,
                 ask, fetch=None, rechazada=_rechazada_basica) -> str | None:
    """Return a reply when this message belongs to the correction flow, else None."""
    st = estado(channel)
    if st and st["estado"] == "propuesta":
        if _SI_RX.match(text):
            meta = {"confirmado_por": "usuario", "fuente": st["fuentes"][0],
                    "fuentes": " ".join(st["fuentes"]), "extracto": st["extracto"],
                    "pregunta": st["pregunta"], "respuesta_anterior": st["respuesta"],
                    "origen": "corrección contrastada",
                    "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "canal": channel}
            await store(f"Corrección confirmada para «{st['pregunta']}»: "
                        f"{st['correccion']} (fuentes: {' '.join(st['fuentes'])})",
                        kind="fact", meta=meta)
            _estado.pop(channel, None)
            return ("Guardada. Usaré esta corrección, con sus fuentes, cuando vuelva a "
                    "salir esa pregunta.")
        if _NO_RX.match(text):
            _estado.pop(channel, None)
            return "De acuerdo, descarto la propuesta y no guardo nada."
        st["estado"] = "pendiente"     # any other message drops the proposal

    deps = (search, fetch, ask, rechazada)
    # A bare "no" right after a contrast disputes it: search again instead of
    # letting the chat model give in without evidence. Only when the previous
    # assistant turn WAS that contrast, so other "no" answers are untouched.
    disputa = bool(st and _NO_RX.match(text) and history
                   and history[-1].get("role") == "assistant"
                   and history[-1].get("content") == st.get("_ultima"))
    if disputa or es_queja_respuesta(text):
        par = _ultimo_par(history)
        if st and (disputa or par is None or par[0] == st["pregunta"]):
            st["veces"] += 1
            st["ts"] = time.time()
            st["_ultima"] = await _contrastar(st, *deps)
            return st["_ultima"]
        # A newer question was answered since: review THAT answer, not the old one.
        if not par:
            return ("¿A qué respuesta te refieres? No tengo una respuesta anterior que "
                    "revisar.")
        st = {"estado": "pendiente", "pregunta": par[0], "respuesta": par[1],
              "veces": 1, "intentos": 0, "vistas": _urls_en(par[1]), "ts": time.time()}
        _estado[channel] = st
        st["_ultima"] = await _contrastar(st, *deps)
        return st["_ultima"]

    propuesta = extraer_correccion(text) if st else None
    if propuesta:
        st["propuesta_usuario"] = propuesta
        st["_ultima"] = await _contrastar(st, *deps)
        return st["_ultima"]
    return None
