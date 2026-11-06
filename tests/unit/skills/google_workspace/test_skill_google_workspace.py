# -*- coding: utf-8 -*-
"""Auditoría de la skill google_workspace: ¿se ACTIVA y hace lo que promete?

Esta suite existe porque la pregunta de una skill no es «¿está bien escrita?»
sino «¿llega la frase del usuario hasta ella?». Por eso NO prueba las regex
sueltas: enruta con el enrutador DE VERDAD (`skills_loader.load_skills()` +
`route()`), que recorre las carpetas por orden ALFABÉTICO y se queda con la
PRIMERA regex que case. Una regex perfecta a la que otra skill le roba la frase
antes es una regex que no existe.

REGLA ABSOLUTA: NI UNA llamada real a Google. Ningún test lee las credenciales
reales, ninguno abre el navegador, ninguno envía, crea ni borra nada. Sin
credenciales y sin red, esta suite pasa entera.

Lo de Drive lo cubre tests/unit/skills/google_workspace/test_drive.py (251 comprobaciones); aquí está lo que
faltaba: correo, calendario, tareas, las colisiones con `comms`/`files` y la
honestidad del error cuando falta una credencial.

Ejecutar: .venv\\Scripts\\python.exe tests\\test_skill_google_workspace.py
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.core.aplicacion import skills_loader  # noqa: E402

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


skills_loader.load_skills()
GW = skills_loader.get_skills()["google_workspace"].module
HANDLE_SRC = Path(ROOT, "skills", "google_workspace", "skill.py").read_text(encoding="utf-8")


def _ruta(frase):
    r = skills_loader.route(frase)
    return (r[0].folder, r[1]) if r else (None, None)


# ===================== 1. ¿SE ACTIVAN LOS 28 INTENTS? ========================
# Frases como las diría un usuario español, NO la regex leída al revés. Con
# «me»/«mi», plurales, con tilde y sin ella. Si una de estas se cae, la skill
# es inalcanzable por ahí y el usuario acaba en el planificador del cerebro,
# que es justo donde nexus se inventa cosas.
FRASES = {
    "open_email": ["abre el correo 2", "ábreme el mail 4",
                   "muéstrame el correo número 3", "léeme el correo 1"],
    "send_email": ["envía un correo a ana@ejemplo.com con asunto Hola diciendo que llego tarde",
                   "mándale un mail a ana@ejemplo.es diciendo que lo confirmo",
                   "escríbele un correo a pepe@ejemplo.com"],
    "create_event": ["crea un evento reunión con Ana el viernes a las 17:00",
                     "resérvame una cita con el dentista el martes",
                     "agéndame una reunión el jueves a las 10",
                     "añade al calendario la revisión del coche mañana"],
    "create_task": ["crea una tarea en el to-do: pagar al proveedor el viernes",
                    "añade una tarea a google tasks: llamar al banco",
                    "mete en la lista de google revisar el contrato"],
    "email_urgent": ["¿tengo correos urgentes?", "hay algo urgente en gmail",
                     "algo urgente en la bandeja", "¿hay correos que corran prisa?"],
    "email_actions": ["analiza los correos", "haz triaje de los correos",
                      "crea tareas de lo urgente", "gestióname la bandeja",
                      "conviérteme los correos en tareas"],
    "email_actions_pron": ["analízalos", "no los leas, analízalos", "procésalos",
                           "gestiónalos", "despáchalos"],
    "summarize_emails": ["resume mis correos", "resume el correo 2",
                         "hazme un resumen de la bandeja", "resúmeme los mails"],
    "mark_unread": ["marca el correo 2 como no leído", "ponlos como no leídos",
                    "déjalos sin leer", "devuélvelos a no leídos"],
    "mark_read": ["pon los correos como leídos", "márcalos como leídos",
                  "marca todo como leído", "ponme los mails como leidos"],
    "delete_email": ["borra el correo 3", "elimina los correos de Amazon",
                     "manda a la papelera los correos de más de 30 días",
                     "quita los correos antiguos"],
    "delete_event": ["cancela la reunión con el CTO", "borra el evento del jueves",
                     "anúlame la cita del dentista", "quita esa cita"],
    "edit_event": ["mueve la reunión al viernes a las 17",
                   "reprograma la cita del médico", "aplaza el evento al martes",
                   "pospón esa reunión"],
    "unread_from": ["de quién son los correos", "cuáles correos tengo",
                    "dime los remitentes", "quién me ha escrito"],
    "unread_count": ["cuántos correos tengo sin leer", "cuántos tengo sin leer",
                     "número de correos", "cuantos mails sin leer tengo"],
    "emails": ["lee mis correos", "échale un ojo a mis correos",
               "qué tengo en la bandeja", "revisa mi gmail",
               "consulta la bandeja de entrada", "qué correos tengo"],
    "gcal": ["qué tengo en el calendario", "qué tengo esta semana",
             "mira mi agenda", "qué citas tengo", "próximos eventos"],
    "gtasks": ["tareas de google", "qué tengo en el to-do", "google tasks",
               "qué hay en mi to-do"],
    "drive_folder_create": ["crea la carpeta Informes en drive",
                            "crea la carpeta Clientes/2026/agosto en drive"],
    "drive_move": ["mueve informe.md a la carpeta Clientes en drive",
                   "llévate el informe a la carpeta Clientes en drive"],
    "drive_rename": ["renombra informe.md a informe-final.md en drive",
                     "cámbiale el nombre a informe.md por informe-v2.md en drive"],
    "drive_delete": ["borra informe-viejo.md de drive",
                     "borra definitivamente informe-viejo.md de drive"],
    "drive_replace": ["actualiza informe-2026-08-02.md en drive",
                      "sobrescribe informe.md en drive"],
    "drive_download": ["descarga informe.md de drive", "bájame el contrato.pdf de drive"],
    "drive_search": ["busca contratos en drive",
                     "busca contratos en la carpeta Clientes de drive"],
    "drive_upload": ["sube el informe a drive", "sube informe-2026-08-02.md a drive",
                     "guárdame el informe en drive"],
    "drive_link": ["dame el enlace de drive", "cuál es el link de drive"],
    "drive_list": ["qué hay en mi drive", "qué hay en la carpeta Clientes de drive"],
}


def test_los_28_intents_del_skill_estan_todos_probados():
    declarados = set(GW.SKILL["patterns"])
    check(len(declarados) == 28, f"la skill declara {len(declarados)} intents, no 28")
    check(declarados == set(FRASES),
          f"intents sin frases de prueba: {sorted(declarados - set(FRASES))}; "
          f"frases de intents que ya no existen: {sorted(set(FRASES) - declarados)}")


def test_cada_intent_se_activa_con_frases_naturales():
    for intent, frases in FRASES.items():
        for frase in frases:
            folder, real = _ruta(frase)
            check(folder == "google_workspace" and real == intent,
                  f"«{frase}» → {folder}/{real} (se esperaba google_workspace/{intent})")


def test_ningun_intent_se_queda_sin_rama_en_handle():
    """Un patrón que enruta a un intent que handle() no conoce cae al final del
    try y devuelve «esa orden no la tengo mapeada»: enruta pero no hace nada."""
    for intent in GW.SKILL["patterns"]:
        check(f'intent == "{intent}"' in HANDLE_SRC,
              f"el intent «{intent}» enruta pero handle() no tiene rama para él")


# ============ 2. TILDES Y ENCLÍTICOS (el fallo que más se repite) ============
def test_el_pronombre_enclitico_desplaza_la_tilde_y_aun_asi_casa():
    """02/08/2026. En español el enclítico MUEVE la tilde: gestiona→gestiónalos,
    procesa→procésalos, despacha→despáchalos, deja→déjalos. Los patrones estaban
    escritos con el verbo sin tilde, así que estas frases —perfectamente normales—
    no casaban con NADA y acababan en el planificador del cerebro."""
    casos = {
        "procésalos": "email_actions_pron",
        "gestiónalos": "email_actions_pron",
        "despáchalos": "email_actions_pron",
        "analízamelos": "email_actions_pron",
        "gestióname la bandeja": "email_actions",
        "gestióname los correos": "email_actions",
        "organízame los correos": "email_actions",
        "déjalos sin leer": "mark_unread",
        "guárdame el informe en drive": "drive_upload",
        "llévate el informe a la carpeta Clientes en drive": "drive_move",
    }
    for frase, esperado in casos.items():
        folder, intent = _ruta(frase)
        check(folder == "google_workspace" and intent == esperado,
              f"«{frase}» → {folder}/{intent} (se esperaba {esperado})")


def test_un_sustantivo_entre_el_interrogativo_y_el_verbo_no_rompe_el_calendario():
    """«qué citas tengo» no casaba: el patrón exigía verbo→sustantivo («qué tengo
    ... citas») y nadie habla así siempre."""
    for frase in ("qué citas tengo", "qué eventos tengo", "tengo alguna cita",
                  "qué reuniones tengo"):
        folder, intent = _ruta(frase)
        check(folder == "google_workspace" and intent == "gcal",
              f"«{frase}» → {folder}/{intent} (se esperaba gcal)")


# ==================== 3. COLISIONES CON OTRAS SKILLS =========================
def test_la_bandeja_de_correo_es_de_gmail_y_la_unificada_es_de_comms():
    """INCIDENTE: skills/comms tenía `bandeja` a secas y va ANTES por orden
    alfabético, así que se quedaba «qué tengo en la bandeja» —ejemplo LITERAL del
    SKILL.md de Google— y respondía con tres mensajes DE MENTIRA escritos a fuego
    en su propio fichero. En español «bandeja (de entrada)» es el correo."""
    for frase in ("qué tengo en la bandeja", "consulta la bandeja de entrada",
                  "revisa la bandeja", "algo urgente en la bandeja",
                  "hazme un resumen de la bandeja"):
        folder, intent = _ruta(frase)
        check(folder == "google_workspace",
              f"«{frase}» se la ha llevado {folder}/{intent}; la bandeja es el correo")
    # y lo de comms sigue siendo de comms
    for frase, esperado in (("lee mis mensajes", "inbox"),
                            ("mi bandeja unificada", "inbox"),
                            ("muéstrame los mensajes de whatsapp", "inbox"),
                            ("tengo mensajes nuevos", "inbox")):
        folder, intent = _ruta(frase)
        check(folder == "comms" and intent == esperado,
              f"«{frase}» → {folder}/{intent}; se le ha robado a comms")


def test_no_le_roba_las_ordenes_de_ficheros_locales_ni_las_del_tablero():
    """La dirección contraria: google_workspace tampoco puede secuestrar lo local.
    `files` habla del disco del usuario; equivocarse ahí borra cosas de verdad."""
    ajenas = {
        "borra el archivo D:/tmp/x.txt": "files",
        "borra la carpeta pruebas": "files",
        "lee el archivo notas.txt": "files",
        "qué hay en la carpeta D:/tmp": "files",
        "qué tareas tengo": "tasks_board",
        "levanta el docker": "autoprovision",
        "guarda en el proyecto nexus que arreglé el bug": "engram",
    }
    for frase, esperado in ajenas.items():
        folder, intent = _ruta(frase)
        check(folder == esperado,
              f"«{frase}» → {folder}/{intent}; era de {esperado}")


def test_una_palabra_del_titulo_no_secuestra_la_orden():
    """El SUSTANTIVO QUE DICE EL OPERADOR manda sobre una palabra suelta del título.

    05/08/2026, medido: «borra la tarea CITA con el dentista de prueba» acababa en
    `google_workspace/delete_event` y contestaba «No encuentro ningún evento». La
    causa era el hueco comodín de 25 caracteres de la primera rama de
    `delete_event`: se tragaba « la tarea » y encontraba «cita» DENTRO DEL TÍTULO
    de una tarea del tablero. El operador había dicho «tarea», y esa palabra es la
    que manda.

    Las dos direcciones van juntas a propósito. Estrechar la rama del calendario
    sin vigilar lo que ya funcionaba es cambiar un fallo por otro, y la frase
    «elimina las dos tareas del calendario» es la trampa: dice «tareas» PERO
    también «calendario», y es de Google. La caza la SEGUNDA rama del mismo
    patrón, que va anclada a «calendario» y no se toca."""
    del_tablero = ("borra la tarea comprar folios",
                   "borra la tarea cita con el dentista",
                   "borra la tarea cita con el dentista de prueba",
                   "elimina la tarea de la reunión con el gestor")
    for frase in del_tablero:
        folder, intent = _ruta(frase)
        check((folder, intent) == ("tasks_board", "delete"),
              f"«{frase}» → {folder}/{intent}; el operador dijo «tarea», "
              "es del TABLERO, no del calendario")

    del_calendario = ("borra el evento Sonorama",
                      "cancela la reunión del jueves",
                      "elimina las dos tareas del calendario",
                      "anúlame la cita del dentista",
                      "quita esa cita")
    for frase in del_calendario:
        folder, intent = _ruta(frase)
        check((folder, intent) == ("google_workspace", "delete_event"),
              f"«{frase}» → {folder}/{intent}; esto es del CALENDARIO y se ha roto")


def test_el_candado_antidrive_de_files_no_tiene_huecos():
    """Los intents de `files` que pueden ver una frase de Drive tienen que llevar
    el lookahead _SIN_DRIVE. Se comprueba ENRUTANDO, que es como se descubrió que
    `search`, `versions` y `restore_file` seguían fuera del candado."""
    fsrc = Path(ROOT, "skills", "files", "skill.py").read_text(encoding="utf-8")
    check("_SIN_DRIVE" in fsrc, "se ha quitado el candado _SIN_DRIVE de skills/files")
    for intent in ("trash", "move", "copy", "rename", "mkdir", "explore",
                   "update", "summarize", "read", "search", "versions",
                   "restore_file"):
        check(f'"{intent}"' in fsrc.split("_INTENTS_QUE_CHOCAN_CON_DRIVE")[1][:400],
              f"el intent «{intent}» de files NO está en el candado anti-drive")
    for frase in ("busca contratos en la carpeta Clientes de drive",
                  "busca los pdf en la carpeta Legal de mi drive",
                  "borra la carpeta Informes de drive",
                  "mueve informe.md a la carpeta Clientes en drive",
                  "resume informe.md de drive"):
        folder, intent = _ruta(frase)
        check(folder == "google_workspace",
              f"«{frase}» se la ha llevado {folder}/{intent}: eso toca el DISCO LOCAL")


# ================= 4. HONESTIDAD DEL ERROR (sin credenciales) ================
class _Ajustes:
    def __init__(self, secretos=None):
        self._s = secretos or {}

    def secret(self, k, d=""):
        return self._s.get(k, d)

    def get(self, k, d=None):
        return d


def _ctx(secretos=None):
    return {"settings": _Ajustes(secretos), "channel": "pc"}


class _Aparte:
    """Aparta CREDS_FILE/TOKEN_FILE del módulo a un temporal. Ningún test puede
    leer —ni de casualidad— las credenciales reales del usuario."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="nexus_gw_test_")
        self.old = (GW.CREDS_FILE, GW.TOKEN_FILE)
        GW.CREDS_FILE = Path(self.tmp, "google_credentials.json")
        GW.TOKEN_FILE = Path(self.tmp, "google_token.json")
        return self

    def con_credenciales(self):
        GW.CREDS_FILE.write_text(json.dumps(
            {"installed": {"client_id": "prueba", "client_secret": "prueba"}}),
            encoding="utf-8")

    def __exit__(self, *a):
        GW.CREDS_FILE, GW.TOKEN_FILE = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def test_sin_librerias_dice_QUE_falta_y_COMO_se_instala():
    salvado = sys.modules.get("googleapiclient", "no-estaba")
    sys.modules["googleapiclient"] = None            # así `import` lanza ImportError
    try:
        r = asyncio.run(GW.handle("unread_count", "cuántos correos sin leer",
                                  None, _ctx()))
    finally:
        if salvado == "no-estaba":
            sys.modules.pop("googleapiclient", None)
        else:
            sys.modules["googleapiclient"] = salvado
    txt = r["reply"]
    check("librer" in txt.lower(), f"no dice que faltan las librerías: {txt[:120]}")
    check("pip install google-api-python-client" in txt,
          "no dice el comando exacto para arreglarlo")
    check("credencial" in txt.lower(),
          "no distingue «faltan librerías» de «faltan credenciales»; el usuario "
          "se pone a reconfigurar Google para nada")


