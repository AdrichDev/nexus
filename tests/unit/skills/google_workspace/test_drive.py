# -*- coding: utf-8 -*-
"""Google Drive en nexus — scope, carpeta configurable, routing y honestidad.

REGLA ABSOLUTA DE ESTE FICHERO: NI UNA llamada real a Google. Ningún test lee
config/google_credentials.json ni google_token.json, ninguno abre el navegador y
NINGUNO sube nada al Drive de nadie. Todo va con dobles: `_FakeDrive` imita lo
justo de la API v3 (files().list/create) para comprobar QUE SE PIDE LO QUE SE
DEBE PEDIR. Sin credenciales y sin red, esta suite pasa entera.

El test que más vale es `test_el_scope_es_drive_file_y_no_el_drive_entero`: está
puesto para que nadie amplíe permisos «de paso» sin que salte algo en rojo.

Ejecutar: .venv\\Scripts\\python.exe tests\\test_drive.py
"""
import asyncio
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# SEC-19: la skill consulta los permisos DE VERDAD (backend.core.comun.permissions),
# que deciden con `settings` y con las carpetas CONFIG_DIR / perfil del usuario.
# Esta suite no puede mirar —ni para leer ni para decidir— la configuración ni el
# perfil del operador, así que se apuntan a carpetas de usar y tirar ANTES de
# cargar la skill: el backend lee estas variables al importarse, y un import
# perezoso llegaría tarde (misma razón que el comentario de arriba de la skill).
# Se borran solas al terminar el proceso.
_TMP_CFG = tempfile.TemporaryDirectory(prefix="nexus_drive_cfg_")
_TMP_DATA = tempfile.TemporaryDirectory(prefix="nexus_drive_data_")
_TMP_HOME = tempfile.TemporaryDirectory(prefix="nexus_drive_home_")
os.environ["NEXUS_CONFIG_DIR"] = _TMP_CFG.name
# T39b: la skill lee umbrales.json de NEXUS_CONFIG_DIR; la caja lleva la
# copia versionada para que la sección 2 compare con lo que la skill lee de
# verdad y no con la carpeta de reserva.
import shutil as _shutil  # noqa: E402
_shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..",
                          "config", "umbrales.json"), _TMP_CFG.name)
os.environ["NEXUS_DATA_DIR"] = _TMP_DATA.name
os.environ["USERPROFILE"] = _TMP_HOME.name
os.environ["HOME"] = _TMP_HOME.name
os.environ["APPDATA"] = os.path.join(_TMP_HOME.name, "AppData", "Roaming")
os.environ["LOCALAPPDATA"] = os.path.join(_TMP_HOME.name, "AppData", "Local")
for _var in ("OneDrive", "OneDriveConsumer"):
    os.environ.pop(_var, None)

_fail, _pass = [], 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def _load_skill(folder):
    """Carga skills/<folder>/skill.py del disco stubbeando lo que falte, para no
    arrastrar medio backend solo por leer unos patterns."""
    path = os.path.join(ROOT, "skills", folder, "skill.py")
    for _ in range(20):
        spec = importlib.util.spec_from_file_location(f"_sk_{folder}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return mod
        except ModuleNotFoundError as exc:
            if not exc.name:
                raise
            m = types.ModuleType(exc.name)
            m.__getattr__ = lambda _n: types.SimpleNamespace()
            sys.modules[exc.name] = m
    raise RuntimeError(f"no se pudo cargar skills/{folder}/skill.py")


gw = _load_skill("google_workspace")
SRC = Path(ROOT, "skills", "google_workspace", "skill.py").read_text(encoding="utf-8")


# ============================ 1. SCOPE ======================================
# ⚠️ ESTE TEST HA CAMBIADO DE BANDO. HISTORIA, PORQUE IMPORTA:
#
# Nació el 01/08/2026 llamándose `test_el_scope_es_drive_file_y_no_el_drive_entero`
# y hacía justo lo contrario de lo que hace ahora: EXIGÍA `drive.file` (solo los
# ficheros que crea nexus) y PROHIBÍA `auth/drive`. Era una barrera puesta a
# propósito para que nadie ampliara permisos «de paso».
#
# El 02/08/2026 el dueño de la cuenta la retiró él mismo, a sabiendas y por
# escrito: «tiene que tener la posibilidad de tener acceso a todo el drive si se
# le pide o a carpetas específicas y ha de poder hacer CRUD tanto de archivos
# como carpetas en ese drive. Ha de tener control total.» Con `drive.file` eso es
# imposible: una carpeta que él creó a mano NO EXISTE para nexus.
#
# LO QUE SE COMPRA CON ESE PERMISO: nexus puede leer, modificar, mover, renombrar
# y borrar CUALQUIER documento de la cuenta (nóminas, contratos, fotos), no solo
# los suyos. Y llega ahí por una regex.
# LO QUE SE PAGA A CAMBIO, y por eso el test no se borró sino que se dio la
# vuelta: ahora la barrera está donde de verdad hace falta — en lo destructivo
# (bloque 7 de este fichero). Si algún día se quiere volver a `drive.file`, esto
# se pone rojo y obliga a leer este comentario antes de tocar nada.
def test_el_scope_es_el_drive_completo_decision_del_02_08_2026():
    """El scope es `auth/drive` COMPLETO por decisión explícita e informada del
    dueño de la cuenta el 02/08/2026 (ver el comentario de arriba). No es un
    descuido: es lo único que permite el «control total» que se pidió."""
    scopes = list(gw.SCOPES)
    check("https://www.googleapis.com/auth/drive" in scopes,
          "FALTA el scope 'auth/drive' COMPLETO. Se amplió el 02/08/2026 a "
          "petición explícita del dueño de la cuenta: sin él no hay CRUD sobre "
          "carpetas que no haya creado nexus. Si lo has vuelto a bajar a "
          "drive.file, lee el comentario de este bloque antes de seguir.")
    check("https://www.googleapis.com/auth/drive.readonly" not in scopes,
          "SE HA COLADO drive.readonly: sobra (auth/drive ya lo incluye) y "
          "encima sugiere que esto es de solo lectura, que no lo es.")
    for p in ("drive.metadata", "drive.appdata", "drive.scripts", "drive.photos.readonly"):
        check(f"https://www.googleapis.com/auth/{p}" not in scopes,
              f"scope {p} añadido sin que haga falta: auth/drive ya lo cubre")
    check(len([s for s in scopes if "/drive" in s]) == 1,
          "hay más de un scope de Drive; con auth/drive sobra todo lo demás, "
          "incluido el drive.file que había antes (pedir los dos no suma nada)")
    # ampliar a Drive no puede dejar sin permisos a lo que ya funcionaba
    for s in ("gmail.modify", "gmail.send", "calendar.events", "tasks"):
        check(f"https://www.googleapis.com/auth/{s}" in gw.SCOPES,
              f"se ha perdido el scope {s} al ampliar Drive")
    # Una decisión de este calibre sin motivo escrito AL LADO se revierte sola en
    # seis meses. El código tiene que contar la fecha, quién y a qué precio.
    i = SRC.index("auth/drive\"")
    contexto = SRC[i:i + 2600]
    check("02/08/2026" in contexto,
          "el comentario junto a SCOPES no dice la FECHA de la decisión")
    check("DECISIÓN DEL" in contexto.upper() or "DECISION DEL" in contexto.upper(),
          "el comentario junto a SCOPES no deja claro que es una decisión tomada")
    for palabra in ("BORRAR", "PAPELERA", "confirm.request"):
        check(palabra in contexto,
              f"el comentario junto a SCOPES no explica el precio: falta «{palabra}» "
              "(qué puede destruir ahora nexus y qué lo frena)")


# ====================== 2. CARPETA DESDE umbrales.json ======================
def test_la_carpeta_sale_de_umbrales_y_no_esta_a_fuego():
    real = gw._umbrales_drive()
    check(isinstance(real.get("carpeta"), str) and real["carpeta"].strip(),
          "_umbrales_drive() no devuelve un nombre de carpeta usable")
    datos = json.loads(Path(ROOT, "config", "umbrales.json").read_text(encoding="utf-8"))
    check("drive" in datos, "config/umbrales.json no tiene sección 'drive'")
    check(datos.get("drive", {}).get("carpeta") == real["carpeta"],
          f"_umbrales_drive() NO lee config/umbrales.json: devuelve {real['carpeta']!r} "
          f"y el archivo dice {datos.get('drive', {}).get('carpeta')!r}")


def test_cambiar_el_json_cambia_la_carpeta_y_uno_roto_no_revienta():
    """Se lee EN CADA LLAMADA, no en el import. Sobre un CONFIG_DIR temporal: el
    config/umbrales.json real NO se toca."""
    original = gw.CONFIG_DIR
    try:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "umbrales.json").write_text(
                json.dumps({"drive": {"carpeta": "CARPETA-DE-PRUEBA"}}), encoding="utf-8")
            gw.CONFIG_DIR = Path(td)
            check(gw._umbrales_drive()["carpeta"] == "CARPETA-DE-PRUEBA",
                  "el nombre de la carpeta está a fuego: cambiar umbrales.json no hace nada")
        with tempfile.TemporaryDirectory() as td:
            Path(td, "umbrales.json").write_text("{ esto no es json", encoding="utf-8")
            gw.CONFIG_DIR = Path(td)
            check(gw._umbrales_drive()["carpeta"] == gw.DRIVE_CARPETA_RESERVA,
                  "con umbrales.json roto debería usar la reserva, no reventar")
    finally:
        gw.CONFIG_DIR = original


