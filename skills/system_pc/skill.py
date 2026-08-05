"""Minion Sistema/PC — control del equipo (con fallbacks simulados)."""
from __future__ import annotations

import datetime as dt
import os
import platform
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

# Import A NIVEL DE MÓDULO, y aquí está la razón: `_NO_ES_PROGRAMA` se concatena
# dentro de SKILL["patterns"], que se construye AL IMPORTAR este fichero. Un
# import dentro de una función —la forma habitual en las demás skills— llegaría
# tarde: el patrón «kill» ya se habría montado. La alternativa era compilar los
# patrones de «kill» perezosamente en el primer uso, y eso significa un nivel de
# indirección y una caché para ahorrar una línea.
#
# No estrena nada en el proyecto: `chrome`, `files` y `tasks_board` ya importan
# `backend.core` a nivel de módulo. Y no cierra ningún ciclo: `reglas` solo
# importa `comun/config` y `comun/audit`, nunca skills ni `skills_loader`.
from backend.core.dominio import reglas as _reglas

try:
    import psutil
except ImportError:
    psutil = None

SHOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "captures"

# Nombre coloquial → nombre real del ejecutable, para que «cierra el navegador»
# encuentre chrome.exe y «cierra la calculadora» encuentre calc.exe.
_ALIAS_PROCESO = {
    "navegador": "chrome", "explorador": "explorer", "terminal": "cmd",
    "consola": "cmd", "calculadora": "calc", "notas": "notepad",
    "bloc de notas": "notepad", "musica": "spotify", "música": "spotify",
}

# Confirmaciones de cierre. Todas nombran el programa y ninguna añade PIDs ni
# recuentos: quien da la orden solo necesita saber que ya está hecho.
_CERRADO_FRASES = (
    "{prog} cerrado",
    "Listo, {prog} fuera",
    "{prog} ya no está en marcha",
    "Hecho: {prog} cerrado",
    "Adiós a {prog}",
    "{prog} apagado",
)

# Lo que NO es un programa que se pueda cerrar. Va como lookahead negativo en el
# patrón «kill» para que «cierra X» a secas siga siendo una orden de PC sin
# robarle la frase a las skills que van detrás por orden alfabético. La lista
# —con lo que protege cada bloque— ya no está aquí: sale de `reglas.valor()`,
# que resuelve reserva del código → `config/umbrales.json` → superposición
# aprendida. Se lee al importar porque el patrón «kill» se monta al importar.
_NO_ES_PROGRAMA = _reglas.valor("system_pc.no_es_programa")

# Palabras con las que se nombra a ESTE equipo cuando se pide volumen.
_ESTE_PC = r"(?:pc|ordenador|ordenata|equipo|sistema|windows|m[aá]quina|torre|sobremesa|port[aá]til)"

# Artículo o determinante delante del destino. Se CONSUME antes del lookahead
# de exclusión para que este vea el sustantivo, no el «los».
_ART = r"(?:el\s+|la\s+|los\s+|las\s+|un\s+|una\s+|mi\s+|mis\s+|este\s+|esta\s+)?"

# Lo que NO es una aplicación con sonido propio. Va como lookahead negativo en
# las formas cortas («silencia X», «el volumen de X») para que no se traguen ni
# la orden sin destino ni lo que es de otras skills. Cada bloque dice de quién
# es lo que protege.
_NO_ES_APP_SONIDO = (
    r"(?!(?:"
    r"tele|televisi[oó]n|televisor(?:es)?|smart|tv|"                 # domotica
    r"casa|sal[oó]n|comedor|cocina|habitaci[oó]n|dormitorio|"        # domotica
    r"recordatorios?|notificaciones?|avisos?|alarmas?|"              # tasks_board / tools
    r"tareas?|m[oó]vil|tel[eé]fono|chats?|mensajes?|"                # tasks_board / telefono / comms
    r"sonido|audio|volumen|silencio|ruido|todo|esto|eso|"            # la orden sin destino
    r"el|la|los|las|un|una|unos|unas|mi|mis|este|esta|"              # determinantes sueltos
    r"poco|mucho|algo"                                               # cuantificadores
    r")\b)"
)

# Las formas de QUITAR el silencio, en un solo sitio. Se escribían sueltas en
# cada patrón y por eso «quítale el silencio» a secas no llegaba a ninguna skill:
# caía al planificador, que además contestaba que lo había hecho.
_QUITAR_SILENCIO = (
    r"(?:qu[ií]ta(?:me|le|te)?\s+el\s+(?:silencio|mute)"
    r"|desil[eé]ncia(?:me|le|lo|la)?|desmutea(?:me|le|lo|la)?"
    r"|activa(?:me)?\s+el\s+sonido|devu[eé]lve(?:le|me)?\s+el\s+sonido"
    r"|(?:que\s+)?vu[eé]lva?\w*\s+a\s+sonar)"
)