def test_sin_credenciales_dice_QUE_falta_y_COMO_se_arregla():
    with _Aparte():
        r = asyncio.run(GW.handle("emails", "lee mis correos", None, _ctx()))
    txt = r["reply"]
    check("Traceback" not in txt, "suelta un traceback en vez de explicarse")
    check("console.cloud.google.com" in txt, "no dice DÓNDE se arregla")
    check("escritorio" in txt.lower(),
          "no avisa de que el cliente OAuth tiene que ser «App de escritorio»; "
          "es el error que más tiempo ha costado")
    check("Client ID" in txt and "⚙" in txt,
          "no dice que basta con pegar el Client ID en la rueda de ajustes")


def test_un_fallo_de_google_no_se_traga_ni_se_disfraza():
    """Si Google (o la red) falla, se dice QUÉ falló y qué probar. Callarlo o
    devolver «no tienes correos» sería mentir sobre algo que no se ha mirado."""
    with _Aparte() as ap:
        ap.con_credenciales()
        original = GW._count_unread
        GW._count_unread = lambda: (_ for _ in ()).throw(RuntimeError("la red se cayó"))
        try:
            r = asyncio.run(GW.handle("unread_count", "cuántos correos sin leer",
                                      None, _ctx()))
        finally:
            GW._count_unread = original
    txt = r["reply"]
    check("Traceback" not in txt, "suelta un traceback")
    check("la red se cayó" in txt, f"se traga el motivo real del fallo: {txt[:150]}")
    check("google_token.json" in txt, "no dice qué probar")