# ==================== 3. LA API QUE SE LLAMA ES LA REAL =====================
class _Ejec:
    def __init__(self, res):
        self._res = res

    def execute(self):
        return self._res


class _FakeFiles:
    def __init__(self, dueño):
        self.d = dueño

    def list(self, **kw):
        self.d.listas.append(kw)
        return _Ejec(self.d.respuesta_list.pop(0) if self.d.respuesta_list else {"files": []})

    def create(self, **kw):
        # media_body NO se guarda: MediaFileUpload tiene el fichero ABIERTO, y
        # guardarlo aquí lo mantendría vivo → el .md se queda bloqueado en Windows
        # y falla el borrado del directorio temporal.
        g = {k: v for k, v in kw.items() if k != "media_body"}
        g["_con_media"] = "media_body" in kw
        self.d.creaciones.append(g)
        n = len(self.d.creaciones)
        return _Ejec({"id": f"id-{n}", "name": (kw.get("body") or {}).get("name", ""),
                      "webViewLink": f"https://drive.google.com/file/d/id-{n}/view"})


    # ── CRUD (02/08/2026). `borrados` es la lista que NUNCA debería crecer sin
    # una confirmación de por medio: es files.delete, el irreversible.
    def update(self, **kw):
        self.d.updates.append({k: v for k, v in kw.items() if k != "media_body"})
        cuerpo = kw.get("body") or {}
        n = len(self.d.updates)
        return _Ejec({"id": kw.get("fileId"), "name": cuerpo.get("name", "el-de-antes"),
                      "mimeType": "text/markdown", "trashed": cuerpo.get("trashed", False),
                      "parents": [kw.get("addParents") or "padre"],
                      "webViewLink": f"https://drive.google.com/file/d/{n}/view"})

    def delete(self, **kw):
        self.d.borrados.append(kw)
        return _Ejec({})

    def get(self, **kw):
        self.d.gets.append(kw)
        return _Ejec(self.d.respuesta_get.pop(0) if self.d.respuesta_get
                     else {"id": kw.get("fileId"), "name": "loquesea",
                           "webViewLink": "https://drive.google.com/x/view"})


class _FakeDrive:
    def __init__(self, respuesta_list=None, respuesta_get=None):
        self.listas, self.creaciones = [], []
        self.updates, self.borrados, self.gets = [], [], []
        self.respuesta_list = list(respuesta_list or [])
        self.respuesta_get = list(respuesta_get or [])

    def files(self):
        return _FakeFiles(self)


def test_subir_pide_files_create_con_padre_nombre_y_mimetype_correctos():
    fake = _FakeDrive([{"files": [{"id": "carpeta-ya-existe", "name": "nexus"}]}])
    orig, gw._drive_service = gw._drive_service, lambda: fake
    try:
        with tempfile.TemporaryDirectory() as td:
            md = Path(td, "informe-2026-08-02.md")
            md.write_text("# informe\n", encoding="utf-8")
            res = gw._drive_subir(md, carpeta="nexus")
    finally:
        gw._drive_service = orig
    check(len(fake.creaciones) == 1, "debería crear UN fichero (la carpeta ya existía)")
    body = fake.creaciones[0].get("body", {})
    check(body.get("name") == "informe-2026-08-02.md",
          f"sube el fichero con otro nombre: {body.get('name')!r}")
    check(body.get("parents") == ["carpeta-ya-existe"],
          "no cuelga el fichero de la carpeta encontrada ('parents' mal)")
    check(fake.creaciones[0].get("_con_media") is True,
          "crea la entrada en Drive pero SIN contenido (falta media_body)")
    check("webViewLink" in fake.creaciones[0].get("fields", ""),
          "no pide webViewLink: sin él no hay enlace que darle a ChatGPT/Claude")
    check(fake.creaciones[0].get("supportsAllDrives") is True,
          "falta supportsAllDrives en files().create")
    check(res.get("webViewLink", "").startswith("https://"), "no devuelve enlace")
    check(res.get("id"), "no devuelve id")
    check(res.get("carpeta") == "nexus", "no dice en qué carpeta ha dejado el fichero")


def test_el_md_se_sube_como_text_markdown():
    """mimetypes de Python NO conoce .md; sin forzarlo, Drive lo guarda como
    binario y ChatGPT/Claude no saben leerlo."""
    check(gw._drive_mime(Path("x.md")) == "text/markdown", ".md no va como text/markdown")
    check(gw._drive_mime(Path("x.markdown")) == "text/markdown", ".markdown mal")
    check(gw._drive_mime(Path("x.pdf")) == "application/pdf", ".pdf mal detectado")
    check(gw._drive_mime(Path("x.zzz")) == "application/octet-stream",
          "extensión desconocida debería caer en octet-stream, no en None")


def test_la_carpeta_se_busca_y_si_no_esta_se_crea():
    fake = _FakeDrive([{"files": []}])                    # no la encuentra
    idc = gw._drive_carpeta_id(fake, "nexus")
    q = fake.listas[0].get("q", "")
    check("mimeType = 'application/vnd.google-apps.folder'" in q,
          f"la búsqueda no filtra por el mimeType de carpeta: q={q!r}")
    check("name = 'nexus'" in q, f"la búsqueda no filtra por nombre: q={q!r}")
    check("trashed = false" in q,
          "la búsqueda no excluye la papelera: reutilizaría una carpeta borrada")
    check(len(fake.creaciones) == 1 and
          fake.creaciones[0]["body"].get("mimeType") == gw.DRIVE_MIME_CARPETA,
          "no crea la carpeta cuando no existe")
    check(idc == "id-1", "no devuelve el id de la carpeta recién creada")
    fake2 = _FakeDrive([{"files": [{"id": "ya", "name": "nexus"}]}])
    check(gw._drive_carpeta_id(fake2, "nexus") == "ya" and not fake2.creaciones,
          "crea carpeta nueva aunque ya existía una suya (duplicaría carpetas)")


