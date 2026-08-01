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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
        "sube el volumen": ("domotica", "tv_volume"),
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
from backend.core import confirm as _confirm                     # noqa: E402

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