def test_el_fallo_de_permisos_de_drive_no_manda_a_arreglar_el_redirect():
    """Un token viejo sin el scope de Drive contesta 403/insufficient. Antes se
    colaba por la rama de «acceso bloqueado» y mandaba a tocar las URIs de
    redirección, que NO era lo que estaba roto. Un mensaje que manda a arreglar
    lo que funciona es peor que ninguno."""
    with _Aparte() as ap:
        ap.con_credenciales()
        original = GW._drive_service
        GW._drive_service = lambda: (_ for _ in ()).throw(
            RuntimeError("403 Request had insufficient authentication scopes"))
        try:
            r = asyncio.run(GW.handle("drive_list", "qué hay en mi drive", None, _ctx()))
        finally:
            GW._drive_service = original
    txt = r["reply"]
    check("auth/drive" in txt, "no dice qué permiso concreto falta")
    check("google_token.json" in txt, "no dice cómo se rehace la autorización")
    check("redirect" not in txt.lower(),
          "manda a arreglar el redirect_uri, que no es lo que está roto")


# ============ 5. SALVAGUARDAS: lo destructivo sigue siendo reversible ========
def test_borrar_un_correo_es_mandarlo_a_la_papelera_nunca_borrarlo():
    check(".trash(" in HANDLE_SRC,
          "el borrado de correos ya no usa messages().trash: si ha pasado a "
          "delete, deja de ser recuperable a los 30 días")
    check("messages().delete(" not in HANDLE_SRC and "messages().batchDelete(" not in HANDLE_SRC,
          "hay un borrado PERMANENTE de Gmail en la skill; el SKILL.md promete "
          "papelera («recuperables 30 días, nunca borrado permanente»)")


