"""Minion TELÉFONO — llamadas y agenda desde tu MÓVIL vinculado (estilo Android Auto).

«llama a 612 345 678», «llama a Rubén», «marca a mamá» → nexus manda la orden
al móvil vinculado por WebSocket (evento 'call') y la app abre la llamada:
  · con número → marca directamente (tel: o puente nativo del APK);
  · con nombre → PRIMERO lo busca en la AGENDA de nexus (data/contacts.json);
    si no está, lo busca en los contactos del móvil (necesita el APK con el
    puente de llamadas; si es viejo, la app avisa de actualizarlo).

La agenda de nexus hace que «llama a mamá» funcione con CUALQUIER APK o PWA:
  «apunta el teléfono de mamá 612 345 678» → guardado; a partir de ahí «llama
  a mamá» marca directo y «envía un whatsapp a mamá diciendo …» (skill n8n)
  puede abrir WhatsApp en el móvil con el chat y el texto listos.

La orden vale desde el PC o desde el propio móvil. El intent 'info' explica
cómo funciona y qué hace falta para activarlo (no marca nada).
"""
from __future__ import annotations

import json
import re
import unicodedata

SKILL = {
    "name": "Teléfono",
    "description": ("Llamadas reales desde tu móvil vinculado y agenda propia: "
                    "«llama a mamá» resuelve el número, «marca el 612 345 678» marca directo"),
    # Orden: info y agenda (específicos) antes que 'llamar' (la acción amplia).
    "patterns": {
        "info": r"(?:puedes|sabes|podr[ií]as)\s+(?:hacer\s+)?llamadas"
                r"|c[oó]mo\s+(?:funcionan?|activo|uso|configuro|hago)\s+(?:las?\s+llamadas?|una\s+llamada|el\s+tel[eé]fono)"
                r"|c[oó]mo\s+llamo\s+por\s+tel[eé]fono"
                r"|qu[eé]\s+necesito\s+para\s+(?:llamar|hacer\s+llamadas)",
        "save_contact": r"(?:ap[uú]nta(?:me)?|guarda(?:me)?|gu[aá]rdame|a[ñn][aá]de(?:me)?|registra(?:me)?)\s+"
                        r"(?:el\s+|la\s+|un\s+)?(?:tel[eé]fono|n[uú]mero|m[oó]vil|contacto)\s+de[l]?\s+"
                        r"(?P<name>[^:,\n]{2,40}?)\s*(?:[:,]|\bes\b)?\s*(?P<num>\+?\d[\d .\-]{6,20})\s*$"
                        r"|(?:el\s+)?(?:tel[eé]fono|n[uú]mero|m[oó]vil)\s+de[l]?\s+"
                        r"(?P<name2>[^:,\n]{2,40}?)\s+es\s+(?P<num2>\+?\d[\d .\-]{6,20})\s*$",
        "del_contact": r"(?:borra|elimina|quita)(?:me)?\s+(?:el\s+)?(?:tel[eé]fono|contacto|n[uú]mero)\s+de[l]?\s+(?P<name>.+)",
        "list_contacts": r"(?:qu[eé]|cu[aá]les|cu[aá]ntos)\s+(?:tel[eé]fonos|contactos)\b"
                         r"|(?:ver|mu[eé]strame|ens[eé][ñn]a(?:me)?|lista(?:me)?|dime|dame)\s+(?:mis\s+|los\s+)?contactos\b"
                         r"|\bmis\s+contactos\b|agenda\s+de\s+(?:tel[eé]fonos|contactos)",
        "llamar": r"(?:ll[aá]ma(?:me|le)?(?:\s+por\s+tel[eé]fono)?|m[aá]rca(?:me|le)?|marca|telefonea"
                  r"|haz(?:le|me)?\s+una\s+llamada|ponle\s+una\s+llamada)\s+(?:al?|el)\s+"
                  r"(?P<who>[^.,;\n]{2,60})",
    },
}

_INFO = (
    "📞 Puedo llamar por ti usando tu móvil vinculado, estilo Android Auto:\n"
    "  • «llama a 612 345 678» → marca ese número directamente.\n"
    "  • «llama a mamá» → busco el número en MI agenda; si no lo tengo, en los "
    "contactos del móvil (APK reciente).\n"
    "  • «apunta el teléfono de mamá 612 345 678» → lo guardo en mi agenda y a "
    "partir de ahí también sirve para «envía un whatsapp a mamá diciendo …».\n"
    "Para que funcione: la app de nexus en el móvil con ✔ VINCULADO. La orden vale "
    "desde el PC o desde el propio móvil (yo mando el evento; quien marca es tu "
    "teléfono, con tu SIM)."
)


# ─────────────────────────── agenda (data/contacts.json) ───────────────────────────