SKILL = {
    "name": "Sistema / PC",
    "description": ("Control real del PC: CPU/RAM/GPU con temperaturas, procesos, abrir apps "
                    "y webs, capturas, webcam, Wake-on-LAN y apagado con doble confirmación"),
    "patterns": {
        # Volumen MAESTRO del PC. Exige que la orden nombre el equipo («del pc»,
        # «del ordenador», «del sistema»): el destino lo dice siempre quien da la
        # orden. Va el primero de los tres de volumen para que «del pc» no lo
        # capture `volume_app` como si «pc» fuera un programa.
        "volume": r"\bvolumen\b[^.\n]{0,12}\b(?:de(?:l)?\s+|en\s+)(?:la\s+|el\s+|mi\s+|este\s+)?"
                  + _ESTE_PC + r"\b"
                  r"|\b(?:s[uú]be|b[aá]ja|p[oó]n)(?:me|le)?\b[^.\n]{0,15}\b(?:de(?:l)?\s+)"
                  + _ESTE_PC + r"\b[^.\n]{0,15}\bvolumen\b"
                  r"|\b(?:sil[eé]ncia|mut[eé]a)(?:me|le)?(?:lo|la)?\s+(?:el\s+|la\s+|mi\s+|este\s+)?"
                  + _ESTE_PC + r"\b"
                  r"|\bqu[ií]ta(?:me|le)?\s+el\s+(?:sonido|audio|volumen)\s+"
                  r"(?:de(?:l)?|a(?:l)?)\s+(?:la\s+|el\s+|mi\s+)?" + _ESTE_PC + r"\b"
                  r"|\b" + _QUITAR_SILENCIO + r"\s+(?:de(?:l)?\s+|a(?:l)?\s+)?"
                  r"(?:la\s+|el\s+|mi\s+|este\s+)?" + _ESTE_PC + r"\b",
        # Volumen de UNA APLICACIÓN concreta, por su sesión de audio de Windows.
        # El nombre se captura tal cual lo dice el operador («spotify») y el
        # handler lo empareja con el proceso real («Spotify.exe»).
        "volume_app": r"\bvolumen\b[^.\n]{0,12}\b(?:de(?:l)?\s+|en\s+)" + _ART
                      + _NO_ES_APP_SONIDO + r"(?P<app>[\w.\-]{2,})"
                      r"|\bqu[ií]ta(?:me|le)?\s+el\s+(?:sonido|audio|volumen)\s+(?:de(?:l)?|a(?:l)?)\s+"
                      + _ART + _NO_ES_APP_SONIDO + r"(?P<app2>[\w.\-]{2,})"
                      r"|\b(?:sil[eé]ncia|mut[eé]a)(?:me|le)?\s+" + _ART
                      + _NO_ES_APP_SONIDO + r"(?P<app3>[\w.\-]{2,})"
                      r"|\b" + _QUITAR_SILENCIO + r"\s+(?:de(?:l)?\s+|a(?:l)?\s+)?"
                      + _ART + _NO_ES_APP_SONIDO + r"(?P<app4>[\w.\-]{2,})",
        # Volumen SIN destino. No se adivina: se pregunta. Va detrás de los dos
        # anteriores, que ya se han quedado las órdenes que sí nombran destino.
        "volume_ask": r"\b(?:s[uú]be|b[aá]ja|p[oó]n|qu[ií]ta)(?:me|le)?\b[^.\n]{0,25}\bvolumen\b"
                      r"|\bvolumen\s+(?:al?\s*)?\d{1,3}\s*%?"
                      r"|\b(?:m[aá]s|menos)\s+volumen\b"
                      r"|^\s*(?:sil[eé]ncia(?:lo|la|me)?|mut[eé]a(?:lo|la)?|silencio)\s*[.!]*$"
                      r"|^\s*qu[ií]ta(?:me)?\s+el\s+(?:sonido|audio|volumen)\s*[.!]*$"
                      # Quitar el silencio SIN destino. Sin esto se iba al
                      # planificador, que respondía «✔» sin haber tocado nada.
                      r"|^\s*" + _QUITAR_SILENCIO + r"\s*[.!]*$",
        # Brillo de la PANTALLA. El SKILL.md de `media` lleva tiempo mandando
        # «pon el brillo al 80» aquí, y aquí no había nada: la frase caía al
        # planificador. Exige «pantalla» o «monitor» cuando no lleva número,
        # para no robarle a domotica el brillo de una bombilla.
        "brightness": r"\bbrillo\s+(?:de\s+la\s+pantalla\s+|del?\s+monitor\s+)?"
                      r"(?:al?\s*)?(?P<bri>\d{1,3})\s*%?"
                      r"|\b(?:sube|baja|pon)(?:me|le)?\b[^.\n]{0,25}\bbrillo\b"
                      r"[^.\n]{0,20}\b(?:pantalla|monitor|pc|equipo|ordenador)\b"
                      r"|\b(?:sube|baja)(?:me|le)?\s+el\s+brillo\b\s*[.!?]*$",
        # Temperaturas de HARDWARE (cpu/gpu/gráfica…). OJO: exige un componente
        # detrás de "temperatura" para NO robar «¿qué temperatura hace en Madrid?»
        # (eso es clima y lo atiende la skill 'clima').
        "temps": r"temperatura[s]?\b.{0,25}\b(cpu|gpu|gr[aá]ficas?|tarjeta gr[aá]fica|procesador|n[uú]cleos?|componentes)\b|temperatura[s]?\s+(de\s+(la|el|los)\s+)?(cpu|gpu|gr[aá]ficas?|tarjeta|procesador|n[uú]cleos?|componentes|equipo|pc|ordenador|sistema)|(cpu|gpu|gr[aá]fica|procesador)\s+.{0,8}temperatura|qu[eé] temperatura (tiene|alcanza|marca|hay en)\s+(la|el|mi)?\s*(cpu|gpu|gr[aá]fica|procesador|pc|equipo)|c[oó]mo (est[aá]n?|van?)\s+(de\s+)?(las\s+|los\s+)?temperatura"
                 r"|(?:est[aá]|anda)\s+(?:muy\s+)?caliente\s+(?:la\s+|el\s+|mi\s+)?(cpu|gpu|gr[aá]fica|procesador|pc|equipo|ordenador|port[aá]til)"
                 r"|se\s+(?:me\s+)?(?:est[aá]\s+)?calentando\s+(?:la\s+|el\s+|mi\s+)?(cpu|gpu|gr[aá]fica|pc|equipo|ordenador|port[aá]til)"
                 r"|cu[aá]ntos?\s+grados\s+(?:tiene|marca|alcanza)\s+(?:la\s+|el\s+|mi\s+)?(cpu|gpu|gr[aá]fica|procesador|pc|equipo)",
        "hardware": r"estado del (sistema|equipo|pc)|c[oó]mo (?:va|anda) (la|el|mi) (cpu|ram|gpu|pc|equipo|ordenador)|informe de[l]? (sistema|equipo|hardware)|\bhardware\b|c[oó]mo (est[aá]|va|anda) (el|mi) (pc|equipo|ordenador|sistema)"
                    r"|diagn[oó]stico (?:r[aá]pido )?(?:del?|de mi) (pc|equipo|sistema|ordenador|hardware)"
                    r"|uso de (?:la\s+)?(cpu|ram|memoria|gpu|disco)"
                    r"|cu[aá]nta (ram|memoria) (?:libre\s+)?(hay|queda|tengo|me queda)",
        "processes": r"(?:l[ií]sta|ver|mu[eé]strame|ens[eé][ñn]ame|dime|dame|saca)(?:me)?\b[^.\n]{0,20}\bprocesos\b"
                     r"|procesos (?:activos|abiertos|en marcha|en ejecuci[oó]n)"
                     r"|qu[eé] procesos (?:hay|corren|est[aá]n|tengo)|top de procesos"
                     r"|qu[eé] [^.\n]{0,25}(?:consume|consumiendo|come|comiendo|gasta|gastando|"
                     r"chupa|chupando)[^.\n]{0,15}\b(?:ram|memoria|cpu)\b",
        # ¿QUIÉN ESCUCHA EN UN PUERTO? 05/08/2026: ninguna de las 32 skills sabía
        # mirar puertos. «qué programa está usando el puerto 5678» no casaba con
        # nada y caía al planificador, que rellenaba el hueco con lo que le
        # parecía: una vez delegó en Hermes y acertó, otra devolvió un ranking de
        # procesos por memoria, al instante y con total seguridad. Falso y no
        # determinista, que es la peor combinación.
        #
        # EXIGE LAS DOS COSAS, la palabra «puerto» y el NÚMERO. Sin el número no
        # es esta pregunta (es la lista, el intent de abajo), y sin la palabra
        # «puerto» un número suelto es de cualquiera. Va ANTES que `ports` porque
        # es el más específico de los dos, y ambos van muy por delante de
        # `open_web`/`open_app`, que se quedan casi cualquier frase.
        "port_who": r"\b(?:qu[eé]|qui[eé]n(?:es)?|cu[aá]l)\b[^.\n]{0,40}"
                    r"\bpuertos?\s+(?:n[uú]mero\s+)?(?P<port>\d{1,5})\b"
                    r"|\b(?:mira|comprueba|revisa|consulta|dime|dame|mu[eé]stra(?:me)?|"
                    r"ens[eé][ñn]a(?:me)?|ver)\b[^.\n]{0,30}"
                    r"\bpuertos?\s+(?:n[uú]mero\s+)?(?P<port2>\d{1,5})\b"
                    r"|\bpuertos?\s+(?P<port3>\d{1,5})\b[^.\n]{0,30}"
                    r"\b(?:qui[eé]n|ocupad[oa]s?|en\s+uso|libres?|escuchando|usa|usando)\b"
                    # A pelo, que es como se pregunta cuando ya se venía hablando
                    # del tema: «el puerto 5432». Anclada a la frase entera para
                    # que un número suelto en medio de otra orden no la dispare.
                    r"|^\s*(?:el\s+|en\s+el\s+)?puertos?\s+(?P<port4>\d{1,5})\s*[.!?¿¡]*$",
        # QUÉ PUERTOS HAY EN ESCUCHA. Siempre en PLURAL y siempre con la palabra
        # «puertos»: sin ella no hay forma de distinguir esto de nada.
        "ports": r"\b(?:qu[eé]|cu[aá]les)\b[^.\n]{0,25}\bpuertos\b"
                 r"|\bpuertos\s+(?:abiertos?|en\s+escucha|escuchando|en\s+uso|ocupados?)\b"
                 r"|\b(?:l[ií]sta|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|dime|dame|saca|ver)"
                 r"(?:me)?\b[^.\n]{0,20}\bpuertos\b",
        # Cerrar un programa. Las tres primeras formas llevan ancla explícita
        # («proceso», «la app/el programa», un «.exe»). La cuarta y la quinta son
        # las que se dicen de verdad —«mata chrome», «cierra spotify»— y por eso
        # no piden ancla: la acotación va por LISTA DE EXCLUSIÓN, con los
        # sustantivos que son de otras skills (la pestaña es de chrome, el tablero
        # de tasks_board, la persiana de domotica) o que no son un programa (la
        # sesión, la ventana). Sin esa lista, un «cierra X» genérico aquí se
        # tragaría medio proyecto, porque system_pc va antes que tasks_board,
        # telefono, tools y vigilancias por orden alfabético.
        "kill": r"\b(?:ci[eé]rra|m[aá]ta|termina|finaliza)(?:me|le)?\s+(?:el\s+)?procesos?\s+(?:de\s+)?(?P<proc>[\w.\-]+)"
                r"|\b(?:ci[eé]rra|m[aá]ta|termina|finaliza)(?:me|le)?\s+(?:la\s+(?:app|aplicaci[oó]n)|el\s+programa)\s+(?:de\s+)?(?P<proc2>[\w.\-]+)"
                r"|\b(?:ci[eé]rra|m[aá]ta|termina|finaliza)(?:me|le)?\s+(?P<proc3>[\w.\-]+\.exe)\b"
                r"|\bm[aá]ta(?:me)?\s+(?:a\s+|al\s+|el\s+)?" + _NO_ES_PROGRAMA +
                r"(?P<proc4>[\w.\-]{2,})"
                r"|\b(?:ci[eé]rra|termina|finaliza)(?:me|le)?\s+(?:el\s+|la\s+|los\s+|las\s+|mi\s+)?"
                + _NO_ES_PROGRAMA + r"(?P<proc5>[\w.\-]{2,})\s*$",
        "youtube": r"\b[aá]bre(?:me)?\b.*youtube(\s+y\s+(busca|pon)\s+(?P<yt>.+))?|\bpon(?:me)?\b.*en youtube\s+(?P<yt2>.+)",
        # «abre la web/página (de) X»: captura TODO el nombre del sitio, no solo la
        # primera palabra. ANTES capturaba \S+ y con «abre la web de youtube» la URL
        # era literalmente "de" → abría https://de (el famoso «de/»). El «de» ahora
        # se ignora y el handler resuelve alias conocidos, dominios o busca en Google.
        # Abrir CUALQUIER web, sin lista de sitios: el handler resuelve la URL
        # (dominio literal → caché aprendida → el modelo la deduce y la memoriza).
        # Tres formas: con la palabra «web/página», una URL o dominio a pelo, y
        # los verbos de navegar («entra en», «métete en», «llévame a»).
        # «llévame a» y «vete a» quedan fuera a propósito: son de mapas (places),
        # que además va antes por orden alfabético.
        "open_web": r"\b(?:[aá]bre(?:me)?|p[oó]n(?:me)?|saca(?:me)?|entra\s+en|m[eé]tete\s+en|"
                    r"visita)\b.*?\b(?:la\s+)?(?:web|p[aá]gina)(?:\s+web)?\s+"
                    r"(?:de\s+la\s+|de\s+los\s+|del\s+|de\s+|la\s+|el\s+)?(?P<url>.+)"
                    r"|\b(?:[aá]bre(?:me)?|entra\s+en|m[eé]tete\s+en|visita)\s+"
                    r"(?:la\s+)?(?P<url2>https?://\S+|(?:www\.)?[\w\-]+(?:\.[\w\-]+)*"
                    r"\.(?:com|es|org|net|io|dev|app|tv|me|info|eu|co|gov|edu)(?:/\S*)?)\b",
        "reindex": r"reindexa (las )?(aplicaciones|apps)|(?:actualiza|reconstruye) el [ií]ndice de (apps|aplicaciones)|reescanea (las )?(aplicaciones|apps)",
        "list_apps": r"qu[eé] (aplicaciones|apps|programas) (conoces|tienes|hay|tengo)( instalad[oa]s)?"
                     r"|(?:lista|mu[eé]strame|ens[eé][ñn]ame)\s+(?:de\s+|las?\s+|los\s+)?(?:aplicaciones|apps|programas)\s+instalad[oa]s",
        # Abrir apps instaladas. El lookahead NEGATIVO evita robar dominios ajenos:
        # el tablero/tareas (tasks_board), correos (google_workspace), pestañas o
        # «X en chrome» (navegador), hermes… Esos, si su skill no los caza, deben
        # llegar al planificador, no abrirse aquí como si fueran un .exe.
        "open_app": r"\b([aá]bre(?:me)?|ejecuta|lanza|arranca|inicia)\b\s+"
                    r"(?!(?:el\s+|la\s+|los\s+|las\s+|mis?\s+|una?\s+)?"
                    r"(?:tablero\b|tareas?\b|correos?\b|mails?\b|e-?mails?\b|"
                    r"pesta[ñn]as?\b|marcadores\b|historial\b|sesi[oó]n\b|hermes\b))"
                    r"(?!.*\ben\s+chrome\b)(?P<app>.+)",
        "screenshot": r"captura de (?:la\s+)?pantalla|haz(?:me)? una captura|s[aá]ca(?:me)? (?:una\s+)?captura|pantallazo|captura la pantalla|screenshot",
        "webcam": r"foto (?:con|desde) la (webcam|c[aá]mara)|haz(?:me)? una foto|s[aá]ca(?:me)? una foto|[eé]cha(?:me)? una foto",
        # SEGURIDAD: apagar y reiniciar SIEMPRE son dos pasos, armados en
        # backend.core.comun.confirm. Los *_confirm solo llegan aquí cuando NO hay nada
        # armado (si lo hay, el brain resuelve el sí/no antes que el router).
        "shutdown_confirm": r"confirmo apagado",
        "shutdown": r"\bap[aá]ga(?:me)?\s+(?:el\s+|la\s+|mi\s+)?(pc|ordenador|equipo|sistema|torre|m[aá]quina)\b",
        "restart_confirm": r"confirmo reinicio",
        "restart": r"\brein[ií]cia(?:me)?\s+(?:el\s+|la\s+|mi\s+)?(pc|ordenador|equipo|sistema|torre|m[aá]quina)\b",
        "wake": r"enciende (el )?(pc|ordenador|equipo)|arranca (el )?(pc|ordenador)|despierta (el )?(pc|ordenador|equipo)|wake on lan",
        "set_mac": r"(guarda|configura|apunta) la mac\s+(?P<mac>[0-9a-fA-F:.\-]{12,17})",
    },
}


