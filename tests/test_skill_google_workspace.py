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

Lo de Drive lo cubre tests/test_drive.py (251 comprobaciones); aquí está lo que
faltaba: correo, calendario, tareas, las colisiones con `comms`/`files` y la
honestidad del error cuando falta una credencial.

Ejecutar: .venv\\Scripts\\python.exe tests\\test_skill_google_workspace.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.core import skills_loader          # noqa: E402

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
    "send_email": ["envía un correo a ruben@ejemplo.com con asunto Hola diciendo que llego tarde",
                   "mándale un mail a ana@ejemplo.es diciendo que lo confirmo",
                   "escríbele un correo a pepe@ejemplo.com"],
    "create_event": ["crea un evento reunión con Rubén el viernes a las 17:00",
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
    `files` habla del disco de Adrian; equivocarse ahí borra cosas de verdad."""
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
    leer —ni de casualidad— las credenciales reales de Adrian."""

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
    reales. Con `auth/drive` completo esto apunta al Drive entero de Adrian."""
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