def test_una_comilla_en_el_nombre_no_rompe_la_consulta():
    """Google escapa ' y \\ con contrabarra. Sin esto, una carpeta «Adri's» genera
    una consulta rota (error 400) que PARECE un fallo de red."""
    check(gw._drive_escape("Adri's") == "Adri\\'s", "no escapa la comilla simple")
    check(gw._drive_escape("a\\b") == "a\\\\b", "no escapa la contrabarra")
    fake = _FakeDrive([{"files": [{"id": "x"}]}])
    gw._drive_carpeta_id(fake, "Adri's")
    check("name = 'Adri\\'s'" in fake.listas[0]["q"],
          f"la consulta no lleva el nombre escapado: {fake.listas[0]['q']!r}")


def test_listar_pide_solo_lo_de_dentro_de_la_carpeta_y_lo_reciente_primero():
    fake = _FakeDrive([{"files": [{"id": "c", "name": "nexus"}]},
                       {"files": [{"id": "1", "name": "a.md", "webViewLink": "http://x"}]}])
    orig, gw._drive_service = gw._drive_service, lambda: fake
    try:
        out = gw._drive_listar(10, "nexus")
    finally:
        gw._drive_service = orig
    q = fake.listas[1].get("q", "")
    check("'c' in parents" in q, f"no filtra por la carpeta de destino: q={q!r}")
    check("trashed = false" in q, "lista también lo que está en la papelera")
    check(fake.listas[1].get("orderBy") == "modifiedTime desc",
          "no ordena por más reciente primero")
    check(len(out) == 1 and out[0]["name"] == "a.md", "no devuelve lo listado")


# ======================= 4. QUÉ FICHERO SE SUBE =============================
def test_se_coge_el_informe_correcto_y_nunca_se_inventa_uno():
    """Subir el fichero equivocado al Drive de alguien no se deshace solo: si no
    está claro cuál es, se devuelve None y el handler LO DICE."""
    orig = gw.REPORTS_DIR
    try:
        with tempfile.TemporaryDirectory() as td:
            gw.REPORTS_DIR = Path(td)                     # vacía
            check(gw._drive_fichero_pedido("sube esto a drive") is None,
                  "sin informes y sin nombre debería dar None, no elegir algo")
            viejo, nuevo = Path(td, "viejo.md"), Path(td, "nuevo.md")
            viejo.write_text("v", encoding="utf-8")
            time.sleep(0.02)
            nuevo.write_text("n", encoding="utf-8")
            os.utime(viejo, (1, 1))
            check(gw._drive_fichero_pedido("sube el informe a drive") == nuevo,
                  "no coge el .md más reciente de data/reports")
            # INCIDENTE: con [\w .\-]+ (admite espacios y es codicioso) esto se
            # llevaba el verbo y buscaba un fichero llamado «sube viejo.md».
            check(gw._drive_fichero_pedido("sube viejo.md a drive") == viejo,
                  "no respeta el fichero nombrado en la orden")
            check(gw._drive_fichero_pedido("sube VIEJO.MD a drive") == viejo,
                  "no encuentra el fichero si cambian las mayúsculas")
            check(gw._drive_fichero_pedido("sube noexiste.md a drive") is None,
                  "un nombre que no existe debe dar None, no colar otro fichero")
    finally:
        gw.REPORTS_DIR = orig


# ===================== 5. ERRORES HONESTOS (sin credenciales) ===============
def test_sin_credenciales_el_mensaje_dice_que_falta_y_como_arreglarlo():
    """handle() con un ctx sin secretos y CREDS_FILE en un sitio vacío: cero red,
    cero OAuth, cero navegador."""
    class _Set:
        def secret(self, _k):
            return ""

    orig = gw.CREDS_FILE
    try:
        with tempfile.TemporaryDirectory() as td:
            gw.CREDS_FILE = Path(td, "no-existe.json")
            r = asyncio.run(gw.handle("drive_upload", "sube esto a drive", None,
                                      {"settings": _Set()}))
    finally:
        gw.CREDS_FILE = orig
    txt = r.get("reply", "")
    check(txt, "handle() no contesta nada sin credenciales")
    check("google_credentials.json" in txt or "Client ID" in txt,
          f"el mensaje no dice QUÉ falta: {txt[:160]!r}")
    check("Traceback" not in txt, "el mensaje sin credenciales parece un traceback")


def test_el_mensaje_de_falta_de_permiso_explica_el_arreglo():
    m = gw.DRIVE_SIN_SCOPE_MSG
    check("google_token.json" in m, "no dice que hay que borrar el token para reautorizar")
    check("Drive API" in m, "no menciona habilitar la Google Drive API (el otro fallo típico)")
    check("auth/drive" in m, "no dice QUÉ permiso pide")
    check("COMPLETO" in m.upper(), "no avisa de que el permiso que pide es el de "
                                   "Drive ENTERO: eso hay que decirlo, no colarlo")


def test_no_afirma_que_el_drive_esta_vacio():
    """Listar UNA carpeta y no encontrar nada no autoriza a decir «tu Drive está
    vacío»: son dos afirmaciones distintas y la segunda no se ha comprobado.
    (Antes del 02/08/2026 ni siquiera se podía comprobar; ahora se podría, pero
    seguiría siendo una respuesta a una pregunta que nadie hizo.)"""
    i = SRC.index('intent == "drive_list"')
    # solo las líneas de CÓDIGO: los comentarios de la rama hablan justamente de
    # por qué NO se dice eso, y buscar sobre el texto crudo daba falso positivo.
    trozo = "\n".join(l for l in SRC[i:i + 1400].splitlines()
                      if not l.lstrip().startswith("#")).lower()
    check("no he subido nada" in trozo,
          "drive_list debería decir «no he subido nada», no «está vacío»")
    check("vacío" not in trozo,
          "afirma que el Drive está vacío, y con drive.file no puede saberlo")


# ============================ 6. ROUTING ====================================
def _registro():
    """Todas las skills en el MISMO orden que skills_loader: alfabético por
    carpeta y, dentro, el orden del dict."""
    reg = []
    for f in sorted(d for d in os.listdir(os.path.join(ROOT, "skills"))
                    if os.path.isfile(os.path.join(ROOT, "skills", d, "skill.py"))):
        try:
            mod = _load_skill(f)
            reg.append((f, {k: re.compile(v, re.IGNORECASE)
                            for k, v in mod.SKILL["patterns"].items()}))
        except Exception:
            pass
    return reg


_REG = _registro()


def _route(texto):
    for folder, pats in _REG:
        for intent, rx in pats.items():
            if rx.search(texto):
                return folder, intent
    return None, None


def test_las_frases_de_drive_llegan_a_drive():
    casos = {
        "sube esto a drive": "drive_upload",
        "sube el informe a drive": "drive_upload",
        "súbelo a mi google drive": "drive_upload",
        "sube informe-2026-08-02.md a drive": "drive_upload",
        "guarda el informe en drive": "drive_upload",
        "cuelga el informe de hoy en drive": "drive_upload",
        "pon esto en el drive": "drive_upload",
        "sube esto a drive y dame el enlace": "drive_upload",
        "qué hay en mi drive": "drive_list",
        "qué has subido a drive": "drive_list",
        "muéstrame lo que hay en drive": "drive_list",
        "lista los archivos de mi drive": "drive_list",
        "dame el enlace de drive": "drive_link",
        "cuál es el link de drive": "drive_link",
        "enlace de google drive": "drive_link",
    }
    for frase, esperado in casos.items():
        folder, intent = _route(frase)
        check(folder == "google_workspace" and intent == esperado,
              f"«{frase}» → {folder}/{intent} (se esperaba google_workspace/{esperado})")