def _send_magic_packet(mac: str, broadcast: str = "255.255.255.255") -> bool:
    """Envía un paquete mágico Wake-on-LAN a la MAC indicada."""
    import socket
    clean = mac.replace(":", "").replace("-", "").replace(".", "")
    if len(clean) != 12:
        return False
    data = bytes.fromhex("FF" * 6 + clean * 16)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(data, (broadcast, 9))
        s.close()
        return True
    except Exception:
        return False

def _steam_appid_by_name(name: str):
    """AppID de Steam por nombre (búsqueda en la tienda, sin API key). None si no
    hay una coincidencia razonable — así «abre battlefield» lanza el juego, pero
    «abre asdf» no dispara nada raro."""
    import json
    import urllib.parse
    import urllib.request
    url = ("https://store.steampowered.com/api/storesearch/?term="
           + urllib.parse.quote(name) + "&l=spanish&cc=ES")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as r:
            items = (json.loads(r.read().decode("utf-8", "ignore")).get("items") or [])
        low = name.lower()
        for it in items:
            nm = str(it.get("name", "")).lower()
            if low in nm or any(len(w) > 2 and w in nm for w in low.split()):
                return it.get("id")
    except Exception:
        return None
    return None


def _mezclador_maestro():
    """Control del volumen maestro de la salida de audio por pycaw, o None si
    pycaw/comtypes no están o Windows no expone el dispositivo."""
    try:
        from pycaw.utils import AudioUtilities
        return AudioUtilities.GetSpeakers().EndpointVolume
    except Exception:                                      # noqa: BLE001
        return None


def _sesiones_audio() -> list:
    """[(nombre_proceso, SimpleAudioVolume)] de cada aplicación con sesión de
    audio abierta. La sesión del sistema no trae proceso y se descarta."""
    try:
        from pycaw.utils import AudioUtilities
        salida = []
        for s in AudioUtilities.GetAllSessions():
            proc = getattr(s, "Process", None)
            vol = getattr(s, "SimpleAudioVolume", None)
            if proc is None or vol is None:
                continue
            try:
                nombre = proc.name() or ""
            except Exception:                              # noqa: BLE001
                continue
            if nombre:
                salida.append((nombre, vol))
        return salida
    except Exception:                                      # noqa: BLE001
        return []


def _porque_no_pycaw() -> str:
    """'' si pycaw sirve aquí; si no, el motivo EXACTO, tal cual lo da Windows.

    No basta con que importe: hay que poder abrir el dispositivo de salida, que
    es COM y puede fallar por su cuenta. Tragarse ese motivo y decir «falta
    pycaw» manda a reinstalar lo que ya está puesto."""
    try:
        from pycaw.utils import AudioUtilities
        AudioUtilities.GetSpeakers()
        return ""
    except Exception as exc:                                     # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


def _hay_pycaw() -> bool:
    """True si pycaw sirve aquí. El volumen por aplicación lo necesita: nircmd
    solo sabe del volumen general."""
    return not _porque_no_pycaw()


def _proceso_en_marcha(nombre: str) -> bool:
    """¿Hay un proceso en marcha que se llame así? Misma puntería que al cerrar
    programas: primero el nombre EXACTO (con o sin `.exe`) y solo si no casa
    ninguno, la subcadena."""
    low = _ALIAS_PROCESO.get(nombre.lower().strip(), nombre.lower().strip())
    if not low:
        return False
    en_marcha = _proc_names()
    if not en_marcha:
        return False
    if low in en_marcha or f"{low}.exe" in en_marcha:
        return True
    return any(low in n for n in en_marcha)


def _detalle_pycaw(motivo: str) -> str:
    """Convierte el motivo crudo en algo accionable, sin ocultarlo.

    Un `ModuleNotFoundError` sí se arregla instalando; cualquier otra cosa
    significa que está instalado y falla por otro lado, y mandar a reinstalar
    ahí es hacer perder el tiempo."""
    if "ModuleNotFoundError" in motivo or "ImportError" in motivo:
        return "No está instalado: «pip install pycaw comtypes» y reinicia nexus."
    return f"Está instalado, pero Windows contesta: {motivo}."