def _contacts_file():
    from backend.core.config import DATA_DIR
    return DATA_DIR / "contacts.json"


def _canon(s: str) -> str:
    """minúsculas y sin acentos → 'Mamá' == 'mama'."""
    s = unicodedata.normalize("NFD", (s or "").strip().lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def load_contacts() -> dict:
    try:
        data = json.loads(_contacts_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_contacts(d: dict) -> None:
    f = _contacts_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def normalize_number(raw: str, cc: str = "+34") -> str:
    """Deja el número listo para tel:/wa.me: +CC y solo dígitos.
    «612 34 56 78» → «+34612345678»; si ya trae prefijo (+ o 00) se respeta."""
    n = re.sub(r"[^\d+]", "", raw or "")
    if n.startswith("00"):
        n = "+" + n[2:]
    if not n.startswith("+") and len(re.sub(r"\D", "", n)) == 9:
        n = cc + n
    return n


def resolve_contact(who: str) -> tuple[str, str]:
    """(nombre_guardado, número) para 'who' según la agenda; ('','') si no está."""
    agenda = load_contacts()
    q = _canon(who)
    if not q:
        return "", ""
    for name, num in agenda.items():
        if _canon(name) == q:
            return name, num
    for name, num in agenda.items():
        cn = _canon(name)
        if q in cn or cn in q:
            return name, num
    return "", ""


# ─────────────────────────────────── handler ───────────────────────────────────

async def handle(intent: str, text: str, match, ctx) -> dict:
    from backend.core import remote
    from backend.core.events import bus

    if intent == "info":
        return {"reply": _INFO}

    if intent == "save_contact":
        gd = match.groupdict()
        name = (gd.get("name") or gd.get("name2") or "").strip(" .")
        cc = ctx["settings"].get("phone_cc", "+34") if ctx.get("settings") else "+34"
        num = normalize_number(gd.get("num") or gd.get("num2") or "", cc)
        if not name or len(re.sub(r"\D", "", num)) < 7:
            return {"reply": "📇 No me cuadra. Formato: «apunta el teléfono de mamá 612 345 678»."}
        agenda = load_contacts()
        agenda[name] = num
        _save_contacts(agenda)
        return {"reply": f"📇 Guardado: {name} → {num}. Ya puedes decir «llama a {name}» "
                         f"o «envía un whatsapp a {name} diciendo …»."}

    if intent == "del_contact":
        name = (match.group("name") or "").strip(" .?!")
        agenda = load_contacts()
        real, _num = resolve_contact(name)
        if not real:
            return {"reply": f"📇 No tengo a «{name}» en la agenda. Di «mis contactos» y te la enseño."}
        agenda.pop(real, None)
        _save_contacts(agenda)
        return {"reply": f"📇 Contacto «{real}» borrado de mi agenda."}

    if intent == "list_contacts":
        agenda = load_contacts()
        if not agenda:
            return {"reply": "📇 Agenda vacía. Estrénala: «apunta el teléfono de mamá 612 345 678»."}
        lines = [f"  • {n} → {v}" for n, v in sorted(agenda.items())]
        return {"reply": f"📇 Mi agenda ({len(agenda)}):\n" + "\n".join(lines) +
                         "\nDi «llama a <nombre>» o «envía un whatsapp a <nombre> diciendo …»."}

    # ---- llamar ----
    who = (match.group("who") or "").strip().rstrip("?!.")
    if not who:
        return {"reply": "📞 ¿A quién llamo? Di «llama a <nombre o número>» y lo marco "
                         "en tu móvil vinculado."}
    cc = ctx["settings"].get("phone_cc", "+34") if ctx.get("settings") else "+34"
    digits = normalize_number(who, cc)
    is_num = len(re.sub(r"\D", "", digits)) >= 7
    name, number = ("", digits) if is_num else resolve_contact(who)
    if not remote.devices():
        return {"reply": "⚠ No tengo ningún móvil vinculado ahora mismo, y las llamadas "
                         "salen por tu teléfono (yo no tengo SIM). Para arreglarlo: abre la app "
                         "de nexus en el móvil, comprueba que pone ✔ VINCULADO y repíteme "
                         f"«llama a {who}». Si no tienes la app, instala el APK desde el HUD."}
    await bus.emit("call", {"to": who,
                            "number": number if (is_num or number) else "",
                            "name": "" if is_num else who})
    if is_num:
        how = "marcando el número directamente"
    elif number:
        how = f"con el {number} de mi agenda"
    else:
        how = ("buscándolo en los contactos del móvil (no lo tengo en mi agenda: "
               f"di «apunta el teléfono de {who} <número>» y la próxima marco directo)")
    return {"reply": f"📞 Marcando a {who} en tu móvil, {how}. Si la llamada no arranca, "
                     "el APK es viejo: actualízalo (necesita el puente de llamadas)."}
