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
def test_el_scope_es_drive_file_y_no_el_drive_entero():
    """La barrera. drive.file = solo los ficheros que crea nexus. «auth/drive» a
    secas = TODO el Drive personal de Adrian. Si alguien amplía por comodidad,
    esto se pone rojo y le obliga a justificarlo."""
    scopes = list(gw.SCOPES)
    check("https://www.googleapis.com/auth/drive.file" in scopes,
          "SCOPES no incluye drive.file: la skill de Drive no podría subir nada")
    check("https://www.googleapis.com/auth/drive" not in scopes,
          "SE HA COLADO el scope 'auth/drive' A SECAS: da acceso a TODO el Drive "
          "personal. Usa drive.file (lee el comentario junto a SCOPES).")
    check("https://www.googleapis.com/auth/drive.readonly" not in scopes,
          "SE HA COLADO drive.readonly: deja LEER todo el Drive y encima no deja "
          "subir. Lo peor de los dos mundos.")
    for p in ("drive.metadata", "drive.appdata", "drive.scripts", "drive.photos.readonly"):
        check(f"https://www.googleapis.com/auth/{p}" not in scopes,
              f"scope {p} añadido sin que haga falta para subir informes")
    check(len([s for s in scopes if "/drive" in s]) == 1,
          "hay más de un scope de Drive; con drive.file sobra todo lo demás")
    # ampliar a Drive no puede dejar sin permisos a lo que ya funcionaba
    for s in ("gmail.modify", "gmail.send", "calendar.events", "tasks"):
        check(f"https://www.googleapis.com/auth/{s}" in gw.SCOPES,
              f"se ha perdido el scope {s} al añadir Drive")
    # una decisión sin motivo escrito se revierte sola en seis meses
    i = SRC.index("drive.file")
    check("NO LO HAGAS" in SRC[i:i + 1800],
          "falta el comentario que explica por qué drive.file y no drive a secas")


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


class _FakeDrive:
    def __init__(self, respuesta_list=None):
        self.listas, self.creaciones = [], []
        self.respuesta_list = list(respuesta_list or [])

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
    check("drive.file" in m, "no dice QUÉ permiso pide (ni que es el mínimo)")


def test_no_afirma_que_el_drive_esta_vacio():
    """Con drive.file nexus NO ve el resto del Drive. Decir «tu Drive está vacío»
    sería inventarse un dato que no puede comprobar — regla del proyecto."""
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