def _motivo_sin_mezclador() -> str:
    """Por qué no se puede tocar el volumen general, mirando las DOS vías.

    Las dos se nombran siempre: saber cuál falta y cuál no es lo que distingue
    «instala algo» de «está puesto y aun así no va»."""
    cola = "" if _hay_nircmd() else " Tampoco tengo nircmd en el PATH."
    motivo = _porque_no_pycaw()
    if motivo:
        return _detalle_pycaw(motivo) + cola
    return "pycaw responde, pero el dispositivo de salida no ha aceptado la orden." + cola


def _sesiones_de(nombre: str) -> list:
    """Sesiones de audio que casan con el nombre pedido. Misma puntería que el
    cierre de procesos: primero el nombre EXACTO (con o sin `.exe`) y solo si no
    casa ninguno se cae a la subcadena, para que «code» no se lleve «codecs»."""
    low = _ALIAS_PROCESO.get(nombre.lower().strip(), nombre.lower().strip())
    if low.endswith(".exe"):
        low = low[:-4]
    exactos, parciales = [], []
    for n, vol in _sesiones_audio():
        nl = n.lower()
        if nl == low or nl == f"{low}.exe" or nl.rsplit(".", 1)[0] == low:
            exactos.append((n, vol))
        elif low and low in nl:
            parciales.append((n, vol))
    return exactos or parciales


def _hay_nircmd() -> bool:
    """True si nircmd está en el PATH."""
    import shutil
    return shutil.which("nircmd") is not None


def _accion_volumen(text: str) -> tuple:
    """Qué pide la orden: ('set', 0-100) | ('step', ±10) | ('mute', None) |
    ('unmute', None). Quitar el silencio se mira ANTES que silenciar, porque
    «quita el silencio» contiene la palabra «silencio»."""
    t = text.lower()
    if re.search(r"\b" + _QUITAR_SILENCIO, t):
        return "unmute", None
    # «mute» como sustantivo va DESPUÉS de quitarlo, porque «quítale el mute»
    # lleva la palabra dentro. Antes no estaba y esa frase caía al final del
    # todo, que es «subir»: pedir que vuelva a sonar te subía el volumen.
    if re.search(r"\b(?:sil[eé]ncia\w*|mut[eé]a\w*|silencio|mute)\b", t) or \
            re.search(r"\bqu[ií]ta\w*\s+el\s+(?:sonido|audio|volumen)\b", t):
        return "mute", None
    m = re.search(r"\b(\d{1,3})\s*%?", t)
    if m:
        return "set", max(0, min(100, int(m.group(1))))
    if re.search(r"\b(?:b[aá]ja\w*|menos)\b", t):
        return "step", -10
    return "step", 10


def _volumen_pc(text: str) -> dict:
    """Volumen maestro de este PC. pycaw primero; nircmd solo como respaldo."""
    accion, valor = _accion_volumen(text)
    ev = _mezclador_maestro()
    if ev is not None:
        try:
            if accion == "mute":
                ev.SetMute(1, None)
                return {"reply": "PC en silencio. ✔", "data": {"target": "pc", "mute": 1}}
            if accion == "unmute":
                ev.SetMute(0, None)
                leido = round(ev.GetMasterVolumeLevelScalar() * 100)
                return {"reply": f"El PC vuelve a sonar, al {leido}%. ✔",
                        "data": {"target": "pc", "mute": 0, "ahora": leido}}
            antes = round(ev.GetMasterVolumeLevelScalar() * 100)
            destino = valor if accion == "set" else max(0, min(100, antes + valor))
            ev.SetMasterVolumeLevelScalar(destino / 100.0, None)
            leido = round(ev.GetMasterVolumeLevelScalar() * 100)
            aviso = (" Ojo: el PC está silenciado, así que no lo vas a oír; "
                     "di «quita el silencio del pc».") if ev.GetMute() else ""
            return {"reply": f"Volumen del PC al {leido}%. ✔" + aviso,
                    "data": {"target": "pc", "antes": antes, "ahora": leido}}
        except Exception as exc:                           # noqa: BLE001
            return {"reply": f"He intentado tocar el volumen del PC con pycaw y Windows lo ha "
                             f"rechazado ({type(exc).__name__}). No te digo que esté hecho, "
                             "porque no lo está."}
    if sys.platform == "win32" and _hay_nircmd():
        try:
            if accion in ("mute", "unmute"):
                subprocess.run(["nircmd", "mutesysvolume", "1" if accion == "mute" else "0"],
                               timeout=3, check=True)
                return {"reply": ("PC en silencio (por nircmd). ✔" if accion == "mute"
                                  else "El PC vuelve a sonar (por nircmd). ✔")}
            if accion == "set":
                subprocess.run(["nircmd", "setsysvolume", str(int(valor * 655.35))],
                               timeout=3, check=True)
                return {"reply": f"Volumen del PC al {valor}% (por nircmd). ✔"}
            subprocess.run(["nircmd", "changesysvolume", str(int(valor * 655.35))],
                           timeout=3, check=True)
            return {"reply": f"Volumen del PC {'subido' if valor > 0 else 'bajado'} "
                             "(por nircmd). ✔"}
        except Exception:                                  # noqa: BLE001
            pass
    return {"reply": "No puedo tocar el volumen del PC: " + _motivo_sin_mezclador()}


def _volumen_app(text: str, nombre: str) -> dict:
    """Volumen de la sesión de audio de una aplicación concreta."""
    nombre = (nombre or "").strip()
    motivo = _porque_no_pycaw()
    if motivo:
        return {"reply": f"No puedo con el volumen de {nombre}: " + _detalle_pycaw(motivo)}
    sesiones = _sesiones_de(nombre)
    if not sesiones:
        abiertas = sorted({n.rsplit(".", 1)[0] if n.lower().endswith(".exe") else n
                           for n, _v in _sesiones_audio()})
        extra = (" Ahora mismo suenan: " + ", ".join(abiertas) + ".") if abiertas \
            else " Ahora mismo no hay ninguna aplicación con sesión de audio abierta."
        # Windows solo crea la sesión de audio cuando la aplicación EMPIEZA a
        # sonar. Abierta y callada no tiene volumen que tocar, y decir «no tiene
        # sesión» a secas suena a que no está: son dos situaciones distintas y se
        # arreglan de forma distinta (darle al play, o abrirla).
        if _proceso_en_marcha(nombre):
            return {"reply": f"{nombre.title()} está abierto pero no suena. Dale al play."}
        return {"reply": f"{nombre.title()} no está abierto.{extra}"}
    accion, valor = _accion_volumen(text)
    crudo = sesiones[0][0]
    prog = (crudo.rsplit(".", 1)[0] if crudo.lower().endswith(".exe") else crudo).title()
    try:
        if accion == "mute":
            for _n, v in sesiones:
                v.SetMute(1, None)
            return {"reply": f"{prog} en silencio. ✔", "data": {"target": crudo, "mute": 1}}
        if accion == "unmute":
            for _n, v in sesiones:
                v.SetMute(0, None)
            leido = round(sesiones[0][1].GetMasterVolume() * 100)
            return {"reply": f"{prog} vuelve a sonar, al {leido}%. ✔",
                    "data": {"target": crudo, "mute": 0, "ahora": leido}}
        antes = round(sesiones[0][1].GetMasterVolume() * 100)
        destino = valor if accion == "set" else max(0, min(100, antes + valor))
        for _n, v in sesiones:
            v.SetMasterVolume(destino / 100.0, None)
        leido = round(sesiones[0][1].GetMasterVolume() * 100)
        aviso = (f" Ojo: {prog} está silenciado; di «quita el silencio de {crudo}» "
                 "para oírlo.") if sesiones[0][1].GetMute() else ""
        return {"reply": f"Volumen de {prog} al {leido}%. ✔" + aviso,
                "data": {"target": crudo, "antes": antes, "ahora": leido}}
    except Exception as exc:                                         # noqa: BLE001
        return {"reply": f"He intentado tocar el volumen de {prog} y Windows lo ha "
                         f"rechazado ({type(exc).__name__}). No te digo que esté hecho, "
                         "porque no lo está."}


def _brillo_actual():
    """Brillo de la pantalla en 0-100, o None si el panel no lo expone.

    Se pregunta por WMI (root/WMI, WmiMonitorBrightness). Los portátiles casi
    siempre responden; los monitores de sobremesa casi nunca, porque llevan el
    control en sus propios botones y Windows no lo alcanza.
    """
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness"
             " -ErrorAction Stop).CurrentBrightness"],
            capture_output=True, text=True, timeout=6)
        linea = (out.stdout or "").strip().splitlines()
        return int(linea[0]) if linea and linea[0].strip().isdigit() else None
    except Exception:                                      # noqa: BLE001
        return None