def test_borrar_los_correos_de_un_remitente_no_corta_el_dominio():
    """El mismo fallo del punto que rompía los nombres de fichero en Drive, pero
    en Gmail: el hueco excluía el «.», así que «borra los correos de
    facturacion@empresa.com» buscaba «from:facturacion@empresa». Se comprueba QUÉ
    consulta se le pide a Gmail; nada se borra de verdad."""
    pedido = {}

    def _falso_buscar(q, limite=25):
        pedido["q"] = q
        return ["fingido-1"]

    with _Aparte() as ap:
        ap.con_credenciales()
        originales = (GW._search_email_ids, GW._trash_emails)
        GW._search_email_ids, GW._trash_emails = _falso_buscar, (lambda ids: len(ids))
        try:
            frase = "borra los correos de facturacion@empresa.com"
            r = skills_loader.route(frase)
            check(r is not None and r[1] == "delete_email", f"«{frase}» no enruta a delete_email")
            asyncio.run(GW.handle("delete_email", frase, r[2], _ctx()))
        finally:
            GW._search_email_ids, GW._trash_emails = originales
    check(pedido.get("q") == "from:facturacion@empresa.com",
          f"se le pide a Gmail «{pedido.get('q')}»: el dominio va cortado")


def test_el_borrado_definitivo_de_drive_sigue_detras_de_confirm_request():
    """La salvaguarda que impide que una frase mal casada se lleve documentos
    reales. Con `auth/drive` completo esto apunta al Drive entero del usuario."""
    tras_handle = HANDLE_SRC.split("async def handle(")[1]
    check(tras_handle.count("_drive_destruir(") == 1,
          "hay más de una llamada a _drive_destruir dentro de handle()")
    rama = tras_handle.split('intent == "drive_delete"')[1].split('intent == "drive_upload"')[0]
    antes_de_destruir = rama.split("_drive_destruir(")[0]
    check("confirm.request(" in rama,
          "el borrado de Drive ya no pasa por confirm.request()")
    check("def _ejecutar" in antes_de_destruir,
          "_drive_destruir se llama fuera del `action` del confirm.request")
    check("_drive_a_papelera" in rama,
          "el camino por defecto ya no es la papelera de Drive")