def test_drive_no_le_roba_frases_a_nadie():
    """Lo que ya funcionaba sigue igual. Drive va el ÚLTIMO del dict y todas sus
    regex exigen la palabra «drive» justamente por esto."""
    intocables = {
        "lee mis correos": ("google_workspace", None),
        "cuántos correos sin leer": ("google_workspace", "unread_count"),
        "de quién son los correos sin leer": ("google_workspace", "unread_from"),
        "envía un correo a hola@ejemplo.com diciendo que llego tarde":
            ("google_workspace", "send_email"),
        "resume mis correos": ("google_workspace", None),
        "qué tengo en el calendario": ("google_workspace", "gcal"),
        "crea un evento mañana a las 10": ("google_workspace", "create_event"),
        "tareas de google": ("google_workspace", "gtasks"),
        "crea una tarea en el to-do: pagar al proveedor": ("google_workspace", "create_task"),
        # y de otras skills, que van ANTES por orden alfabético
        "levanta el docker": ("autoprovision", "docker_up"),
        "sube el volumen de la tele": ("domotica", "tv_volume"),
        "guarda en el proyecto nexus que arreglé el bug": ("engram", "save"),
    }
    for frase, (folder_esp, intent_esp) in intocables.items():
        folder, intent = _route(frase)
        check(folder == folder_esp,
              f"«{frase}» se ha ido a {folder}/{intent}; era de {folder_esp}")
        check(not str(intent).startswith("drive_"),
              f"DRIVE HA ROBADO «{frase}» (→ {intent})")
        if intent_esp:
            check(intent == intent_esp, f"«{frase}» → {intent}, se esperaba {intent_esp}")


def test_todos_los_intents_de_drive_tienen_rama_en_handle():
    for intent in [k for k in gw.SKILL["patterns"] if k.startswith("drive_")]:
        check(f'intent == "{intent}"' in SRC,
              f"el intent {intent} tiene regex pero NADIE lo atiende en handle()")


# ══════════ 7. LO DESTRUCTIVO (el bloque que más importa del fichero) ═══════
# Desde el 02/08/2026 estos intents apuntan a documentos REALES de la cuenta
# entera, y se llega a ellos por una regex. Regla del proyecto, nacida del
# incidente del tablero: solo lectura por defecto; borrar exige confirmación.
from backend.core.comun import confirm as _confirm  # noqa: E402

# Los tests NO escriben en la auditoría real (data/logs/audit.jsonl). Ese fichero
# es la traza de lo que ha hecho nexus de verdad y lo comparten otras suites
# (test_purga mira cuántas entradas destructivas hay); llenarlo de confirmaciones
# de mentira ensucia el historial del usuario y rompe tests ajenos.
_confirm._audit = lambda **_kw: None


def _con_drive_falso(fake):
    """Sustituye el servicio de Drive por el doble. Devuelve el restaurador."""
    orig = gw._drive_service
    gw._drive_service = lambda: fake
    return lambda: setattr(gw, "_drive_service", orig)


def _handle(intent, texto, canal="pc"):
    """handle() de verdad, pero sin pasar por _ensure_credentials: ese lee (y en
    algún caso REESCRIBE) config/google_credentials.json, y los tests no tocan la
    configuración real de nadie. Del Drive se encarga el doble."""
    orig = gw._ensure_credentials
    gw._ensure_credentials = lambda _c: True
    try:
        return asyncio.run(gw.handle(intent, texto, None,
                                     {"channel": canal, "settings": None}))
    finally:
        gw._ensure_credentials = orig


def _fichero(nombre="informe-viejo.md", carpeta=False):
    return {"files": [{"id": "id-obj", "name": nombre, "parents": ["padre-viejo"],
                       "mimeType": gw.DRIVE_MIME_CARPETA if carpeta else "text/markdown",
                       "webViewLink": "https://drive.google.com/file/d/id-obj/view"}]}


def test_borrar_manda_a_la_papelera_y_NO_borra_de_verdad():
    """EL TEST. «borra X de drive» = trashed:true, que se deshace desde
    drive.google.com/drive/trash. files.delete NO se toca."""
    _confirm.clear()
    fake = _FakeDrive([_fichero()])
    restaurar = _con_drive_falso(fake)
    try:
        res = _handle("drive_delete", "borra informe-viejo.md de drive")
    finally:
        restaurar()
    check(fake.borrados == [],
          "¡files.delete LLAMADO! Un borrado normal tiene que ir a la PAPELERA, "
          "no destruir el documento. Esto es exactamente el incidente del tablero.")
    check(len(fake.updates) == 1, f"esperaba UN update (el de papelera), hubo {len(fake.updates)}")
    check((fake.updates[0].get("body") or {}).get("trashed") is True,
          "el update no pone trashed=True: entonces no ha mandado nada a la papelera")
    check(fake.updates[0].get("fileId") == "id-obj",
          "manda a la papelera un id que no es el del fichero pedido")
    check("papelera" in res["reply"].lower(),
          "no le dice al usuario que está en la papelera (y que puede recuperarlo)")
    check(_confirm.pending("pc") is None,
          "ha pedido confirmación para ir a la papelera; eso es reversible, va directo")


def test_el_borrado_definitivo_no_ocurre_sin_pasar_por_confirm_request():
    _confirm.clear()
    fake = _FakeDrive([_fichero()])
    restaurar = _con_drive_falso(fake)
    try:
        res = _handle("drive_delete", "borra definitivamente informe-viejo.md de drive")
        check(fake.borrados == [],
              "¡HA BORRADO DE VERDAD sin preguntar! files.delete no vuelve atrás.")
        check(fake.updates == [], "ni siquiera debería haberlo mandado a la papelera aún")
        pend = _confirm.pending("pc")
        check(pend is not None, "no ha dejado ninguna confirmación armada: "
                                "entonces, o no borra, o borró a lo callado")
        check("definitiv" in res["reply"].lower(),
              "no avisa de que ese borrado es DEFINITIVO")
        check("sí" in res["reply"].lower() and "no" in res["reply"].lower(),
              "no dice cómo se contesta a la confirmación")
        # decir que no NO borra nada
        check(asyncio.run(_confirm.answer("no", "pc")) is not None, "no atendió el «no»")
        check(fake.borrados == [], "¡ha borrado después de que el usuario dijera NO!")
        # y decir que sí SÍ borra: la acción está bien enchufada, no es decorativa
        fake.respuesta_list = [_fichero()]
        _handle("drive_delete", "borra definitivamente informe-viejo.md de drive")
        asyncio.run(_confirm.answer("sí", "pc"))
        check(len(fake.borrados) == 1,
              "tras confirmar, files.delete no se llamó: la confirmación era un adorno")
    finally:
        restaurar()
        _confirm.clear()


def test_borrar_una_carpeta_con_cosas_dentro_dice_cuantas_antes_de_tocar_nada():
    _confirm.clear()
    fake = _FakeDrive([_fichero("Pruebas", carpeta=True),
                       {"files": [{"id": f"h{i}", "name": f"hijo{i}.md"} for i in range(3)]}])
    restaurar = _con_drive_falso(fake)
    try:
        res = _handle("drive_delete", "borra la carpeta Pruebas de drive")
    finally:
        restaurar()
        _confirm.clear()
    check(fake.borrados == [] and fake.updates == [],
          "ha vaciado la carpeta sin avisar; eso es justo lo que no se hace")
    check("3" in res["reply"],
          f"no dice CUÁNTOS elementos se lleva por delante: {res['reply']!r}")
    check("papelera" in res["reply"].lower(),
          "no aclara que, aun con confirmación, va a la papelera y es recuperable")
    check(res.get("data", {}).get("confirm") is True, "no marca que está esperando un sí/no")


def test_files_delete_solo_se_invoca_desde_dentro_de_la_confirmacion():
    """Lectura del código, no del comportamiento: que mañana nadie añada un
    atajo «rápido» que llame a _drive_destruir() sin pasar por confirm."""
    check(SRC.count("files().delete(") == 1,
          "hay más de un sitio llamando a files().delete(); debe existir UNO solo, "
          "dentro de _drive_destruir()")
    i = SRC.index("def _drive_destruir")
    check("files().delete(" in SRC[i:i + 700],
          "files().delete() ya no vive dentro de _drive_destruir(); localízalo")
    # una aparición es el `def`; solo puede quedar UNA llamada más
    apariciones = SRC.count("_drive_destruir(")
    check(apariciones == 2,
          f"_drive_destruir() aparece {apariciones} veces (1 def + {apariciones - 1} "
          "llamadas); solo puede llamarse desde el `action` de un confirm.request()")
    j = SRC.index("def _ejecutar")
    check("_drive_destruir(" in SRC[j:j + 500],
          "_drive_destruir() ya no está dentro del closure que arma confirm.request()")
    check("confirm.request(" in SRC[j:j + 900],
          "el closure que destruye no acaba en un confirm.request()")