def _pon_brillo(pct: int) -> bool:
    """Fija el brillo. Devuelve False si Windows no lo acepta."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods"
             f" -ErrorAction Stop).WmiSetBrightness(1,{int(pct)})"],
            capture_output=True, text=True, timeout=6)
        return out.returncode == 0
    except Exception:                                      # noqa: BLE001
        return False


def _cpu_temp():
    """Temperatura de CPU en °C (float) o None. Windows no la expone por psutil,
    así que probamos, en orden: psutil (Linux/algunos) → LibreHardwareMonitor u
    OpenHardwareMonitor por WMI (si están abiertos) → MSAcpi_ThermalZoneTemperature."""
    # 1) psutil — funciona en Linux y en algún hardware
    if psutil is not None:
        try:
            sensors = psutil.sensors_temperatures() or {}
            for key in ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal"):
                if sensors.get(key):
                    return max(s.current for s in sensors[key] if s.current)
            for arr in sensors.values():
                if arr and arr[0].current:
                    return arr[0].current
        except Exception:
            pass
    if sys.platform != "win32":
        return None
    # 2) LibreHardwareMonitor / OpenHardwareMonitor por WMI (lo más fiable en Windows)
    try:
        import wmi  # pip install wmi (lo instala run.bat)
        for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
            try:
                w = wmi.WMI(namespace=ns)
                temps = [s for s in w.Sensor() if getattr(s, "SensorType", "") == "Temperature"]
                cpu = [s.Value for s in temps if s.Value and "CPU" in (s.Name or "")
                       and any(k in (s.Name or "") for k in ("Package", "Core", "CCD", "Tctl"))]
                if cpu:
                    return max(cpu)
                cpu_any = [s.Value for s in temps if s.Value and "CPU" in (s.Name or "")]
                if cpu_any:
                    return max(cpu_any)
            except Exception:
                continue
    except Exception:
        pass
    # 3) MSAcpi_ThermalZoneTemperature (décimas de Kelvin; a veces requiere admin)
    try:
        import wmi
        vals = [z.CurrentTemperature for z in
                wmi.WMI(namespace="root\\wmi").MSAcpi_ThermalZoneTemperature()]
        if vals:
            return (min(vals) / 10.0) - 273.15
    except Exception:
        pass
    return None


def _gpu_info():
    """Info de GPU NVIDIA por nvidia-smi: {name, temp, util, mem_used, mem_total} o None."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4)
        line = (out.stdout or "").strip().splitlines()[0]
        name, temp, util, mused, mtot = [x.strip() for x in line.split(",")]
        return {"name": name, "temp": float(temp), "util": float(util),
                "mem_used": float(mused), "mem_total": float(mtot)}
    except Exception:
        return None


def _temps_report() -> str:
    """Solo temperaturas — para «¿a qué temperatura está la CPU/gráfica?»."""
    parts = []
    ct = _cpu_temp()
    parts.append(f"CPU {ct:.0f}°C" if ct is not None else
                 "CPU n/d (para leerla en Windows, ten abierto LibreHardwareMonitor)")
    g = _gpu_info()
    if g:
        parts.append(f"GPU {g['name']} {g['temp']:.0f}°C")
    else:
        parts.append("GPU n/d (sin NVIDIA detectada por nvidia-smi)")
    return " · ".join(parts)


def _hw_report() -> str:
    if psutil is None:
        return ("no puedo leer CPU/RAM/disco: falta psutil (pip install psutil y reinicia). "
                "No te doy cifras que no he medido")
    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.3)
    cpu_txt = f"CPU {cpu:.0f}% ({psutil.cpu_count()} núcleos)"
    ct = _cpu_temp()
    if ct is not None:
        cpu_txt += f" a {ct:.0f}°C"
    parts = [cpu_txt,
             f"RAM {vm.percent:.0f}% de {vm.total/2**30:.1f} GB",
             f"Disco {psutil.disk_usage('/').percent:.0f}%"]
    g = _gpu_info()
    if g:
        parts.append(f"GPU {g['name']} {g['util']:.0f}% a {g['temp']:.0f}°C "
                     f"({g['mem_used']/1024:.1f}/{g['mem_total']/1024:.1f} GB)")
    parts.append(f"{platform.system()} {platform.release()}")
    return " · ".join(parts)


def _proc_names() -> set:
    """Conjunto de nombres de proceso en marcha (en minúsculas)."""
    if psutil is None:
        return set()
    out = set()
    for p in psutil.process_iter(["name"]):
        n = (p.info.get("name") or "").lower()
        if n:
            out.add(n)
    return out


def _tokens(name: str) -> list:
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split() if len(w) > 2]


# ─────────────────────────────────────────────────────────────────────────────
# PUERTOS EN ESCUCHA
#
# Añadido el 05/08/2026 porque NINGUNA de las 32 skills sabía mirar puertos.
# «qué programa está usando el puerto 5678» no casaba con ningún patrón, así que
# la decisión la tomaba el modelo: una vez delegó en Hermes y acertó, otra
# devolvió un ranking de procesos por memoria, al instante y con total
# seguridad. Falso y no determinista.
#
# LA REGLA AQUÍ ES QUE O SALE DEL SISTEMA O SE DICE QUE NO SE SABE. Hay tres
# formas de no saberlo y las tres se cuentan tal cual: sin psutil y sin netstat,
# psutil que no deja mirar (en Windows los procesos de otros usuarios necesitan
# administrador), y un puerto en el que sencillamente no escucha nadie. Ninguna
# de las tres se rellena con «lo más parecido».
# ─────────────────────────────────────────────────────────────────────────────

def _nombre_de_pid(pid) -> str:
    """Nombre del ejecutable de un PID, o '' si no se puede saber.

    Cadena vacía significa «no lo sé», y quien la reciba lo enseña como PID a
    secas. Devolver aquí un nombre aproximado sería exactamente el fallo que
    este bloque viene a arreglar."""
    if pid is None or psutil is None:
        return ""
    try:
        return psutil.Process(pid).name() or ""
    except Exception:                                      # noqa: BLE001
        return ""


def _puertos_por_psutil():
    """[(puerto, pid, nombre)] de lo que ESCUCHA, o None si psutil no puede.

    None NO es «no hay puertos»: es «no lo he podido mirar». Son dos respuestas
    distintas para el usuario y por eso no comparten valor de retorno."""
    if psutil is None:
        return None
    escucha = getattr(psutil, "CONN_LISTEN", "LISTEN")
    try:
        conexiones = psutil.net_connections(kind="inet")
    except Exception:                                      # noqa: BLE001
        # AccessDenied en Windows sin administrador, y cualquier otra cosa que
        # psutil eche por aquí. Se cae al respaldo, no se inventa nada.
        return None
    filas = []
    for c in conexiones:
        if getattr(c, "status", "") != escucha:
            continue
        laddr = getattr(c, "laddr", None)
        puerto = getattr(laddr, "port", None)
        if puerto is None:
            continue
        filas.append((int(puerto), getattr(c, "pid", None),
                      _nombre_de_pid(getattr(c, "pid", None))))
    return filas


def _nombres_por_pid_tasklist() -> dict:
    """pid -> nombre del ejecutable, leído de `tasklist`. {} si no se puede.

    Solo hace falta cuando psutil no está: `netstat -ano` da el PID pero no el
    nombre, y un PID a pelo no le dice nada a nadie."""
    if sys.platform != "win32":
        return {}
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                             capture_output=True, text=True, timeout=10,
                             encoding="utf-8", errors="replace")
    except Exception:                                      # noqa: BLE001
        return {}
    tabla = {}
    for linea in (out.stdout or "").splitlines():
        campos = re.findall(r'"([^"]*)"', linea)
        if len(campos) >= 2 and campos[1].strip().isdigit():
            tabla[int(campos[1].strip())] = campos[0].strip()
    return tabla