def test_el_scope_de_drive_sigue_documentado_con_su_fecha_y_su_precio():
    """No se toca el scope sin dejar escrito por qué. El aviso al usuario tiene
    que seguir en el SKILL.md: puede borrar CUALQUIER documento de la cuenta."""
    check("https://www.googleapis.com/auth/drive" in HANDLE_SRC,
          "ha desaparecido el scope de Drive de la lista de SCOPES")
    check("02/08/2026" in HANDLE_SRC, "el scope completo está sin fechar")
    doc = Path(ROOT, "skills", "google_workspace", "SKILL.md").read_text(encoding="utf-8")
    check("auth/drive" in doc and "borrar cualquier documento" in doc.lower(),
          "el SKILL.md ya no avisa de lo que implica el permiso completo")


# ====== 6. ENVIAR CORREO: VISTA PREVIA, CONFIRMACIÓN E IDEMPOTENCIA (SEC-05) ==
# Hallazgo SEC-05 / fila P1-4 del roadmap: «envía un correo» parseaba el
# destinatario, dejaba que el MODELO redactara el cuerpo cuando no se lo dictabas
# y llamaba a _send_gmail en la misma respiración. Nadie veía el correo antes de
# que saliera, y la misma orden dos veces mandaba dos correos. El borrado de
# eventos y de Drive sí pasaban por confirm.request: la asimetría era el fallo.
#
# Contrato nuevo: el correo se ARMA (se enseña tal cual: para, asunto y cuerpo),
# solo sale con un «sí», y la huella del envío impide que se repita.
from backend.core.comun import confirm as _confirm   # noqa: E402

_ORDEN = "envía un correo a ana@ejemplo.com con asunto Hola diciendo que llego tarde"
_ORDEN_MANANA = ("envía un correo a ana@ejemplo.com con asunto Hola diciendo "
                 "que llego mañana")
_ORDEN_A_PEPE = ("envía un correo a pepe@ejemplo.com con asunto Hola diciendo "
                 "que llego tarde")


class _Reloj:
    """Reloj de mentira: la ventana de idempotencia se prueba moviendo la hora,
    nunca durmiendo (una prueba que duerme 5 minutos no se ejecuta)."""

    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def time(self):
        return self.t


class _Envio:
    """Doble de _send_gmail + confirmación limpia. De este equipo no sale nada:
    _send_gmail se sustituye y _llm_text nunca llama a un modelo."""

    def __init__(self):
        self.enviados = []
        self.auditorias = []
        self._previos = {}

    def __enter__(self):
        self._previos = {"audit": _confirm._audit, "send": GW._send_gmail,
                         "llm": GW._llm_text, "time": _confirm.time}
        _confirm.clear()
        _confirm.olvidar_envios()
        _confirm._audit = lambda **kw: self.auditorias.append(kw)
        GW._send_gmail = self._anotar
        GW._llm_text = self._sin_modelo
        self._aparte = _Aparte().__enter__()
        self._aparte.con_credenciales()
        return self

    def _anotar(self, to, subject, body):
        self.enviados.append({"to": to, "subject": subject, "body": body})
        return "id-falso"

    @staticmethod
    async def _sin_modelo(order):
        return ""

    def con_modelo(self, texto):
        """Lo que contestaría el cerebro al pedirle el cuerpo del correo."""
        async def _falso(order):
            return texto
        GW._llm_text = _falso

    def reloj(self, t=1_800_000_000.0):
        self._reloj = _Reloj(t)
        _confirm.time = self._reloj
        return self._reloj

    def enviar(self, frase=_ORDEN, ctx=None):
        r = skills_loader.route(frase)
        assert r is not None and r[1] == "send_email", f"«{frase}» no enruta a send_email"
        return asyncio.run(GW.handle("send_email", frase, r[2], ctx or _ctx()))["reply"]

    def directo(self, frase, ctx=None):
        """handle() sin pasar por el enrutador (frases incompletas a propósito)."""
        return asyncio.run(GW.handle("send_email", frase, None, ctx or _ctx()))["reply"]

    def responder(self, texto, canal="pc"):
        return asyncio.run(_confirm.answer(texto, canal))

    def __exit__(self, *a):
        GW._send_gmail = self._previos["send"]
        GW._llm_text = self._previos["llm"]
        _confirm._audit = self._previos["audit"]
        _confirm.time = self._previos["time"]
        _confirm.clear()
        _confirm.olvidar_envios()
        self._aparte.__exit__(*a)
        return False