def test_mover_y_renombrar_van_directos_porque_no_destruyen():
    for intent, frase in (("drive_move", "mueve informe.md a la carpeta Clientes en drive"),
                          ("drive_rename", "renombra informe.md a final.md en drive")):
        _confirm.clear()
        fake = _FakeDrive([_fichero("informe.md"),
                           {"files": [{"id": "carpeta-destino", "name": "Clientes"}]}])
        restaurar = _con_drive_falso(fake)
        try:
            _handle(intent, frase)
        finally:
            restaurar()
        check(_confirm.pending("pc") is None,
              f"{intent} pide confirmación y no destruye nada: sobra fricción")
        check(fake.borrados == [], f"{intent} ha llamado a files.delete")
    _confirm.clear()


# ══════════════════ 8. CRUD DE CARPETAS Y FICHEROS ══════════════════════════
def test_crear_una_carpeta_anidada_crea_solo_los_tramos_que_faltan():
    fake = _FakeDrive([{"files": [{"id": "id-clientes", "name": "Clientes"}]},  # existe
                       {"files": []},                                          # 2026 no
                       {"files": []}])                                         # agosto no
    restaurar = _con_drive_falso(fake)
    try:
        gw._drive_crear_carpeta("Clientes/2026/agosto")
    finally:
        restaurar()
    check(len(fake.creaciones) == 2,
          f"debía crear 2 tramos (2026 y agosto), creó {len(fake.creaciones)}")
    b0 = fake.creaciones[0].get("body") or {}
    check(b0.get("name") == "2026" and b0.get("mimeType") == gw.DRIVE_MIME_CARPETA,
          "el tramo intermedio no se crea como carpeta")
    check(b0.get("parents") == ["id-clientes"],
          "«2026» no cuelga de «Clientes»: la ruta anidada no se está respetando")
    check((fake.creaciones[1].get("body") or {}).get("parents") == ["id-1"],
          "«agosto» no cuelga del «2026» recién creado")
    # el segundo tramo se busca DENTRO del primero, no por todo el Drive
    check("'id-clientes' in parents" in fake.listas[1]["q"],
          f"la búsqueda del tramo 2 no acota al padre: {fake.listas[1]['q']!r}")


def test_mover_usa_addparents_y_removeparents_y_no_recrea_el_fichero():
    fake = _FakeDrive([_fichero("informe.md"),
                       {"files": [{"id": "carpeta-destino", "name": "Clientes"}]}])
    restaurar = _con_drive_falso(fake)
    try:
        res = gw._drive_mover("informe.md", "Clientes")
    finally:
        restaurar()
    check(len(fake.updates) == 1, "mover debe ser UN files.update")
    u = fake.updates[0]
    check(u.get("addParents") == "carpeta-destino", f"addParents mal: {u.get('addParents')!r}")
    check(u.get("removeParents") == "padre-viejo",
          "no quita el padre anterior: el fichero acabaría en las dos carpetas")
    check(u.get("fileId") == "id-obj", "mueve un id que no es el del fichero pedido")
    check(fake.creaciones == [] and fake.borrados == [],
          "mover NO es copiar y borrar: si crea o borra, algo se ha reimplementado mal")
    check(res.get("destino") == "Clientes", "no devuelve a dónde lo ha movido")


def test_renombrar_es_un_update_de_name_a_secas():
    fake = _FakeDrive([_fichero("informe.md")])
    restaurar = _con_drive_falso(fake)
    try:
        gw._drive_renombrar("informe.md", "informe-final.md")
    finally:
        restaurar()
    u = fake.updates[0]
    check((u.get("body") or {}) == {"name": "informe-final.md"},
          f"el body del renombrado lleva cosas de más: {u.get('body')!r}")
    check("trashed" not in (u.get("body") or {}), "renombrar no puede tocar trashed")
    check(fake.creaciones == [] and fake.borrados == [], "renombrar ni crea ni borra")


def test_actualizar_conserva_el_id_y_no_deja_un_duplicado():
    """Volver a subir dejaría DOS ficheros con el mismo nombre y un enlace nuevo;
    el viejo es el que el usuario ya ha pegado en ChatGPT/Claude."""
    fake = _FakeDrive([_fichero("informe.md")])
    restaurar = _con_drive_falso(fake)
    try:
        with tempfile.TemporaryDirectory() as td:
            md = Path(td, "informe.md")
            md.write_text("# nuevo contenido\n", encoding="utf-8")
            gw._drive_reemplazar("informe.md", md)
    finally:
        restaurar()
    check(fake.creaciones == [],
          "ha creado un fichero nuevo: eso es un duplicado, no una actualización")
    check(len(fake.updates) == 1 and fake.updates[0].get("fileId") == "id-obj",
          "no actualiza el fichero que ya estaba (se pierde el enlace de siempre)")


def test_listar_o_buscar_en_una_carpeta_que_no_existe_NO_la_crea():
    """Una operación de LECTURA que crea cosas de rebote es una mentira: contesta
    «no hay nada» sobre una carpeta que acaba de fabricar ella misma."""
    for fn in (lambda: gw._drive_listar(10, "NoExiste"),
               lambda: gw._drive_buscar("x", "", "NoExiste")):
        fake = _FakeDrive([{"files": []}])
        restaurar = _con_drive_falso(fake)
        try:
            check(fn() == [], "debería devolver lista vacía")
        finally:
            restaurar()
        check(fake.creaciones == [],
              "¡ha CREADO la carpeta que solo iba a leer! (falta crear=False)")


def test_la_carpeta_de_umbrales_es_el_defecto_pero_se_puede_apuntar_a_otra():
    check(gw._drive_carpeta_pedida("sube el informe a la carpeta Clientes de drive") == "Clientes",
          "no coge la carpeta que dice la orden; siempre acabaría en la de umbrales")
    check(gw._drive_carpeta_pedida("crea la carpeta Clientes/2026/agosto en drive")
          == "Clientes/2026/agosto", "no admite rutas anidadas")
    check(gw._drive_carpeta_pedida("mueve notas.md a la raíz de drive") == "raiz",
          "no entiende «a la raíz»")
    check(gw._drive_carpeta_pedida("sube el informe a drive") == "",
          "se inventa una carpeta cuando la orden no dice ninguna (debe usar umbrales)")
    fake = _FakeDrive()
    restaurar = _con_drive_falso(fake)
    try:
        check(gw._drive_carpeta_id(fake, "raiz") == gw.DRIVE_RAIZ,
              "«raíz» no se traduce al id literal 'root' de Drive")
    finally:
        restaurar()
    check(fake.listas == [] and fake.creaciones == [],
          "para ir a la raíz no hace falta buscar ni crear nada")


def test_buscar_arma_la_q_con_contains_y_filtra_por_tipo():
    fake = _FakeDrive([{"files": []}])
    restaurar = _con_drive_falso(fake)
    try:
        gw._drive_buscar("contratos", "pdf")
    finally:
        restaurar()
    q = fake.listas[0]["q"]
    check("name contains 'contratos'" in q, f"no busca por trozo de nombre: {q!r}")
    check("mimeType contains 'pdf'" in q, f"no filtra por tipo: {q!r}")
    check("trashed = false" in q, "buscaría también en la papelera")
    check(fake.listas[0].get("supportsAllDrives") is True,
          "sin supportsAllDrives no ve las unidades compartidas")