def _puertos_por_netstat():
    """[(puerto, pid, nombre)] leído de `netstat -ano`, o None si no se puede.

    Es el respaldo de `_puertos_por_psutil`. La línea de netstat en Windows es
    «TCP  0.0.0.0:8177  0.0.0.0:0  LISTENING  1234»: se coge el puerto de la
    dirección LOCAL (la segunda columna) y el PID de la última."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=15, encoding="utf-8", errors="replace")
    except Exception:                                      # noqa: BLE001
        return None
    if getattr(out, "returncode", 1) != 0:
        return None
    nombres = _nombres_por_pid_tasklist()
    filas = []
    for linea in (out.stdout or "").splitlines():
        campos = linea.split()
        # Solo TCP en escucha: en UDP no existe el estado LISTENING y una
        # entrada UDP no significa que haya nadie atendiendo.
        if len(campos) < 5 or campos[0].upper() != "TCP" or campos[3].upper() != "LISTENING":
            continue
        m = re.search(r":(\d{1,5})$", campos[1])
        if not m:
            continue
        pid = int(campos[4]) if campos[4].isdigit() else None
        filas.append((int(m.group(1)), pid, nombres.get(pid, "")))
    return filas


def _puertos_en_escucha():
    """(filas, motivo). `filas` es [(puerto, pid, nombre)] cuando se ha podido
    mirar; `None` cuando NO, y entonces `motivo` explica por qué.

    Nunca devuelve las dos cosas a medias: o hay dato, o hay explicación."""
    filas = _puertos_por_psutil()
    if filas is not None:
        return filas, ""
    filas = _puertos_por_netstat()
    if filas is not None:
        return filas, ""
    if psutil is None and sys.platform != "win32":
        return None, ("No puedo mirar los puertos: falta psutil (pip install psutil y "
                      "reinicia) y aquí no tengo el netstat de Windows como respaldo.")
    if psutil is None:
        return None, ("No puedo mirar los puertos: falta psutil (pip install psutil y "
                      "reinicia) y netstat tampoco me ha contestado.")
    return None, ("No he podido leer la tabla de puertos: psutil me la ha denegado "
                  "—en Windows los procesos de otros usuarios piden administrador— y "
                  "netstat tampoco me ha contestado. No te la invento.")


def _quien_escucha(filas, puerto: int) -> list:
    """Las filas que escuchan en ESE puerto, sin repetir proceso."""
    vistos, salida = set(), []
    for p, pid, nombre in filas:
        if p != puerto or (pid, nombre) in vistos:
            continue
        vistos.add((pid, nombre))
        salida.append((p, pid, nombre))
    return salida


def _etiqueta_proceso(pid, nombre: str) -> str:
    """Cómo se nombra un proceso en la respuesta. Sin nombre se enseña el PID a
    secas: es menos cómodo, pero es lo que se sabe."""
    if nombre and pid is not None:
        return f"{nombre} (PID {pid})"
    if nombre:
        return nombre
    if pid is not None:
        return f"un proceso del que Windows no me da el nombre (PID {pid})"
    return "un proceso del sistema, sin PID visible"


async def _verify_started(before: set, name_hint: str, wait: float = 1.8):
    """Comprueba de VERDAD si arrancó LO QUE SE PIDIÓ, comparando procesos
    antes/después. Devuelve (estado, detalle):
      'yes'     = arrancó (o ya estaba) un proceso que CASA con el nombre pedido
      'other'   = arrancó algo, pero NO casa con el nombre (quizá un launcher/otra cosa)
      'no'      = no arrancó nada ni casa nada → NO se abrió (no mentimos)
      'unknown' = sin psutil, no se puede verificar → se da por lanzado sin afirmar de más."""
    if psutil is None:
        return "unknown", ""
    import asyncio as _a
    await _a.sleep(wait)
    after = _proc_names()
    new = after - before
    toks = _tokens(name_hint)
    def casa(n):
        return any(t in n for t in toks)
    new_match = [n for n in new if casa(n)]
    if new_match:
        return "yes", new_match[0]
    if any(casa(n) for n in after):          # ya estaba abierto y coincide con el nombre
        return "yes", next(n for n in after if casa(n)) + " (ya estaba en marcha)"
    if new:
        return "other", sorted(new, key=len)[-1]   # abrió algo, pero no casa el nombre
    return "no", ""


def _steam_root():
    """Carpeta raíz de Steam (registro o rutas por defecto). None si no está."""
    if sys.platform == "win32":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            p = winreg.QueryValueEx(k, "SteamPath")[0]
            if p and Path(p).exists():
                return Path(p)
        except Exception:
            pass
    for c in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if Path(c).exists():
            return Path(c)
    return None


def _steam_installed() -> list:
    """Juegos Steam INSTALADOS: [(appid, nombre)] leyendo appmanifest_*.acf."""
    root = _steam_root()
    if not root:
        return []
    libs = [root / "steamapps"]
    try:
        vdf = (root / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"path"\s*"([^"]+)"', vdf):
            libs.append(Path(m.group(1).replace("\\\\", "\\")) / "steamapps")
    except Exception:
        pass
    games, seen = [], set()
    for lib in libs:
        try:
            for acf in lib.glob("appmanifest_*.acf"):
                t = acf.read_text(encoding="utf-8", errors="ignore")
                aid = re.search(r'"appid"\s*"(\d+)"', t)
                nm = re.search(r'"name"\s*"([^"]+)"', t)
                if aid and nm and aid.group(1) not in seen:
                    seen.add(aid.group(1))
                    games.append((aid.group(1), nm.group(1)))
        except Exception:
            continue
    return games


def _match_steam_game(query: str):
    """Empareja la petición con un juego INSTALADO. (appid, nombre) o (None, None)."""
    q = query.lower().strip()
    qtok = _tokens(q)
    for aid, nm in _steam_installed():
        low = nm.lower()
        if q in low or low in q or any(t in low for t in qtok):
            return aid, nm
    return None, None


async def handle(intent: str, text: str, match, ctx) -> dict:
    bus = ctx["bus"]

    if intent == "volume":
        return _volumen_pc(text)

    if intent == "volume_app":
        gd = match.groupdict()
        nombre = next((gd.get(k) for k in ("app", "app2", "app3", "app4", "app5")
                       if gd.get(k)), "")
        return _volumen_app(text, nombre)

    if intent == "volume_ask":
        return {"reply": "¿De qué? La tele, el PC o una aplicación."}

    if intent == "brightness":
        num = match.groupdict().get("bri")
        baja = bool(re.search(r"\bbaja", text, re.IGNORECASE))
        if sys.platform != "win32":
            return {"reply": "El brillo de la pantalla solo lo sé tocar en Windows, "
                             "y esto no es Windows."}
        # WMI expone el brillo solo si el panel lo soporta: los portatiles casi
        # siempre, los monitores de sobremesa casi nunca (ahi lo manda su propio
        # menu por hardware). Si no responde, se dice; no se finge que ha ido.
        actual = _brillo_actual()
        if actual is None:
            return {"reply": "Tu pantalla no deja que Windows le cambie el brillo: no expone "
                             "el control por WMI. Suele pasar en monitores de sobremesa, que "
                             "lo llevan en sus propios botones. En un portátil sí funcionaría."}
        destino = int(num) if num else max(0, min(100, actual + (-10 if baja else 10)))
        destino = max(0, min(100, destino))
        if not _pon_brillo(destino):
            return {"reply": f"He pedido el brillo al {destino}% y Windows no lo ha aceptado. "
                             "Puede que haga falta ejecutar nexus como administrador."}
        return {"reply": f"Brillo al {destino}%. ✔"}

    if intent == "hardware":
        from backend.core.comun import permissions
        if not permissions.hardware_allowed():
            return {"reply": permissions.HW_DENIED}
        return {"reply": f"Informe de sistemas: {_hw_report()}. "
                         "Si quieres afinar, di «lista los procesos» y vemos quién consume."}

    if intent == "temps":
        from backend.core.comun import permissions
        if not permissions.hardware_allowed():
            return {"reply": permissions.HW_DENIED}
        return {"reply": f"Temperaturas: {_temps_report()}"}

    if intent == "processes":
        if psutil is None:
            return {"reply": "No puedo leer los procesos: falta psutil (pip install psutil y "
                             "reinicia). No me invento una lista."}
        procs = sorted(psutil.process_iter(["name", "memory_info"]),
                       key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0,
                       reverse=True)[:8]
        top = " · ".join(f"{p.info['name']} {p.info['memory_info'].rss/2**20:.0f} MB"
                         for p in procs if p.info["name"])
        return {"reply": f"Top procesos por memoria: {top}. "
                         "Di «cierra el proceso <nombre>» y tumbo el que sobre."}

    if intent == "port_who":
        gd = match.groupdict()
        crudo = next((gd.get(k) for k in ("port", "port2", "port3", "port4")
                      if gd.get(k)), "")
        puerto = int(crudo)
        filas, motivo = _puertos_en_escucha()
        if filas is None:
            return {"reply": motivo}
        duenyos = _quien_escucha(filas, puerto)
        # UN PUERTO SIN NADIE SE DICE TAL CUAL. Aquí es donde el planificador se
        # inventaba una respuesta: no se ofrece «lo más parecido» ni se cambia
        # la pregunta por otra que sí se sepa contestar.
        if not duenyos:
            return {"reply": f"En el puerto {puerto} no escucha nadie ahora mismo. "
                             "Está libre."}
        if len(duenyos) == 1:
            _p, pid, nombre = duenyos[0]
            return {"reply": f"En el puerto {puerto} escucha {_etiqueta_proceso(pid, nombre)}."}
        lista = ", ".join(_etiqueta_proceso(pid, nombre) for _p, pid, nombre in duenyos)
        return {"reply": f"En el puerto {puerto} escuchan {len(duenyos)} procesos: {lista}."}

    if intent == "ports":
        filas, motivo = _puertos_en_escucha()
        if filas is None:
            return {"reply": motivo}
        if not filas:
            return {"reply": "No hay ningún puerto en escucha en este equipo."}
        # Un puerto puede aparecer varias veces (IPv4 e IPv6, varias interfaces):
        # se enseña una vez por puerto.
        por_puerto = {}
        for p, pid, nombre in sorted(filas):
            por_puerto.setdefault(p, (pid, nombre))
        tope = int(_reglas.valor("system_pc.puertos_en_lista"))
        puertos = sorted(por_puerto)
        visibles = puertos[:tope]
        texto = " · ".join(f"{p}: {_etiqueta_proceso(*por_puerto[p])}" for p in visibles)
        resto = len(puertos) - len(visibles)
        # LO QUE NO CABE SE CUENTA, NO SE ESCONDE: una lista recortada en
        # silencio es una lista que miente sobre cuántos puertos hay abiertos.
        cola = f" Y {resto} puerto(s) más en escucha." if resto > 0 else ""
        return {"reply": f"Puertos en escucha ({len(puertos)}): {texto}.{cola}"}

    if intent == "kill":
        gd = match.groupdict()
        name = next((gd.get(k) for k in ("proc", "proc2", "proc3", "proc4", "proc5")
                     if gd.get(k)), "")
        if psutil is None:
            return {"reply": f"Sin psutil no puedo tocar procesos de verdad (pip install psutil "
                             f"y reinicia). No he terminado «{name}»."}
        # El nombre coloquial no es el del ejecutable: «cierra el navegador» tiene
        # que buscar chrome.exe. Misma tabla que usa la apertura de apps.
        low = _ALIAS_PROCESO.get(name.lower().strip(), name.lower().strip())
        exactos, parciales = [], []
        for p in psutil.process_iter(["name", "pid"]):
            n = (p.info.get("name") or "")
            if not n:
                continue
            nl = n.lower()
            if nl == low or nl == f"{low}.exe" or nl.rsplit(".", 1)[0] == low:
                exactos.append((p, n, p.info.get("pid")))
            elif low in nl:
                parciales.append((p, n, p.info.get("pid")))
        # El nombre exacto manda: «cierra el proceso code» no debe llevarse
        # también a «codecs_host». Solo si no casa ninguno se usa la subcadena.
        victimas = exactos or parciales
        if not victimas:
            return {"reply": f"No encuentro ningún proceso llamado «{name}». "
                             "Di «lista los procesos» y te enseño los que hay en marcha."}

        # Cerrar procesos es directo, sin confirmación: es lo que se le pide.
        ok, fallidos = 0, 0
        for p, _n, _pid in victimas:
            try:
                p.terminate()
                ok += 1
            except Exception:                              # noqa: BLE001
                fallidos += 1
        if not ok:
            return {"reply": f"No he podido terminar ninguno de los {len(victimas)} proceso(s) "
                             f"de «{name}»: seguramente hagan falta permisos de administrador."}
        # Un solo nombre, sin PIDs: lo que el operador quiere saber es que ya está.
        programa = victimas[0][1]
        for _p, n, _pid in victimas:
            if n.lower().startswith(low):
                programa = n
                break
        programa = programa.rsplit(".", 1)[0] if programa.lower().endswith(".exe") else programa
        extra = f" ({fallidos} instancia(s) se han resistido, seguramente por permisos)" \
            if fallidos else ""
        # Se varía la frase: es una orden que se repite muchas veces al día y
        # siempre la misma respuesta suena a grabación.
        import random
        plantilla = random.choice(_CERRADO_FRASES)
        return {"reply": plantilla.format(prog=programa.title()) + extra + ".",
                "data": {"killed": ok, "failed": fallidos, "program": programa}}

    if intent == "youtube":
        q = (match.groupdict().get("yt") or match.groupdict().get("yt2") or "").strip()
        url = f"https://www.youtube.com/results?search_query={q.replace(' ', '+')}" if q \
            else "https://www.youtube.com"
        webbrowser.open(url)
        return {"reply": f"Abriendo YouTube{f' y buscando «{q}»' if q else ''}."}

    if intent == "open_web":
        gd = match.groupdict()
        raw = (gd.get("url") or gd.get("url2") or "").strip().rstrip(".?!,;:")
        low_raw = raw.lower()
        # 1) URL o dominio explícito → directo, sin pensar
        if raw.startswith("http://") or raw.startswith("https://"):
            webbrowser.open(raw)
            return {"reply": f"Abriendo {raw}."}
        if "." in raw and " " not in raw:
            webbrowser.open("https://" + raw)
            return {"reply": f"Abriendo https://{raw}."}
        # 2) Webs ya APRENDIDAS (el modelo las dedujo antes) → instantáneo
        import json as _json
        from backend.core.comun.config import DATA_DIR
        cache_file = DATA_DIR / "web_urls.json"
        try:
            cache = _json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
        if low_raw in cache:
            webbrowser.open(cache[low_raw])
            return {"reply": f"Abriendo {raw} ({cache[low_raw]})."}
        # 3) El MODELO razona la URL oficial de CUALQUIER web que le pidas
        #    (sin listas fijas). Si acierta, la memoriza para la próxima vez.
        url = ""
        try:
            from backend.core.infraestructura.llm import get_provider_safe
            prov = await get_provider_safe()
            if prov is not None and prov.name != "mock":
                out = await prov.chat([
                    {"role": "system", "content":
                     "Devuelve SOLO la URL oficial y completa (empezando por https://) "
                     "de la web que te pida el usuario. Una sola línea, sin comillas ni "
                     "explicaciones. Prioriza la versión española (.es o /es) si existe. "
                     "Si de verdad no conoces su web oficial, responde exactamente SEARCH."},
                    {"role": "user", "content": f"La web de: {raw}"}])
                cand = (out or "").strip().splitlines()[0].strip().strip('"\'«»<>').rstrip(".")
                if re.match(r"^https?://[\w.\-]+(?::\d+)?(?:/\S*)?$", cand) \
                        and "SEARCH" not in cand.upper():
                    url = cand
        except Exception:
            pass
        if url:
            webbrowser.open(url)
            cache[low_raw] = url          # aprendida: la próxima vez ni lo piensa
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(_json.dumps(cache, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
            except Exception:
                pass
            return {"reply": f"Abriendo la web de {raw} → {url}"}
        # 4) Último recurso (modelo apagado o no la conoce): búsqueda en Google,
        #    que es lo honesto — mejor que inventarse un dominio.
        webbrowser.open(f"https://www.google.com/search?q={raw.replace(' ', '+')}")
        return {"reply": f"No he podido deducir la URL de «{raw}» (¿modelo apagado?); "
                         "te la he buscado en Google — el primer resultado será su web."}

    if intent == "set_mac":
        mac = match.group("mac")
        ctx["settings"].set("wol_mac", mac)
        return {"reply": f"MAC guardada ({mac}). Ahora puedo encender ese equipo con "
                         "«enciende el ordenador» (necesita Wake-on-LAN activado en su BIOS)."}

    if intent == "wake":
        mac = ctx["settings"].get("wol_mac", "")
        if not mac:
            return {"reply": "No tengo la MAC del equipo a encender. Dímela: «guarda la mac "
                             "aa:bb:cc:dd:ee:ff» (la ves con «ipconfig /all» → Dirección física). "
                             "Y activa Wake-on-LAN en la BIOS y en el adaptador de red del PC."}
        bcast = ctx["settings"].get("wol_broadcast", "255.255.255.255")
        ok = _send_magic_packet(mac, bcast)
        return {"reply": f"Paquete mágico enviado a {mac}. Si el equipo tiene Wake-on-LAN "
                         "activado y está en la misma red, debería encenderse en unos segundos."
                if ok else "No he podido enviar el paquete (¿MAC válida? ¿red disponible?)."}

    if intent == "reindex":
        from backend.core.infraestructura.app_index import build_index
        import asyncio
        apps = await asyncio.to_thread(build_index)
        return {"reply": f"Índice reconstruido: conozco {len(apps)} aplicaciones instaladas."
                if apps else "Índice vacío (esto solo funciona en Windows)."}

    if intent == "list_apps":
        from backend.core.infraestructura.app_index import get_index
        apps = get_index()
        if not apps:
            return {"reply": "Aún no tengo índice de aplicaciones (¿estamos en Windows? "
                             "prueba «reindexa las aplicaciones»)."}
        sample = " · ".join(sorted(apps)[:25])
        return {"reply": f"Conozco {len(apps)} aplicaciones instaladas. Muestra: {sample}…"}

    if intent == "open_app":
        app = match.group("app").strip().rstrip(".?!")
        low = app.lower().strip()
        # 1) Webs frecuentes (no son apps instaladas)
        web_alias = {"internet": "https://www.google.com",
                     "whatsapp web": "https://web.whatsapp.com",
                     "gmail": "https://mail.google.com",
                     "el calendario de google": "https://calendar.google.com",
                     "twitch": "https://www.twitch.tv"}
        if low in web_alias:
            webbrowser.open(web_alias[low])
            return {"reply": f"Abriendo {app}."}

        # 2) ÍNDICE COMPLETO de aplicaciones instaladas (Menú Inicio +
        #    registro + Microsoft Store) con búsqueda difusa.
        #    Si el índice está vacío (primer uso / arranque incompleto),
        #    lo construimos AHORA en vez de decir que no se puede.
        import asyncio
        from backend.core.infraestructura.app_index import build_index, find_app, get_index, launch
        if not get_index() and sys.platform == "win32":
            await ctx["bus"].emit("log", {"level": "info",
                                          "msg": "Índice de apps vacío — escaneando ahora..."})
            await asyncio.to_thread(build_index)
        hit = find_app(app)
        if hit:
            name, target = hit
            before = _proc_names()
            try:
                launch(target)
            except Exception as exc:
                return {"reply": f"He encontrado «{name}» pero no se deja abrir: {exc}"}
            st, detail = await _verify_started(before, name or app)
            if st == "no":
                return {"reply": f"He intentado abrir «{name.title()}» pero NO detecto que "
                                 "haya arrancado. ¿Sigue cargando, o el acceso directo apunta a "
                                 "algo que ya no existe? (prueba «reindexa las aplicaciones»)."}
            if st == "other":
                return {"reply": f"He lanzado algo ({detail}) pero no estoy seguro de que sea "
                                 f"«{name.title()}». Échale un ojo, por si acaso."}
            if st == "yes":
                return {"reply": f"Listo, {name.title()} está abierto. ✓"}
            return {"reply": f"Abriendo {name.title()}…"}   # sin psutil: no puedo confirmar

        # 3b) ¿Es un JUEGO de Steam INSTALADO? Solo lanzamos lo que está instalado:
        #     si no, mentiríamos diciendo que lo abrimos.
        if sys.platform == "win32":
            aid, gname = _match_steam_game(app)
            if aid:
                before = _proc_names()
                os.system(f'start "" steam://rungameid/{aid}')
                st, _d = await _verify_started(before, gname, wait=3.0)
                if st == "no":
                    return {"reply": f"He pedido a Steam abrir «{gname}» (appid {aid}) pero no "
                                     "arranca. Revisa que Steam esté abierto y con la sesión iniciada."}
                return {"reply": f"Lanzando «{gname}» desde Steam ▶ ✓"}
            # No está instalado → NO decimos que lo abrimos. Ofrecemos la tienda.
            store = await asyncio.to_thread(_steam_appid_by_name, app)
            if store:
                return {"reply": f"No veo «{app}» instalado en Steam, así que no puedo abrirlo. "
                                 f"Existe en la tienda; si quieres instalarlo dime «instala {app} en steam»."}

        # 3) Último recurso: comandos clásicos de Windows / protocolo URI.
        #    OJO: los valores NO llevan 'start' (ya lo añade el wrapper de abajo);
        #    antes ponía «start "" start spotify:» y por eso no abría Spotify.
        alias = {"calculadora": "calc", "notas": "notepad", "explorador": "explorer",
                 "navegador": "chrome", "terminal": "cmd", "cmd": "cmd",
                 "spotify": "spotify:", "steam": "steam://open/main",
                 "epic": "com.epicgames.launcher://", "whatsapp": "whatsapp:"}
        before = _proc_names()
        try:
            if sys.platform == "win32":
                if low == "discord":
                    os.system('start "" "%LOCALAPPDATA%\\Discord\\Update.exe" --processStart Discord.exe')
                else:
                    os.system(f'start "" {alias.get(low, app)}')
            else:
                subprocess.Popen(alias.get(low, app).split())
        except Exception as exc:
            return {"reply": f"No he podido abrir «{app}»: {exc}"}
        st, detail = await _verify_started(before, app)
        if st == "no":
            return {"reply": f"No encuentro «{app}» instalado (ni en el índice ni como app "
                             "conocida), así que no se ha abierto nada. Dime el nombre exacto o "
                             "«reindexa las aplicaciones»."}
        if st == "other":
            return {"reply": f"He lanzado algo ({detail}) pero no estoy seguro de que sea "
                             f"«{app}». Compruébalo, por favor."}
        if st == "yes":
            return {"reply": f"Listo, «{app}» está abierto. ✓"}
        return {"reply": f"Abriendo «{app}»…"}

    if intent == "screenshot":
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        out = SHOTS_DIR / f"captura-{dt.datetime.now():%Y%m%d-%H%M%S}.png"
        try:
            import mss
            with mss.mss() as sct:
                sct.shot(output=str(out))
            return {"reply": f"Captura guardada en data/captures/{out.name}. ✔"}
        except Exception:
            return {"reply": "Aún no puedo capturar la pantalla de verdad: instala mss "
                             "(pip install mss) y reinicia; la captura quedaría en "
                             "data/captures/ con fecha y hora."}

    if intent == "webcam":
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import cv2
            cam = cv2.VideoCapture(0)
            ok, frame = cam.read()
            cam.release()
            if ok:
                out = SHOTS_DIR / f"webcam-{dt.datetime.now():%Y%m%d-%H%M%S}.jpg"
                cv2.imwrite(str(out), frame)
                return {"reply": f"Foto tomada: data/captures/{out.name}. ✔"}
        except Exception:
            pass
        return {"reply": "No consigo abrir la webcam: instala opencv-python "
                         "(pip install opencv-python) y comprueba que ninguna otra app "
                         "la esté usando. La foto iría a data/captures/."}

    if intent in ("shutdown", "restart"):
        apagar = intent == "shutdown"
        verbo = "apagar" if apagar else "reiniciar"
        yo = "apago" if apagar else "reinicio"
        from backend.core.comun import confirm
        canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"
        abiertos = len(_proc_names()) if psutil is not None else 0
        cuantos = (f" Ahora mismo hay {abiertos} programa(s) distintos en marcha y "
                   "se cerrarán todos." if abiertos else "")

        def _ejecutar(_apagar=apagar):
            if sys.platform != "win32":
                return f"No sé {verbo} este sistema operativo, así que no he hecho nada."
            os.system("shutdown /s /t 15" if _apagar else "shutdown /r /t 15")
            return (f"{'Apagando' if _apagar else 'Reiniciando'} en 15 segundos. "
                    "Si te has arrepentido, aún puedes cancelarlo con: shutdown /a")

        await bus.emit("alert", {"level": "warn",
                                 "msg": f"{verbo.upper()} SOLICITADO — esperando confirmación"})
        pregunta = (f"⚠ Voy a {verbo} este equipo en 15 segundos desde que me digas que sí."
                    f"{cuantos} Lo que no esté guardado se pierde.\n"
                    f"¿Lo {yo}? Responde «sí» o «no» "
                    f"(o la frase exacta «confirmo {'apagado' if apagar else 'reinicio'}»).")
        return {"reply": confirm.request(
            channel=canal, kind=f"{verbo}_equipo", summary=pregunta,
            action=_ejecutar, request_text=text, targets=[{"host": platform.node()}],
            cancel_reply=f"Cancelado, no {yo} nada."),
            "data": {"confirm": True}}

    if intent in ("shutdown_confirm", "restart_confirm"):
        # si hubiera algo armado, el brain lo habría resuelto antes del router
        que = "apagado" if intent == "shutdown_confirm" else "reinicio"
        return {"reply": f"No hay ningún {que} pendiente de confirmar, así que no he hecho "
                         f"nada. Si lo quieres de verdad, dime «{'apaga' if que == 'apagado' else 'reinicia'} el pc»."}

    return {"reply": "Esa orden de sistema no la tengo mapeada. Puedo darte el estado del "
                     "equipo, temperaturas, procesos, abrir apps y webs, capturas, webcam, "
                     "y apagar o reiniciar (siempre con confirmación)."}