def test_un_correo_no_sale_hasta_decir_que_si():
    with _Envio() as e:
        pregunta = e.enviar()
        check(e.enviados == [], f"ha enviado ANTES de preguntar: {e.enviados!r}")
        check("ana@ejemplo.com" in pregunta, "la pregunta no dice A QUIÉN va el correo")
        check("Hola" in pregunta, "la pregunta no dice el ASUNTO")
        check("llego tarde" in pregunta,
              "la pregunta no enseña el CUERPO que va a salir (lo que se envía se ve)")
        pend = _confirm.pending("pc")
        check(pend is not None and pend["kind"] == "envio_correo",
              "no ha quedado armada una confirmación de envío de correo")
        check(pend is not None and pend["destructive"] is False,
              "un envío no es destructivo: confirm.request debe recibir destructive=False")


def test_decir_que_si_envia_una_sola_vez_exactamente_lo_que_ensena():
    with _Envio() as e:
        e.enviar()
        respuesta = e.responder("sí") or ""
        check(len(e.enviados) == 1,
              f"confirmar debía enviar UNA vez, envió {len(e.enviados)}")
        if e.enviados:
            env = e.enviados[0]
            check(env["to"] == "ana@ejemplo.com" and env["subject"] == "Hola"
                  and env["body"] == "llego tarde",
                  f"ha enviado algo distinto de lo que enseñó: {env!r}")
        check("ana@ejemplo.com" in respuesta,
              f"la respuesta no dice a quién se ha enviado: {respuesta!r}")
        check(_confirm.pending("pc") is None,
              "la confirmación sigue armada después del «sí»")


def test_decir_que_no_no_envia_nada_y_lo_dice_sin_adornos():
    with _Envio() as e:
        e.enviar()
        respuesta = (e.responder("no") or "").lower()
        check(e.enviados == [], "ha enviado algo después de un «no»")
        check("no he enviado nada" in respuesta,
              f"al cancelar no dice la verdad (no he enviado nada): {respuesta!r}")


def test_cambiar_de_tema_desa_rma_el_envio_y_no_manda_nada():
    with _Envio() as e:
        e.enviar()
        respuesta = e.responder("hablamos de otra cosa luego")
        check(respuesta is None, f"una frase que no es sí/no debía devolver None: {respuesta!r}")
        check(_confirm.pending("pc") is None,
              "la confirmación sigue armada tras cambiar de tema: dispararía más tarde")
        check(e.enviados == [], "ha enviado algo al desarmar la confirmación")


def test_la_misma_orden_dos_veces_no_manda_dos_correos():
    with _Envio() as e:
        e.enviar()
        e.responder("sí")
        segunda = e.enviar()
        check(len(e.enviados) == 1,
              f"el mismo correo ha salido {len(e.enviados)} veces")
        check("ana@ejemplo.com" in segunda and "ya ha salido" in segunda.lower(),
              f"la segunda vez no dice que ya había salido: {segunda!r}")
        check(_confirm.pending("pc") is None,
              "ha armado otra confirmación para un envío que ya había salido")
        acciones = [str(a.get("action", "")) for a in e.auditorias]
        check(any(a.startswith("envio_aceptado") for a in acciones),
              f"el envío aceptado no queda en la auditoría: {acciones!r}")
        check(any(a.startswith("envio_duplicado") for a in acciones),
              f"el duplicado rechazado no queda en la auditoría: {acciones!r}")


def test_el_mismo_destinatario_con_otro_cuerpo_si_sale():
    with _Envio() as e:
        e.enviar()
        e.responder("sí")
        e.enviar(_ORDEN_MANANA)
        e.responder("sí")
        check([x["body"] for x in e.enviados] == ["llego tarde", "llego mañana"],
              f"otro cuerpo es otro correo y debe salir: {e.enviados!r}")


def test_otro_destinatario_no_se_confunde_con_el_anterior():
    with _Envio() as e:
        e.enviar()
        e.responder("sí")
        e.enviar(_ORDEN_A_PEPE)
        check(len(e.enviados) == 1 and _confirm.pending("pc") is not None,
              "otro destinatario con el mismo texto debe volver a preguntar")
        e.responder("sí")
        check([x["to"] for x in e.enviados] == ["ana@ejemplo.com", "pepe@ejemplo.com"],
              f"el segundo destinatario no ha recibido su correo: {e.enviados!r}")