def test_descargar_una_carpeta_se_niega_en_vez_de_inventarse_algo():
    fake = _FakeDrive([_fichero("Clientes", carpeta=True)])
    restaurar = _con_drive_falso(fake)
    try:
        try:
            gw._drive_descargar("Clientes", Path(ROOT, "no-se-usa"))
            check(False, "ha intentado descargar una CARPETA como si fuera un fichero")
        except IsADirectoryError:
            check(True, "")
    finally:
        restaurar()
    check("IsADirectoryError" in SRC, "handle() no traduce ese error a algo legible")


def test_un_nombre_que_no_existe_se_dice_no_se_aproxima():
    fake = _FakeDrive([{"files": []}])
    restaurar = _con_drive_falso(fake)
    try:
        res = _handle("drive_rename", "renombra loquesea.md a otro.md en drive")
    finally:
        restaurar()
    check("no encuentro" in res["reply"].lower(),
          f"no dice claramente que no lo encuentra: {res['reply']!r}")
    check("loquesea.md" in res["reply"], "no repite el nombre que se buscó")
    check(fake.updates == [] and fake.borrados == [], "ha tocado algo pese a no encontrarlo")
    check("name = " in fake.listas[0]["q"],
          "busca por aproximación; con el Drive entero eso toca el documento de al lado")


# ══════════════ 9. ROUTING DE LOS INTENTS NUEVOS (02/08/2026) ═══════════════
def test_las_ordenes_nuevas_de_drive_llegan_a_drive():
    casos = {
        "crea la carpeta Informes en drive": "drive_folder_create",
        "crea la carpeta Clientes/2026/agosto en drive": "drive_folder_create",
        "haz una carpeta nueva llamada Contratos en mi drive": "drive_folder_create",
        "mueve informe-2026-08-02.md a la carpeta Clientes en drive": "drive_move",
        "mueve el archivo notas.md a la raíz de drive": "drive_move",
        "renombra informe.md a informe-final.md en drive": "drive_rename",
        "cámbiale el nombre a borrador.md por definitivo.md en drive": "drive_rename",
        "borra informe-viejo.md de drive": "drive_delete",
        "borra la carpeta Pruebas de drive": "drive_delete",
        "elimina para siempre la carpeta Pruebas de mi drive": "drive_delete",
        "actualiza informe-2026-08-02.md en drive": "drive_replace",
        "reemplaza el informe en drive": "drive_replace",
        "descarga informe.md de drive": "drive_download",
        "bájame el contrato.pdf de drive": "drive_download",
        "busca contratos en drive": "drive_search",
        "busca los pdf de 2026 en drive": "drive_search",
        "qué hay en la carpeta Clientes de drive": "drive_list",
        "sube el informe a la carpeta Clientes de drive": "drive_upload",
    }
    for frase, intent_esp in casos.items():
        folder, intent = _route(frase)
        check(folder == "google_workspace",
              f"«{frase}» se ha ido a {folder}/{intent} en vez de a Drive")
        check(intent == intent_esp, f"«{frase}» → {intent}, se esperaba {intent_esp}")


def test_drive_no_le_ha_robado_nada_a_files_ni_al_resto():
    """skills/files gestiona ficheros LOCALES y va ANTES por orden alfabético.
    Las dos direcciones tienen que aguantar: ni files se lleva las de Drive
    (para eso está _SIN_DRIVE allí), ni Drive se lleva las locales."""
    locales = {
        "borra el archivo D:/tmp/x.txt": "trash",
        "borra la carpeta pruebas": "trash",
        "manda a la papelera el archivo basura.txt": "trash",
        "mueve el archivo a.txt a la carpeta D:/tmp": "move",
        "renombra a.txt a b.txt": "rename",
        "crea la carpeta D:/tmp/nueva": "mkdir",
        "qué hay en la carpeta D:/tmp": "explore",
        "lee el archivo notas.txt": "read",
        "resume el documento informe.md": "summarize",
    }
    for frase, intent_esp in locales.items():
        folder, intent = _route(frase)
        check(folder == "files",
              f"DRIVE (u otro) HA ROBADO una orden de ficheros locales: "
              f"«{frase}» → {folder}/{intent}")
        check(intent == intent_esp, f"«{frase}» → files/{intent}, se esperaba {intent_esp}")
    otros = {
        "borra los correos de spam": ("google_workspace", "delete_email"),
        "cancela el evento de mañana": ("google_workspace", "delete_event"),
        "lee mis correos": ("google_workspace", None),
        "qué tengo en el calendario": ("google_workspace", None),
        "crea una tarea en el to-do: pagar al proveedor": ("google_workspace", None),
    }
    for frase, (folder_esp, intent_esp) in otros.items():
        folder, intent = _route(frase)
        check(folder == folder_esp, f"«{frase}» → {folder}/{intent}")
        check(not str(intent).startswith("drive_"),
              f"DRIVE HA ROBADO «{frase}» (→ {intent})")
        if intent_esp:
            check(intent == intent_esp, f"«{frase}» → {intent}, se esperaba {intent_esp}")


def test_el_candado_antidrive_de_files_sigue_puesto():
    fsrc = Path(ROOT, "skills", "files", "skill.py").read_text(encoding="utf-8")
    check("_SIN_DRIVE" in fsrc,
          "se ha quitado el candado de skills/files: volverá a robarle las órdenes "
          "a Drive porque «files» va antes por orden alfabético")
    check("alfabético" in fsrc.lower() or "alfabetico" in fsrc.lower(),
          "el candado está pero sin explicar por qué; el siguiente lo borra")


# ══ 10. SEC-19: LA RUTA QUE SE TECLEA PASA POR LOS PERMISOS DE ⚙ ═════════
# EL AGUJERO (hallazgo SEC-19, encontrado en T7): `_drive_fichero_pedido`
# aceptaba una RUTA ABSOLUTA escrita en la propia orden y la subía tal cual, sin
# pasar por `permissions.path_allowed()` — que es por donde pasa CUALQUIER otra
# ruta del proyecto. Con `perm_files: "todo"` (el valor que este operador tiene
# guardado) la orden «sube «C:\...\config\secrets.json» a drive» metía las API
# keys en Google Drive, y lo mismo un token OAuth o una clave privada: era el
# único camino de LECTURA + EXFILTRACIÓN que se saltaba la denylist de T7.
#
# Lo que fijan estas pruebas, en orden: (1) el arnés NO stubbea los permisos —si
# lo hiciera, un SimpleNamespace siempre diría que sí y todo esto no probaría
# nada—; (2) una ruta tecleada con credenciales se NIEGA en modo «todo» sin una
# sola subida; (3) en «carpetas» sale lo de dentro y no lo de fuera; (4) los
# informes de nexus (data/reports) se siguen subiendo IGUAL en los tres modos,
# porque son sus propios artefactos; (5) `drive_replace` tiene la misma puerta;
# (6) la negativa no revela si el archivo existe; (7) `None` sigue significando
# «no he encontrado qué subir», nunca «no tienes permiso».
from backend.core.comun import permissions as _permisos  # noqa: E402
from backend.core.comun.config import settings as _ajustes  # noqa: E402


class _Config:
    """Cambia claves de configuración EN MEMORIA (nunca escribe settings.json)."""

    def __init__(self, **vals):
        self.vals = vals

    def __enter__(self):
        self.previo = dict(_ajustes._json)
        _ajustes._json.update(self.vals)
        return self

    def __exit__(self, *_exc):
        _ajustes._json.clear()
        _ajustes._json.update(self.previo)
        return False


class _Entorno:
    """Cambia variables de entorno y las devuelve pase lo que pase."""

    def __init__(self, **vals):
        self.vals = vals

    def __enter__(self):
        self.previo = {k: os.environ.get(k) for k in self.vals}
        os.environ.update(self.vals)
        return self

    def __exit__(self, *_exc):
        for k, v in self.previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


class _EspiaSubidas:
    """Apunta la llamada y contesta algo inocuo: ni Drive ni se lee el fichero."""

    def __init__(self):
        self.llamadas = []

    def __call__(self, *a, **kw):
        self.llamadas.append({"args": a, "kwargs": kw})
        ruta = Path(a[0]) if a else Path("?")
        return {"id": "id-subido", "name": ruta.name,
                "webViewLink": "https://drive.google.com/file/d/id-subido/view",
                "carpeta": "nexus"}


def _espia_de(nombre):
    """Sustituye gw.<nombre> por el espía. Devuelve (espía, restaurar)."""
    espia = _EspiaSubidas()
    original = getattr(gw, nombre)
    setattr(gw, nombre, espia)
    return espia, lambda: setattr(gw, nombre, original)


def _perfil_de_mentira(td):
    """Un perfil (USERPROFILE/HOME/APPDATA) dentro de la carpeta desechable."""
    home = Path(td, "perfil")
    home.mkdir(parents=True, exist_ok=True)
    entorno = _Entorno(USERPROFILE=str(home), HOME=str(home),
                       APPDATA=str(home / "AppData" / "Roaming"),
                       LOCALAPPDATA=str(home / "AppData" / "Local"))
    return entorno, home


def test_los_permisos_los_resuelve_el_modulo_de_verdad_no_un_stub():
    """`_load_skill` stubbea con SimpleNamespace los módulos que no encuentra, y un
    SimpleNamespace SIEMPRE es verdadero: stubbeado, `path_allowed` no negaría
    nunca y el resto de este bloque pasaría sin probar nada. Se comprueba además
    que la configuración de la prueba es de usar y tirar (aquí se escribe un
    secrets.json de mentira)."""
    check(hasattr(gw, "_permisos"),
          "la skill no expone _permisos(): no hay forma de comprobar que el permiso "
          "lo resuelve el módulo real y no un doble del arnés")
    mod = gw._permisos() if hasattr(gw, "_permisos") else None
    check(getattr(mod, "__name__", "") == "backend.core.comun.permissions",
          f"la skill resuelve los permisos con {getattr(mod, '__name__', mod)!r}, no con "
          "backend.core.comun.permissions: el arnés lo está stubbeando y el agujero "
          "SEC-19 volvería a estar abierto sin que esta suite se enterara")
    check(callable(getattr(mod, "path_allowed", None))
          and callable(getattr(mod, "deny_msg", None)),
          "el módulo de permisos de la skill no tiene path_allowed/deny_msg reales")
    cfg = Path(_permisos.CONFIG_DIR).resolve()
    check(str(cfg).startswith(str(Path(tempfile.gettempdir()).resolve())),
          f"la configuración de esta prueba NO es de usar y tirar ({cfg}): aquí no se escribe")


def test_un_secreto_de_la_config_no_se_sube_aunque_el_modo_sea_todo():
    """El caso del hallazgo: la denylist vive DENTRO de path_allowed y se aplica
    antes del modo, así que en «todo» —el modo más abierto— una ruta tecleada con
    credenciales tiene que seguir negándose. Antes del arreglo el fichero existía y
    se subía a Drive."""
    seco = Path(_permisos.CONFIG_DIR) / "secrets.json"
    seco.parent.mkdir(parents=True, exist_ok=True)
    seco.write_text('{"demo": "credencial de mentira, de la carpeta desechable"}',
                   encoding="utf-8")
    espia, restaurar = _espia_de("_drive_subir")
    try:
        with _Config(perm_files="todo"):
            res = _handle("drive_upload", f"sube «{seco}» a drive")
    finally:
        restaurar()
    txt = res.get("reply", "")
    check(espia.llamadas == [],
          f"¡HA SUBIDO EL SECRETO A DRIVE! llamadas={espia.llamadas}")
    check("permiso" in txt.lower(), f"la negativa no habla de permisos: {txt[:200]!r}")
    check("⚙" in txt, f"no dice DÓNDE se arregla (⚙ → Permisos): {txt[:200]!r}")
    check("copi" in txt.lower(),
          f"no ofrece la salida honesta (una copia en una carpeta permitida): {txt[:200]!r}")
    check("no sé qué archivo" not in txt.lower(),
          f"contesta «no sé qué archivo» a una ruta que sí se sabía: {txt[:200]!r}")


def test_la_clave_ssh_tecleada_en_la_orden_tampoco_sale_del_equipo():
    """Segundo nombre de la denylist: `~/.ssh`. El perfil es de mentira, así que no
    se toca ni se lee la carpeta real del operador."""
    with tempfile.TemporaryDirectory() as td:
        entorno, home = _perfil_de_mentira(td)
        clave = home / ".ssh" / "id_rsa"
        clave.parent.mkdir(parents=True, exist_ok=True)
        clave.write_text("clave de mentira\n", encoding="utf-8")
        espia, restaurar = _espia_de("_drive_subir")
        try:
            with entorno, _Config(perm_files="todo"):
                res = _handle("drive_upload", f"sube «{clave}» a drive")
        finally:
            restaurar()
        txt = res.get("reply", "")
        check(espia.llamadas == [],
              f"¡HA SUBIDO UNA CLAVE PRIVADA! llamadas={espia.llamadas}")
        check("permiso" in txt.lower(), f"la negativa no habla de permisos: {txt[:200]!r}")
        check("⚙" in txt, f"no dice DÓNDE se arregla (⚙ → Permisos): {txt[:200]!r}")
        check("no sé qué archivo" not in txt.lower(),
              f"contesta «no sé qué archivo» cuando lo que pasa es que no hay permiso: {txt[:200]!r}")