def test_pasada_la_ventana_el_mismo_correo_vuelve_a_salir():
    with _Envio() as e:
        reloj = e.reloj()
        ventana = _confirm.umbrales_envios()["ventana_idempotencia_seg"]
        check(ventana > 0, "la ventana de idempotencia no está configurada")
        e.enviar()
        e.responder("sí")
        reloj.t += ventana + 1
        e.enviar()
        e.responder("sí")
        check(len(e.enviados) == 2,
              f"fuera de la ventana el mismo correo debe volver a salir: {len(e.enviados)}")


def test_el_cuerpo_redactado_por_nexus_se_dice_en_la_pregunta():
    with _Envio() as e:
        e.con_modelo("Hola Ana, te confirmo la reunión del jueves. Un saludo.")
        pregunta = e.enviar("escríbele un correo a ana@ejemplo.com")
        check(e.enviados == [],
              "ha enviado sin preguntar cuando el cuerpo lo puso el modelo")
        check("redactado por nexus" in pregunta.lower(),
              f"no avisa de que el cuerpo lo escribió nexus: {pregunta[:200]!r}")
        check("te confirmo la reunión del jueves" in pregunta,
              "la pregunta no enseña el texto que ha escrito el modelo")


def test_un_cuerpo_largo_se_recorta_con_puntos_suspensivos_no_se_resume():
    with _Envio() as e:
        largo = " ".join(f"frase numero {i}" for i in range(300))
        pregunta = e.enviar("envía un correo a ana@ejemplo.com con asunto Hola "
                            f"diciendo {largo}")
        check("…" in pregunta,
              "recorta el cuerpo sin marcar el corte: parece que el correo es más corto")
        check("frase numero 299" not in pregunta, "no ha recortado nada")
        check("frase numero 0 " in pregunta,
              "el recorte no empieza por el texto de verdad (¿lo ha parafraseado?)")
        check(len(pregunta) < len(largo),
              "la pregunta es más larga que el cuerpo: no ha recortado")


def test_si_google_falla_la_respuesta_no_dice_que_se_envio():
    with _Envio() as e:
        def _rompe(to, subject, body):
            raise RuntimeError("el buzón rechazó el mensaje")
        GW._send_gmail = _rompe
        e.enviar()
        respuesta = (e.responder("sí") or "")
        txt = respuesta.lower()
        check("ha fallado" in txt, f"no dice que ha fallado: {respuesta!r}")
        check("el buzón rechazó el mensaje" in txt, f"se traga el motivo real: {respuesta!r}")
        check("enviado a ana" not in txt,
              f"da por enviado un correo que ha fallado: {respuesta!r}")
        acciones = [str(a.get("action", "")) for a in e.auditorias]
        check(not any(a.startswith("envio_aceptado") for a in acciones),
              "marca como enviado un correo que falló: el reintento quedaría bloqueado")


def test_sin_direccion_pide_la_direccion_y_no_arma_ningun_envio():
    with _Envio() as e:
        r = e.directo("envía un correo diciendo que llego tarde")
        check("dirección" in r.lower(), f"no pide la dirección: {r!r}")
        check(_confirm.pending("pc") is None, "ha armado un envío sin destinatario")
        check(e.enviados == [], "ha enviado un correo sin destinatario")


def test_sin_cuerpo_y_sin_modelo_pide_el_texto_y_no_arma_nada():
    with _Envio() as e:
        r = e.directo("envía un correo a ana@ejemplo.com")
        check("diciendo" in r.lower(), f"no pide el texto del correo: {r!r}")
        check(_confirm.pending("pc") is None, "ha armado un envío sin cuerpo")
        check(e.enviados == [], "ha enviado un correo vacío")


def test_el_correo_solo_sale_desde_dentro_de_la_confirmacion():
    """La salvaguarda en el código: _send_gmail NO puede llamarse en la rama, ni
    antes del `action`. Y el atajo de «no me preguntes» (que existe para borrar
    lo que va a la papelera) NO se extiende a los envíos: un correo siempre se
    pregunta."""
    rama = HANDLE_SRC.split('intent == "send_email"')[1].split('intent == "summarize_emails"')[0]
    check("_send_gmail(" not in rama,
          "la rama de send_email llama a _send_gmail directamente, fuera del action")
    check("_envio_correo_confirmado(" in rama,
          "la rama de send_email ya no arma el envío con la acción diferida")
    check("_SIN_PREGUNTAR_RX" not in rama,
          "el atajo de «no me preguntes» se ha colado en los ENVÍOS: un correo "
          "siempre se confirma")
    check("_SIN_PREGUNTAR_RX.search(text)" in HANDLE_SRC,
          "se ha quitado el atajo de borrado sin preguntar, que sí era válido "
          "(todo lo que borra va a la papelera)")
    cuerpo = HANDLE_SRC.split("def _envio_correo_confirmado(")[1].split("\nasync def handle(")[0]
    antes_de_enviar = cuerpo.split("async def _enviar(")[0]
    check("async def _enviar(" in cuerpo and "confirm.request(" in cuerpo,
          "el envío de correo ya no se arma con una acción diferida")
    check("_send_gmail(" not in antes_de_enviar,
          "_send_gmail se llama antes del action del confirm.request")