def test_en_modo_carpetas_solo_sale_lo_que_vive_en_una_carpeta_permitida():
    """El modo por defecto desde T7: lo de dentro de perm_folders sale, lo de fuera
    no, y el mensaje de la negativa es accionable (añadir la carpeta en ⚙)."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        permitida = base / "permitida"
        permitida.mkdir()
        dentro = permitida / "nota-permitida.md"
        dentro.write_text("contenido del operador\n", encoding="utf-8")
        (base / "fuera").mkdir()
        fuera = base / "fuera" / "nota-privada.md"
        fuera.write_text("contenido privado\n", encoding="utf-8")
        espia, restaurar = _espia_de("_drive_subir")
        try:
            with _Config(perm_files="carpetas", perm_folders=[str(permitida)]):
                ok = _handle("drive_upload", f"sube «{dentro}» a drive")
                no = _handle("drive_upload", f"sube «{fuera}» a drive")
        finally:
            restaurar()
        check(len(espia.llamadas) == 1,
              f"esperaba UNA subida (la de la carpeta permitida), hubo {len(espia.llamadas)}")
        if espia.llamadas:
            check(Path(espia.llamadas[0]["args"][0]) == dentro,
                  f"ha subido el fichero equivocado: {espia.llamadas[0]['args'][0]}")
        check("https://" in ok.get("reply", ""),
              f"la subida permitida no devuelve enlace: {ok.get('reply')!r}")
        txt = no.get("reply", "")
        check("permiso" in txt.lower(), f"la negativa no habla de permisos: {txt[:200]!r}")
        check("Carpetas permitidas" in txt,
              f"no dice DÓNDE se añade la carpeta (⚙ → Permisos → Carpetas permitidas): {txt[:200]!r}")
        check("no sé qué archivo" not in txt.lower(),
              f"contesta «no sé qué archivo» a una ruta que sí se sabía: {txt[:200]!r}")


def test_los_informes_de_nexus_se_siguen_subiendo_en_los_tres_modos():
    """REGRESIÓN de lo que NO se puede romper: data/reports es de nexus. El último
    .md (sin nombrar nada) y un nombre suelto que solo existe ahí se suben igual en
    «todo», «carpetas» y «sandbox». Si algún día se le pide permiso a los informes
    propios, esto se pone rojo y alguien tendrá que decidirlo a conciencia."""
    with tempfile.TemporaryDirectory() as td:
        entorno, _home = _perfil_de_mentira(td)
        original = gw.REPORTS_DIR
        try:
            gw.REPORTS_DIR = Path(td, "reports")
            gw.REPORTS_DIR.mkdir()
            informe = gw.REPORTS_DIR / "informe-de-hoy.md"
            informe.write_text("# informe\n", encoding="utf-8")
            for modo in ("todo", "carpetas", "sandbox"):
                espia, restaurar = _espia_de("_drive_subir")
                try:
                    with entorno, _Config(perm_files=modo, perm_folders=[]):
                        fallback = _handle("drive_upload", "sube el informe a drive")
                        por_nombre = _handle("drive_upload", "sube informe-de-hoy.md a drive")
                finally:
                    restaurar()
                check(len(espia.llamadas) == 2,
                      f"modo {modo!r}: esperaba DOS subidas (el último informe y el "
                      f"nombrado), hubo {len(espia.llamadas)}")
                for llamada in espia.llamadas:
                    check(Path(llamada["args"][0]) == informe,
                          f"modo {modo!r}: sube {llamada['args'][0]} en vez de {informe}")
                for res in (fallback, por_nombre):
                    txt = res.get("reply", "")
                    check("permiso" not in txt.lower(),
                          f"modo {modo!r}: un informe propio de nexus se topa con la "
                          f"negativa de permisos: {txt[:200]!r}")
                    check("Subido a tu Drive" in txt,
                          f"modo {modo!r}: no confirma la subida del informe: {txt[:200]!r}")
        finally:
            gw.REPORTS_DIR = original


def test_actualizar_en_drive_desde_una_ruta_prohibida_no_toca_nada():
    """`drive_replace` comparte la puerta: meter el CONTENIDO de un token OAuth en
    un documento de Drive es el mismo robo que subirlo."""
    seco = Path(_permisos.CONFIG_DIR) / "google_token.json"
    seco.parent.mkdir(parents=True, exist_ok=True)
    seco.write_text('{"demo": "token de mentira"}', encoding="utf-8")
    subidas, restaurar_s = _espia_de("_drive_subir")
    cambios, restaurar_r = _espia_de("_drive_reemplazar")
    try:
        with _Config(perm_files="todo"):
            res = _handle("drive_replace", f"actualiza «{seco}» en drive")
    finally:
        restaurar_s()
        restaurar_r()
    txt = res.get("reply", "")
    check(subidas.llamadas == [] and cambios.llamadas == [],
          f"¡HA MANDADO UN TOKEN A DRIVE! subidas={subidas.llamadas} cambios={cambios.llamadas}")
    check("permiso" in txt.lower(), f"la negativa no habla de permisos: {txt[:200]!r}")
    check("⚙" in txt, f"no dice DÓNDE se arregla (⚙ → Permisos): {txt[:200]!r}")
    check("no sé qué archivo" not in txt.lower(),
          f"contesta «no sé qué archivo» a una ruta que sí se sabía: {txt[:200]!r}")


def test_la_negativa_no_revela_si_el_archivo_existe():
    """La negativa no hace stat sobre la ruta pedida: la respuesta es la MISMA
    exista o no el archivo. Si cambiara, sería un buscador de ficheros gratis."""
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        permitida = base / "permitida"
        permitida.mkdir()
        (base / "fuera").mkdir()
        existe = base / "fuera" / "informe-real.md"
        no_existe = base / "fuera" / "informe-inventado.md"
        existe.write_text("contenido privado\n", encoding="utf-8")
        respuestas = []
        for ruta in (existe, no_existe):
            espia, restaurar = _espia_de("_drive_subir")
            try:
                with _Config(perm_files="carpetas", perm_folders=[str(permitida)]):
                    respuestas.append({
                        "txt": _handle("drive_upload", f"sube «{ruta}» a drive").get("reply", ""),
                        "subidas": list(espia.llamadas)})
            finally:
                restaurar()
        a = respuestas[0]["txt"].replace(str(existe), "«RUTA»")
        b = respuestas[1]["txt"].replace(str(no_existe), "«RUTA»")
        check(a == b,
              f"la respuesta cambia según si el archivo existe:\n  existe: {a!r}\n  no existe: {b!r}")
        bajo = a.lower()
        check("no existe" not in bajo and "no encuentro" not in bajo
              and "no sé qué archivo" not in bajo,
              f"la negativa asegura algo sobre la existencia del archivo: {a!r}")
        check(respuestas[0]["subidas"] == [] and respuestas[1]["subidas"] == [],
              "ha intentado subir algo en alguno de los dos casos")


def test_una_ruta_prohibida_no_se_confunde_con_un_nombre_que_no_existe():
    """Dos cosas distintas se dicen distinto: `None` = «no he encontrado qué
    subir»; una ruta denegada = DriveRutaDenegada con su mensaje de permisos. Si la
    denegación llegara al handler como None, el mensaje mentiría dos veces."""
    exc_cls = getattr(gw, "DriveRutaDenegada", None)
    check(exc_cls is not None,
          "la skill no distingue «ruta denegada» de «no encontrado»: hace falta "
          "DriveRutaDenegada, o la negativa se contará como «no sé qué archivo»")
    with tempfile.TemporaryDirectory() as td:
        permitida = Path(td, "permitida")
        permitida.mkdir()
        fuera = Path(td, "privado")
        fuera.mkdir()
        nota = fuera / "notas.md"
        nota.write_text("x\n", encoding="utf-8")
        lanzo, ruta_exc = False, None
        with _Config(perm_files="carpetas", perm_folders=[str(permitida)]):
            try:
                devuelto = gw._drive_fichero_pedido(f"sube «{nota}» a drive")
                check(False, f"una ruta DENEGADA devolvió {devuelto!r} en vez de "
                             "levantar DriveRutaDenegada")
            except Exception as exc:                       # noqa: BLE001
                lanzo = isinstance(exc, exc_cls) if exc_cls else False
                ruta_exc = getattr(exc, "ruta", None)
        check(lanzo, "la denegación no llegó como DriveRutaDenegada")
        check(str(nota) in str(ruta_exc or ""),
              f"la excepción no lleva la ruta denegada (lleva {ruta_exc!r})")


def test_una_carpeta_anidada_de_drive_entre_comillas_no_se_confunde_con_una_ruta_local():
    """«Clientes/2026» es una carpeta de DRIVE, no una ruta del disco. La puerta de
    permisos no puede bloquear una orden legítima de subida a una carpeta anidada:
    si lo hiciera, el arreglo de SEC-19 rompería el uso normal del intent."""
    with tempfile.TemporaryDirectory() as td:
        entorno, _home = _perfil_de_mentira(td)
        original = gw.REPORTS_DIR
        try:
            gw.REPORTS_DIR = Path(td, "reports")
            gw.REPORTS_DIR.mkdir()
            informe = gw.REPORTS_DIR / "informe-de-hoy.md"
            informe.write_text("# informe\n", encoding="utf-8")
            espia, restaurar = _espia_de("_drive_subir")
            try:
                with entorno, _Config(perm_files="carpetas", perm_folders=[]):
                    res = _handle("drive_upload",
                                  "sube el informe a la carpeta «Clientes/2026» de drive")
            finally:
                restaurar()
        finally:
            gw.REPORTS_DIR = original
        check(len(espia.llamadas) == 1,
              f"la carpeta de Drive «Clientes/2026» se ha tomado por una ruta local: "
              f"subidas={espia.llamadas} respuesta={res.get('reply')!r}")
        if espia.llamadas:
            check(Path(espia.llamadas[0]["args"][0]) == informe,
                  "no sube el informe pedido")
            check(espia.llamadas[0]["args"][1] == "Clientes/2026",
                  f"no sube a la carpeta anidada pedida: {espia.llamadas[0]['args'][1]!r}")
        check("permiso" not in res.get("reply", "").lower(),
              f"una orden normal se topa con la negativa de permisos: {res.get('reply')!r}")


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