# ====== 6b. TRIAJE DE CORREO: PROPONE Y ESPERA UN «SÍ» (SEC-07 / P2-3) ======
# Hallazgo SEC-07: el cuerpo del correo entra en el MISMO prompt de clasificación que
# la orden del operador, y la creación (Google Tasks/Calendar + tablero) se hacía sin
# enseñar nada. Contrato: la orden produce una propuesta, el «sí» la crea, y la
# creación NO se puede llamar desde ningún otro sitio.
def _trozo(src, ini, fin):
    """El texto entre `ini` y `fin`; "" si el punto de partida ya no existe (una
    prueba estructural tiene que DECIR que falta, no reventar con un IndexError)."""
    if ini not in src:
        return ""
    resto = src.split(ini, 1)[1]
    return resto.split(fin, 1)[0] if fin in resto else resto


def test_el_triaje_de_correo_propone_y_solo_crea_dentro_de_la_confirmacion():
    """La salvaguarda en el código: `_email_actions_job` (lo que se ejecuta al pedirlo)
    no puede crear nada, y `_crear_items_correo` no puede llamarse fuera del `action`
    de `confirm.request`. Si alguien vuelve a meter la creación en el job «para que sea
    más rápido», esto se pone rojo."""
    rama = _trozo(HANDLE_SRC, 'if intent == "email_actions":', 'if intent == "create_event"')
    check(bool(rama), "no encuentro la rama de email_actions en handle()")
    check("_create_everywhere" not in rama and "add_to_group" not in rama,
          "la rama de email_actions crea tareas/eventos directamente")
    check("_email_actions_job(" in rama, "la rama de email_actions ya no encola el triaje")
    check("_SIN_PREGUNTAR_RX" not in rama,
          "el atajo de «no me preguntes» se ha colado en el triaje de correo")
    job = _trozo(HANDLE_SRC, "async def _email_actions_job(", "\ndef _parse_json_array")
    check(bool(job), "no encuentro _email_actions_job en la skill")
    check("_create_everywhere" not in job and "add_to_group" not in job,
          "_email_actions_job escribe: la creación tiene que vivir en el action del confirm")
    check("confirm.request(" not in job and "_propuesta_correo(" in job,
          "el job no arma la propuesta por confirm.request")
    prop = _trozo(HANDLE_SRC, "def _propuesta_correo(", "\nasync def _crear_items_correo(")
    check(bool(prop), "no existe _propuesta_correo: el triaje no propone nada")
    check("confirm.request(" in prop and "_KIND_CREACION_CORREO" in prop
          and "destructive=False" in prop,
          "la propuesta no se arma con confirm.request(kind=creacion_desde_correo, destructive=False)")
    check("async def _crear(" in prop, "la propuesta no aplaza la creación en un action")
    antes_del_action = prop.split("async def _crear(")[0] if "async def _crear(" in prop else prop
    check("_crear_items_correo(" not in antes_del_action,
          "se llama a la creación ANTES del action: un «no» crearía igual")
    cuerpo = _trozo(HANDLE_SRC, "async def _crear_items_correo(",
                    "\nasync def _email_actions_job(")
    check(bool(cuerpo), "no existe _crear_items_correo: la creación no tiene un único dueño")
    check("_create_everywhere," in cuerpo and "add_to_group," in cuerpo,
          "el action de la propuesta ya no es el único que escribe")
    # Y la prueba por conteo: un solo sitio llama a cada escritor.
    for escritor in ("_create_everywhere", "add_to_group"):
        usos = [ln for ln in HANDLE_SRC.splitlines()
                if escritor in ln and not ln.lstrip().startswith("def ")]
        check(len(usos) == 1, f"{escritor} se llama desde {len(usos)} sitios, no desde uno: {usos}")


def test_el_triaje_de_correo_no_lo_dispara_una_frase_de_solo_leer():
    """«revisa mi correo y crea tareas» NO entra por el triaje: enruta a `emails`, que
    solo lista y no crea nada. Es el comportamiento de hoy y se fija aquí para que
    nadie ensanche la regex del triaje sin darse cuenta de lo que arrastra (el correo
    que se lee se convierte en tareas de Google). El triaje se pide con las frases de
    FRASES["email_actions"]."""
    for frase in ("revisa mi correo y crea tareas", "revisa mi correo"):
        folder, intent = _ruta(frase)
        check((folder, intent) == ("google_workspace", "emails"),
              f"«{frase}» → {folder}/{intent}; solo leer no debe llegar al triaje")
    for frase in ("analiza los correos", "haz triaje de los correos",
                  "crea tareas de lo urgente", "gestióname la bandeja"):
        folder, intent = _ruta(frase)
        check((folder, intent) == ("google_workspace", "email_actions"),
              f"«{frase}» → {folder}/{intent}; el triaje se ha quedado inalcanzable")


# =============================== runner =====================================
if __name__ == "__main__":
    for name, t in sorted(globals().items()):
        if name.startswith("test_") and callable(t):
            print(f"-- {t.__name__}")
            try:
                t()
            except Exception as exc:                          # noqa: BLE001
                _fail.append(f"{t.__name__}: EXCEPCIÓN {type(exc).__name__}: {exc}")
                print("  EXCEPCIÓN:", exc)
    print(f"\n{_pass} OK, {len(_fail)} fallo(s)")
    if _fail:
        for f in _fail:
            print(" -", f)
        sys.exit(1)
    sys.exit(0)
