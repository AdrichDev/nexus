"""Minion BACKUP — copias de seguridad de la memoria y datos de nexus.

Lo importante de nexus vive en data/ (memoria en grafo, tablero, contactos,
agenda de vigilancias, facturas, informes). Este minion:
  * hace una COPIA DIARIA automática (la dispara el scheduler) en
    data/backups/nexus-data-AAAAMMDD.zip, y rota: guarda las últimas KEEP;
  * copia AHORA bajo orden («haz una copia de seguridad»);
  * opcionalmente deja una SEGUNDA copia del zip en otro sitio (otro disco) si
    `backup_destino_extra` está configurado — sin nube y sin dependencias;
  * lista los zips que hay y VERIFICA el último (manifiesto con sha256 por
    archivo), para poder decir «verificó OK» y no solo «existe un zip»;
  * restaura de VERDAD: `previsualizar_restaurar()` enseña qué hay dentro sin
    extraer nada y `restaurar()` lo deja en una carpeta NUEVA, byte a byte, con
    el «sí» del operador por medio. Nunca escribe encima de data/;
  * ARCHIVA los backups manuales *.bak_vXX sueltos del proyecto en un zip y
    borra los originales — pidiendo confirmación y solo tras verificar el zip.

QUÉ CIFRA Y QUÉ NO (decisión de T17, PRIV-04 — se toma, no se finge)
---------------------------------------------------------------------
Los zips NO van cifrados, y esto es una decisión escrita, no un olvido:

  * DPAPI (`comun/cripto.py`) es la única primitiva criptográfica del proyecto y
    ata el blob a ESTA máquina y ESTE usuario de Windows. Una copia cifrada con
    DPAPI no se puede abrir en otro PC: se lleva por delante justo el caso para
    el que existe la copia (se rompió el disco, se perdió el equipo).
  * La biblioteca estándar de Python no trae ningún cifrado autenticado (ni AES
    ni ChaCha20). Montar uno a mano —un flujo derivado de HMAC, XOR con sha256—
    es inventar criptografía, y una cifra floja es PEOR que ninguna: da una
    sensación de protección que no existe y encima tapa el riesgo real.
  * `cryptography` está en el entorno, pero SOLO como dependencia transitiva en
    `requirements.lock`; no está declarada en `requirements.txt` y no se añaden
    dependencias por esta tarea.

Lo que sí se hace: el manifiesto deja probar que el contenido es el que se
copió (integridad), la copia se puede mandar fuera del disco con
`backup_destino_extra`, y README.md → «Recuperación» dice sin adornos que el
zip está en claro y que lo que hay que cifrar es el DESTINO (BitLocker,
VeraCrypt o un disco cifrado del sistema operativo).

EL MANIFIESTO (formato)
-----------------------
Un único archivo de texto dentro del zip, `nexus-backup-manifest.json`:

    {"formato": "nexus-backup-manifiesto", "version": 1, "creado": "...",
     "archivos": [{"ruta": "memory/nota.md", "bytes": 42, "sha256": "…"}, …],
     "total_archivos": N, "total_bytes": M, "omitidos": [], "cifrado": false,
     "nota": "…por qué no va cifrado…"}

Demuestra que el zip está íntegro y que no se ha tocado ni truncado, y sirve
para que un zip VIEJO sin manifiesto se siga leyendo y restaurando (se dice que
no se puede demostrar su contenido). NO es una firma: quien pueda reescribir el
zip puede reescribir el manifiesto. No pretende parar a un atacante, sino
detectar corrupción y ediciones accidentales.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

SKILL = {
    # QUÉ EFECTO tiene cada intent del enrutador (ARQ-03, task T8b): lo decide
    # `canales.EFECTOS` para permitir, preguntar o denegar; sin declarar, destructive.
    "effects": {
        "restore": "write_local",
        "list": "read",
        "baks": "destructive",
        "make": "write_local",
    },
    # Los que YA preguntan con confirm.request antes de su efecto: `brain`
    # no los vuelve a preguntar (T8c).
    "confirma": ("restore", "baks"),
    "name": "Backup",
    "description": "Copia diaria automática de data/ (memoria, tablero, contactos) con rotación de 7, backup bajo orden, restauración verificada en una carpeta nueva y archivado de los .bak sueltos",
    # 'restore' va antes que 'make': «restaura la copia de seguridad» contiene
    # «copia de seguridad» y si no, 'make' se lo llevaría.
    "patterns": {
        "restore": r"(?:restaura(?:me)?|restablece(?:me)?|recupera(?:me)?|revierte|vuelve\s+a)\s+"
                   r"(?:la\s+|el\s+|una\s+|un\s+)?(?:copia\s+de\s+seguridad|backups?|"
                   r"copia\s+de\s+ayer)",
        "list": r"(?:qu[eé]|cu[aá]ntas)\s+copias\s+de\s+seguridad|(?:ver|lista(?:me)?|mu[eé]strame)\s+"
                r"(?:las\s+|los\s+)?(?:copias\s+de\s+seguridad|backups?)\b|\bmis\s+backups?\b",
        "baks": r"(?:archiva|recoge|limpia|empaqueta)\s+(?:los\s+)?(?:\.?bak(?:s)?|backups?\s+manuales|"
                r"archivos\s+bak)\b",
        "make": r"(?:haz(?:me)?|crea(?:me)?|genera(?:me)?)\s+(?:una\s+|la\s+)?copia\s+de\s+seguridad"
                r"|\bhaz(?:me)?\s+(?:un\s+)?backup\b|\bbackup\s+ahora\b",
    },
}

KEEP = 7                     # rotación: cuántas copias diarias se conservan
_EXCLUDE_DIRS = {"backups", "chrome_nexus"}      # no auto-anidar ni perfiles de Chrome
_MAX_FILE = 50 * 1024 * 1024                     # por archivo (los gordos no van al zip)

# El manifiesto vive DENTRO del zip, con nombre propio (no cuelga de data/), y
# es lo que convierte «hay un zip» en «este zip trae lo que dice traer».
MANIFIESTO = "nexus-backup-manifest.json"
FORMATO_MANIFIESTO = "nexus-backup-manifiesto"
VERSION_MANIFIESTO = 1

_RX_DIARIA = re.compile(r"^nexus-data-(\d{8})\.zip$", re.IGNORECASE)
_RX_BAKS = re.compile(r"^baks-", re.IGNORECASE)
_TROZO = 1 << 20

AVISO_SIN_CIFRAR = (
    "el zip NO va cifrado: su contenido es texto legible (memoria, tablero, "
    "contactos). Protégelo cifrando el DESTINO (BitLocker, VeraCrypt o un disco "
    "cifrado) o dejándolo en un disco que puedas guardar bajo llave — ver "
    "README.md → «Recuperación».")


def _dirs():
    from backend.core.comun.config import DATA_DIR
    root = Path(DATA_DIR)
    dest = root / "backups"
    return root, dest


def _sha256_de(ruta: Path) -> tuple[int, str]:
    """(tamaño, sha256) leyendo el archivo UNA vez y por trozos."""
    h = hashlib.sha256()
    total = 0
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(_TROZO), b""):
            h.update(trozo)
            total += len(trozo)
    return total, h.hexdigest()


# ───────────────────────── crear la copia (+ manifiesto) ────────────────────

def make_backup() -> tuple[Path, int]:
    """Zipea data/ con su manifiesto dentro → (ruta_zip, nº archivos de datos).

    El zip se escribe a un `.tmp` y se renombra al final: una copia a medias
    nunca se llama `nexus-data-*.zip`, que es el nombre del que uno se fía. El
    número que devuelve cuenta ARCHIVOS DE DATOS, no la entrada del manifiesto.
    """
    root, dest = _dirs()
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"nexus-data-{dt.date.today():%Y%m%d}.zip"

    archivos: list[dict] = []
    omitidos: list[dict] = []
    if root.exists():
        for f in sorted(root.rglob("*")):
            try:
                if not f.is_file() or f.stat().st_size > _MAX_FILE:
                    continue
                rel = f.relative_to(root)
            except OSError:
                continue
            if rel.parts and rel.parts[0] in _EXCLUDE_DIRS:
                continue
            # as_posix(): el zip guarda «/» y en Windows str(rel) daría «\», con
            # lo que el manifiesto y la restauración no casarían.
            arc = rel.as_posix()
            if arc == MANIFIESTO:
                omitidos.append({"ruta": arc,
                                 "motivo": "ese nombre está reservado para el manifiesto de la copia"})
                continue
            try:
                n, digest = _sha256_de(f)
            except OSError as exc:
                omitidos.append({"ruta": arc, "motivo": f"no se pudo leer: {exc}"})
                continue
            archivos.append({"ruta": arc, "bytes": n, "sha256": digest, "origen": f})

    manifiesto = {
        "formato": FORMATO_MANIFIESTO,
        "version": VERSION_MANIFIESTO,
        "creado": dt.datetime.now().isoformat(timespec="seconds"),
        "raiz": "data/",
        "archivos": [{k: v for k, v in a.items() if k != "origen"} for a in archivos],
        "total_archivos": len(archivos),
        "total_bytes": sum(a["bytes"] for a in archivos),
        "omitidos": omitidos,
        "cifrado": False,
        "nota": AVISO_SIN_CIFRAR,
    }

    tmp = out.with_name(out.name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for a in archivos:
                z.write(a["origen"], a["ruta"])
            z.writestr(MANIFIESTO, json.dumps(manifiesto, ensure_ascii=False, indent=1))
        tmp.replace(out)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    rotate_backups()
    return out, len(archivos)


def destino_extra_configurado() -> str:
    """La carpeta del segundo disco, tal como está en ⚙ (`backup_destino_extra`)."""
    try:
        from backend.core.comun.config import settings
        return (settings.get("backup_destino_extra") or "").strip()
    except Exception:                                          # noqa: BLE001
        return ""


def copiar_extra(zip_path, destino=None) -> dict:
    """Deja una SEGUNDA copia del zip en otro sitio (otro disco) y lo informa.

    `destino=None` lee `backup_destino_extra` de la configuración; vacío = no se
    copia nada (`ok: None`, no es un error). NUNCA lanza: que el segundo disco
    falle no puede llevarse por delante la copia local, que ya está hecha.
    """
    raw = destino if destino is not None else destino_extra_configurado()
    txt = str(raw or "").strip()
    out = {"ok": None, "destino": txt, "nombre": "", "bytes": 0, "error": ""}
    if not txt:
        out["error"] = "no hay segundo destino configurado (backup_destino_extra vacío)"
        return out
    origen = Path(zip_path)
    try:
        carpeta = Path(txt).expanduser()
        out["destino"] = str(carpeta)
        raiz_datos = Path(_dirs()[0]).resolve()
        destino_real = carpeta.resolve()
        if destino_real == raiz_datos or raiz_datos in destino_real.parents:
            out["ok"] = False
            out["error"] = ("el destino extra está DENTRO de data/: la copia acabaría "
                            "dentro de lo que se copia y se multiplicaría. Señala otro "
                            "disco o una carpeta de fuera de data/.")
            return out
        if destino_real == origen.parent.resolve():
            out["ok"] = False
            out["error"] = ("el destino extra es la MISMA carpeta de los backups: eso no "
                            "es una copia fuera del disco")
            return out
        carpeta.mkdir(parents=True, exist_ok=True)
        gemela = carpeta / origen.name
        shutil.copyfile(origen, gemela)
        tam = gemela.stat().st_size
        if tam != origen.stat().st_size:
            out["ok"] = False
            out["error"] = "la copia del segundo destino no tiene el mismo tamaño"
            return out
        out.update({"ok": True, "nombre": gemela.name, "bytes": tam})
    except Exception as exc:                                   # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def crear(destino_extra=None) -> dict:
    """La copia completa: zip + manifiesto (+ segunda copia fuera del disco).

    Es la puerta que usan la orden del operador y el scheduler. `destino_extra`
    se pasa a mano solo en las pruebas: en producción se lee de la configuración.
    """
    out, n = make_backup()
    copia = copiar_extra(out, destino_extra)
    return {"ruta": out, "nombre": out.name, "archivos": n,
            "bytes": out.stat().st_size, "copia_extra": copia}


def rotate_backups(keep: int = KEEP) -> int:
    """Borra las copias diarias más viejas dejando las últimas `keep`."""
    _root, dest = _dirs()
    zips = sorted(dest.glob("nexus-data-*.zip"))
    removed = 0
    for old in zips[:-keep] if len(zips) > keep else []:
        try:
            old.unlink()
            removed += 1
        except Exception:
            pass
    return removed


def list_backups() -> list[dict]:
    _root, dest = _dirs()
    out = []
    for f in sorted(dest.glob("*.zip"), reverse=True):
        out.append({"name": f.name, "mb": round(f.stat().st_size / 1e6, 2),
                    "date": dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M"),
                    "es_diaria": bool(_RX_DIARIA.match(f.name))})
    return out


# ─────────────────────── verificar el contenido (no la existencia) ──────────

def verificar_backup(zip_path) -> dict:
    """¿El contenido del zip coincide con su manifiesto?

    Relee el zip y compara tamaño y sha256 de CADA archivo, y avisa también de
    entradas que están en el archivo pero no en el manifiesto. Es la diferencia
    entre «existe un zip» y «este zip trae lo que se copió»."""
    ruta = Path(zip_path)
    out = {"ruta": str(ruta), "ok": False, "motivo": "", "verificados": 0,
           "bytes": 0, "manifiesto": False, "discrepancias": []}
    try:
        with zipfile.ZipFile(ruta) as z:
            try:
                man = json.loads(z.read(MANIFIESTO).decode("utf-8"))
            except KeyError:
                out["motivo"] = ("la copia no lleva manifiesto (se hizo con una versión "
                                 "anterior de nexus): se puede restaurar, pero no puedo "
                                 "demostrar que su contenido sea el original")
                return out
            except Exception:                                  # noqa: BLE001
                out["motivo"] = "el manifiesto está ilegible o corrupto"
                return out
            if (not isinstance(man, dict) or man.get("formato") != FORMATO_MANIFIESTO
                    or not isinstance(man.get("archivos"), list)):
                out["motivo"] = "el manifiesto no tiene el formato de una copia de nexus"
                return out
            out["manifiesto"] = True
            presentes = set(z.namelist())
            esperados = {}
            for a in man["archivos"]:
                if isinstance(a, dict) and isinstance(a.get("ruta"), str):
                    esperados[a["ruta"]] = a
            for arc, a in esperados.items():
                if arc not in presentes:
                    out["discrepancias"].append(
                        {"ruta": arc, "motivo": "el manifiesto lo nombra y NO está en el zip"})
                    continue
                info = z.getinfo(arc)
                if info.file_size != a.get("bytes"):
                    out["discrepancias"].append(
                        {"ruta": arc, "motivo": f"tamaño {info.file_size} ≠ {a.get('bytes')} "
                                                "del manifiesto"})
                    continue
                h = hashlib.sha256()
                with z.open(arc) as fh:
                    for trozo in iter(lambda: fh.read(_TROZO), b""):
                        h.update(trozo)
                if h.hexdigest() != a.get("sha256"):
                    out["discrepancias"].append(
                        {"ruta": arc, "motivo": "el sha256 no coincide con el del manifiesto"})
                    continue
                out["verificados"] += 1
                out["bytes"] += info.file_size
            for sobrante in sorted(presentes - set(esperados) - {MANIFIESTO}):
                if sobrante.endswith("/"):
                    continue
                out["discrepancias"].append(
                    {"ruta": sobrante, "motivo": "está en el zip pero NO en el manifiesto"})
            out["ok"] = not out["discrepancias"]
            out["motivo"] = (f"el contenido coincide con el manifiesto "
                             f"({out['verificados']} archivos, sha256 comprobado)"
                             if out["ok"] else "el contenido NO coincide con el manifiesto")
            return out
    except zipfile.BadZipFile:
        out["motivo"] = "el archivo está corrupto o no es un zip válido"
    except OSError as exc:
        out["motivo"] = f"no se pudo leer la copia: {exc}"
    return out


def estado_backups() -> dict:
    """El estado de la copia diaria MÁS RECIENTE, con su contenido verificado.

    Un listado de nombres dice «existe un zip». Esto dice «el último backup
    verificó OK» (o por qué no verificó), que es lo que sirve antes de fiarse de
    una copia."""
    _root, dest = _dirs()
    diarias = sorted((f for f in dest.glob("nexus-data-*.zip")), reverse=True)
    if not diarias:
        return {"nombre": "", "ruta": "", "verificado": False, "manifiesto": False,
                "motivo": "no hay ninguna copia diaria todavía", "archivos": 0,
                "bytes": 0, "discrepancias": [], "fecha": "", "total": 0}
    ultima = diarias[0]
    ver = verificar_backup(ultima)
    fecha = ""
    try:
        fecha = dt.datetime.fromtimestamp(
            ultima.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        pass
    return {"nombre": ultima.name, "ruta": str(ultima), "verificado": bool(ver["ok"]),
            "manifiesto": bool(ver["manifiesto"]), "motivo": ver["motivo"],
            "archivos": ver["verificados"], "bytes": ver["bytes"],
            "discrepancias": ver["discrepancias"], "fecha": fecha,
            "total": len(diarias)}


# ──────────────────────────── restaurar de verdad ───────────────────────────

def _fecha_de_nombre(nombre: str) -> str:
    """La fecha que el NOMBRE promete (`nexus-data-AAAAMMDD.zip`) → AAAA-MM-DD."""
    m = _RX_DIARIA.match(nombre or "")
    if not m:
        return ""
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _entrada_peligrosa(nombre: str) -> str:
    """Por qué esta entrada NO se puede escribir. '' si es segura.

    Es la guarda de zip-slip: ni rutas absolutas (unix, Windows o UNC) ni «..»
    que salga de la carpeta de destino. Se mira el nombre TAL CUAL viene en el
    índice del zip, sin normalizar a conveniencia."""
    n = (nombre or "").replace("\\", "/")
    if not n.strip():
        return "entrada sin nombre"
    if n.startswith("/") or n.startswith("~"):
        return "ruta absoluta"
    if re.match(r"^[A-Za-z]:", n):
        return "ruta absoluta (letra de unidad)"
    trozos = [t for t in n.split("/") if t not in ("", ".")]
    if any(t == ".." for t in trozos):
        return "salta fuera de la carpeta de destino con «..»"
    return ""


def previsualizar_restaurar(zip_path) -> dict:
    """Qué hay dentro de una copia, SIN extraer nada.

    Devuelve nombres, tamaños, cuántos son, la fecha que promete el nombre del
    archivo, si está vacía o truncada/corrupta, qué dice su manifiesto y si es
    (o no) una copia de datos de nexus, con el motivo cuando no lo es."""
    ruta = Path(zip_path)
    out = {"ruta": str(ruta), "nombre": ruta.name, "fecha": _fecha_de_nombre(ruta.name),
           "bytes": 0, "archivos": [], "total_archivos": 0, "total_bytes": 0,
           "vacio": False, "truncado": False, "es_backup": False, "motivo": "",
           "manifiesto": {"presente": False, "ok": False, "motivo": "",
                          "discrepancias": []},
           "cifrado": False, "aviso_cifrado": AVISO_SIN_CIFRAR, "peligrosas": []}
    if not ruta.is_file():
        out["motivo"] = f"no existe ninguna copia en {ruta}"
        return out
    try:
        out["bytes"] = ruta.stat().st_size
    except OSError:
        pass
    es_diaria = bool(_RX_DIARIA.match(ruta.name))
    es_baks = bool(_RX_BAKS.match(ruta.name))
    try:
        z = zipfile.ZipFile(ruta)
    except zipfile.BadZipFile:
        out["truncado"] = True
        out["motivo"] = ("el archivo no se abre como zip: está corrupto o se copió/"
                         "truncó a medias")
        return out
    except OSError as exc:
        out["motivo"] = f"no se pudo abrir la copia: {exc}"
        return out
    with z:
        try:
            infos = [i for i in z.infolist() if not i.is_dir()]
        except Exception:                                      # noqa: BLE001
            out["motivo"] = "el índice del zip está corrupto"
            out["truncado"] = True
            return out
        nombres = [i.filename for i in infos]
        tiene_manifiesto = MANIFIESTO in nombres
        # Lo PRIMERO es la seguridad de las rutas: un zip que se sale de la
        # carpeta de destino se rechaza por eso, diga lo que diga su nombre.
        for n in nombres:
            porque = _entrada_peligrosa(n)
            if porque:
                out["peligrosas"].append({"ruta": n, "motivo": porque})
        if out["peligrosas"]:
            primera = out["peligrosas"][0]
            out["motivo"] = (f"el zip lleva rutas que se saldrían de la carpeta de destino "
                             f"(«{primera['ruta']}»: {primera['motivo']}): no lo restauro")
            return out
        if not es_diaria and not tiene_manifiesto:
            if es_baks:
                out["motivo"] = ("eso es el archivo de copias .bak del proyecto "
                                 "(baks-…zip), no una copia de data/: no se restaura "
                                 "como si fueran datos")
            else:
                out["motivo"] = ("no es una copia de datos de nexus: ni el nombre es "
                                 "nexus-data-AAAAMMDD.zip ni lleva manifiesto de copia")
            return out
        malo = z.testzip()
        if malo is not None:
            out["truncado"] = True
            out["motivo"] = (f"el zip está corrupto o truncado: la entrada «{malo}» no "
                             "pasa la comprobación de integridad (CRC)")
            return out
        datos = [i for i in infos if i.filename != MANIFIESTO]
        out["archivos"] = [{"ruta": i.filename, "bytes": i.file_size} for i in datos]
        out["total_archivos"] = len(datos)
        out["total_bytes"] = sum(i.file_size for i in datos)
        if not datos:
            out["vacio"] = True
            out["motivo"] = "la copia está vacía: no hay ni un archivo de data/ dentro"
            return out
        out["es_backup"] = True

    ver = verificar_backup(ruta)
    out["manifiesto"] = {"presente": bool(ver["manifiesto"]), "ok": bool(ver["ok"]),
                         "motivo": ver["motivo"], "discrepancias": ver["discrepancias"]}
    if ver["manifiesto"] and not ver["ok"]:
        primera = (ver["discrepancias"] or [{"ruta": "?", "motivo": ver["motivo"]}])[0]
        out["es_backup"] = False
        out["motivo"] = (f"el contenido no coincide con el manifiesto: «{primera['ruta']}» "
                         f"({primera['motivo']}). No restauro algo que no puedo demostrar")
    return out


def _no_tocado() -> list[str]:
    return ["tu `data/` actual (los datos con los que nexus está funcionando ahora)",
            "`config/` (claves API, tokens de Google/Spotify, .env): no entra en la copia",
            "los zips de `data/backups/` (ni se leen ni se reescriben)"]


def restaurar(zip_path, destino) -> dict:
    """Restaura la copia en una carpeta NUEVA. Nunca encima de `data/`.

    Se niega (devolviendo `ok: False` y el motivo, sin extraer nada) si el
    archivo no es una copia de nexus, si está corrupto o truncado, si lleva
    rutas fuera del destino, si el manifiesto no cuadra o si el destino ya tiene
    contenido."""
    prev = previsualizar_restaurar(zip_path)
    out = {"ok": False, "motivo": "", "destino": str(destino), "archivos": 0,
           "bytes": 0, "no_tocado": _no_tocado(), "manifiesto": prev["manifiesto"]}
    if not prev["es_backup"]:
        out["motivo"] = prev["motivo"] or "no es una copia de datos de nexus"
        return out

    d = Path(destino).expanduser()
    raiz_datos = Path(_dirs()[0]).resolve()
    try:
        resuelto = d.resolve()
    except OSError:
        resuelto = d.absolute()
    if resuelto == raiz_datos or resuelto in raiz_datos.parents:
        out["motivo"] = (f"no restauro ENCIMA de data/ ni en una carpeta que lo contenga "
                         f"({resuelto}): esto va siempre a una carpeta nueva y aparte")
        return out
    if raiz_datos in resuelto.parents:
        out["motivo"] = (f"no restauro DENTRO de data/ ({resuelto}): los archivos "
                         "restaurados se mezclarían con los que nexus está usando y "
                         "entrarían en la próxima copia. Elige una carpeta de fuera")
        return out
    if d.exists():
        if not d.is_dir():
            out["motivo"] = f"el destino existe y no es una carpeta: {d}"
            return out
        try:
            dentro = list(d.iterdir())
        except OSError as exc:
            out["motivo"] = f"no puedo mirar el destino: {exc}"
            return out
        if dentro:
            out["motivo"] = (f"el destino ya tiene contenido ({len(dentro)} entrada(s) en "
                             f"{d}): no escribo encima. Elige una carpeta nueva o vacía")
            return out

    esperado = {}
    if prev["manifiesto"]["presente"]:
        try:
            with zipfile.ZipFile(prev["ruta"]) as z:
                man = json.loads(z.read(MANIFIESTO).decode("utf-8"))
            esperado = {a["ruta"]: a for a in man.get("archivos") or []
                        if isinstance(a, dict) and isinstance(a.get("ruta"), str)}
        except Exception:                                      # noqa: BLE001
            esperado = {}

    try:
        d.mkdir(parents=True, exist_ok=True)
        base = d.resolve()
    except OSError as exc:
        out["motivo"] = f"no se pudo crear el destino: {exc}"
        return out

    extraidos = 0
    bytes_ = 0
    fallos: list[dict] = []
    with zipfile.ZipFile(prev["ruta"]) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            nombre = info.filename
            if nombre == MANIFIESTO:
                continue
            porque = _entrada_peligrosa(nombre)
            if porque:
                fallos.append({"ruta": nombre, "motivo": porque})
                continue
            objetivo = (base / nombre).resolve()
            if objetivo != base and base not in objetivo.parents:
                fallos.append({"ruta": nombre,
                               "motivo": "quedaría fuera de la carpeta de destino"})
                continue
            escrito = 0
            h = hashlib.sha256()
            try:
                objetivo.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as origen, open(objetivo, "wb") as dst:
                    for trozo in iter(lambda: origen.read(_TROZO), b""):
                        h.update(trozo)
                        escrito += len(trozo)
                        dst.write(trozo)
            except OSError as exc:
                fallos.append({"ruta": nombre, "motivo": f"no se pudo escribir: {exc}"})
                continue
            esp = esperado.get(nombre)
            if esp and (h.hexdigest() != esp.get("sha256") or escrito != esp.get("bytes")):
                fallos.append({"ruta": nombre,
                               "motivo": "lo que hay dentro del zip no coincide con el manifiesto"})
                continue
            extraidos += 1
            bytes_ += escrito

    if fallos:
        primero = fallos[0]
        out["motivo"] = (f"no he podido restaurar entero: «{primero['ruta']}» "
                         f"({primero['motivo']}). Se han escrito {extraidos} archivo(s) "
                         f"en {d}; revísalo o borra esa carpeta y repite")
        out["archivos"] = extraidos
        out["bytes"] = bytes_
        return out

    out.update({"ok": True, "archivos": extraidos, "bytes": bytes_, "destino": str(d),
                "motivo": ("restaurado y verificado contra el manifiesto"
                           if prev["manifiesto"]["ok"] else
                           "restaurado SIN manifiesto: no puedo demostrar que sea el original")})
    return out


def _restaurar_y_contar(zip_path, destino) -> str:
    """Lo que se le contesta al operador cuando dice «sí» (acción de confirm.request)."""
    r = restaurar(zip_path, destino)
    if not r["ok"]:
        return (f"🛟 NO he restaurado nada: {r['motivo']}.\n"
                "Tu data/ y tu config/ siguen exactamente como estaban.")
    if r["manifiesto"].get("ok"):
        aviso = "El manifiesto cuadra: lo restaurado es exactamente lo que se copió."
    else:
        aviso = ("La copia no llevaba manifiesto (es de una versión anterior): no puedo "
                 "demostrar que su contenido sea el original.")
    return (f"🛟 Restaurado en {r['destino']}: {r['archivos']} archivos, {r['bytes']} bytes. "
            f"{aviso}\n"
            "NO he tocado: tu data/ actual, config/ (claves y tokens) ni los zips de "
            "data/backups/.\n"
            "Para USAR estos datos: cierra nexus, renombra «data» a «data_viejo» (no lo "
            "borres), renombra esta carpeta a «data» y vuelve a arrancar. Si algo no "
            "cuadra, «data_viejo» sigue ahí intacta.")


# ─────────────────────────── .bak sueltos del proyecto ──────────────────────

def project_root(explicit: Path | None = None) -> Path:
    from backend.core.comun.config import DATA_DIR
    return Path(explicit) if explicit else Path(DATA_DIR).parent


def find_baks(root: Path) -> list[Path]:
    """Los *.bak* sueltos de backend/, frontend/, skills/, tests/ y la raíz.
    Solo backups de verdad («x.py.bak», «x.py.bak_v75»), no «receta.baking.md»."""
    import re as _re
    baks: list[Path] = []
    for sub in ("backend", "frontend", "skills", "tests", "."):
        base = root / sub
        if not base.exists():
            continue
        it = base.rglob("*.bak*") if sub != "." else base.glob("*.bak*")
        for f in it:
            if (f.is_file() and _re.search(r"\.bak(?:_[A-Za-z0-9]+)?$", f.name)
                    and ".venv" not in f.parts and "backups" not in f.parts):
                baks.append(f)
    return sorted(set(baks))


def archive_baks(project_root_dir: Path | None = None) -> tuple[int, Path | None]:
    """Recoge los *.bak* sueltos en data/backups/baks-<fecha>.zip y BORRA los
    originales — solo si el zip se verifica íntegro. Devuelve (nº, ruta_zip).
    Destructivo: desde el chat solo se llama detrás de confirm.request()."""
    root = project_root(project_root_dir)
    _r, dest = _dirs()
    dest.mkdir(parents=True, exist_ok=True)
    baks = find_baks(root)
    if not baks:
        return 0, None
    out = dest / f"baks-{dt.date.today():%Y%m%d}.zip"
    with zipfile.ZipFile(out, "a", zipfile.ZIP_DEFLATED) as z:
        existing = set(z.namelist())
        for f in baks:
            # as_posix(): zipfile guarda los nombres con «/» y en Windows
            # str(ruta_relativa) da «\», con lo que la verificación no casaría.
            arc = f.relative_to(root).as_posix()
            if arc not in existing:
                z.write(f, arc)
    # verificación: el zip abre, no está corrupto y contiene TODO con su tamaño
    with zipfile.ZipFile(out) as z:
        if z.testzip() is not None:
            return 0, out
        names = set(z.namelist())
        for f in baks:
            arc = f.relative_to(root).as_posix()
            if arc not in names or z.getinfo(arc).file_size != f.stat().st_size:
                return 0, out
    for f in baks:
        try:
            f.unlink()
        except Exception:
            pass
    return len(baks), out


# ───────────── automático (lo llama el scheduler una vez al día) ─────────────

async def auto_backup() -> bool:
    """Copia diaria si aún no existe la de hoy. Silenciosa salvo en el log.

    NO pregunta NADA nunca: la llama el scheduler. La segunda copia de
    `backup_destino_extra` se intenta aquí también; si ese disco falla, se dice
    en el log y la copia local (ya hecha) no se toca."""
    _root, dest = _dirs()
    today = dest / f"nexus-data-{dt.date.today():%Y%m%d}.zip"
    if today.exists():
        return False
    try:
        import asyncio as _aio
        res = await _aio.to_thread(crear)   # el zip NO congela el HUD
        extra = res["copia_extra"]
        cola = ""
        if extra["ok"] is True:
            cola = f" + copia en {extra['destino']}"
        elif extra["ok"] is False:
            cola = f" (la copia al segundo disco FALLÓ: {extra['error']})"
        from backend.core.comun.events import bus
        await bus.emit("log", {"level": "ok",
                               "msg": f"🛟 Backup diario: {res['nombre']} "
                                      f"({res['archivos']} archivos){cola}"})
        return True
    except Exception:
        return False


async def handle(intent: str, text: str, match, ctx) -> dict:
    if intent == "make":
        import asyncio as _aio
        res = await _aio.to_thread(crear)
        out, n = res["ruta"], res["archivos"]
        mb = round(out.stat().st_size / 1e6, 2)
        ver = await _aio.to_thread(verificar_backup, out)
        if ver["ok"]:
            comprobacion = ("verificado: el contenido coincide con su manifiesto "
                            "(sha256 de cada archivo)")
        elif ver["manifiesto"]:
            comprobacion = f"⚠ no he podido verificar el contenido ({ver['motivo']})"
        else:
            comprobacion = "sin manifiesto que comparar"
        reply = (f"🛟 Copia de seguridad hecha: {out.name} — {n} archivos, {mb} MB "
                 f"(data/backups/). {comprobacion}. Guardo las últimas {KEEP} copias diarias.")
        extra = res["copia_extra"]
        if extra["ok"] is True:
            reply += (f"\nSegunda copia fuera del disco: {extra['destino']} "
                      f"({extra['nombre']}, mismo tamaño).")
        elif extra["ok"] is False:
            reply += (f"\n⚠ La copia al segundo destino (backup_destino_extra) NO se hizo: "
                      f"{extra['error']}. La copia local está hecha y verificada.")
        return {"reply": reply,
                "data": {"count": n, "verificado": ver["ok"], "copia_extra": extra["ok"]}}

    if intent == "list":
        items = list_backups()
        if not items:
            return {"reply": "🛟 No hay copias todavía. Di «haz una copia de seguridad» "
                             "(además, cada día hago una sola)."}
        lines = [f"  • {b['name']} — {b['mb']} MB ({b['date']})"
                 + (" [archivo de .bak, no rota]" if b["name"].startswith("baks-") else "")
                 for b in items[:10]]
        est = estado_backups()
        if not est["nombre"]:
            estado_txt = ""
        elif est["verificado"]:
            estado_txt = (f"\nEl último backup ({est['nombre']}) verificó OK: "
                          f"{est['archivos']} archivos, {est['bytes']} bytes, y el "
                          "manifiesto cuadra.")
        elif est["manifiesto"]:
            primera = (est["discrepancias"] or [{}])[0]
            estado_txt = (f"\n⚠ El último backup ({est['nombre']}) NO verifica: "
                          f"«{primera.get('ruta', '?')}» {primera.get('motivo', '')}. "
                          "Haz una copia nueva y no te fíes de ese zip.")
        else:
            estado_txt = (f"\nEl último backup ({est['nombre']}) no lleva manifiesto (es de "
                          "una versión anterior de nexus): se puede restaurar, pero no puedo "
                          "demostrar que su contenido sea el original.")
        return {"reply": f"🛟 Zips en data/backups/ ({len(items)}):\n" + "\n".join(lines) +
                         f"\nLa copia diaria (nexus-data-*) se hace sola y roto a {KEEP}."
                         + estado_txt +
                         "\nDi «restaura la copia de seguridad» y la dejo en una carpeta "
                         "nueva, enseñándote antes qué lleva (y sin tocar tu data/)."}

    if intent == "baks":
        # Archivar BORRA los originales: no se hace sin un sí explícito.
        from backend.core.comun import confirm
        root = project_root()
        baks = find_baks(root)
        if not baks:
            return {"reply": "🛟 No he encontrado archivos .bak sueltos: el proyecto está limpio."}

        def _ejecutar():
            n, out = archive_baks()
            if not n:
                return (f"⚠ He preparado {out.name} pero la verificación no cuadró: "
                        "NO he borrado nada. Revisa data/backups/ y repite.")
            return (f"🛟 {n} archivos .bak archivados en {out.name} y eliminados de las "
                    "carpetas de trabajo. Todo recuperable del zip.")

        muestra = "\n".join(f"    • {f.relative_to(root).as_posix()}" for f in baks[:12])
        resto = f"\n    … y {len(baks) - 12} más" if len(baks) > 12 else ""
        pregunta = (f"🛟 Voy a meter {len(baks)} archivo(s) .bak en un zip y BORRAR los "
                    f"originales:\n{muestra}{resto}\n"
                    "Solo borro si el zip se verifica íntegro. ¿Lo confirmas? «sí» o «no».")
        return {"reply": confirm.request(
            channel=(ctx.get("channel") or "pc"), kind="archivar_baks", summary=pregunta,
            action=_ejecutar, request_text=text,
            targets=[{"path": f.relative_to(root).as_posix()} for f in baks],
            cancel_reply="Vale, no toco ningún .bak."),
            "data": {"confirm": True, "count": len(baks)}}

    if intent == "restore":
        # Antes esto solo EXPLICABA los pasos. Ahora restaura de verdad, y con la
        # misma cultura de seguridad que la purga: primero la vista previa, luego
        # el «sí», y SIEMPRE a una carpeta nueva. Nunca encima del data/ vivo.
        from backend.core.comun import confirm
        items = list_backups()
        diaria = next((b for b in items if b["es_diaria"]), None)
        if not diaria:
            if items:
                return {"reply": "🛟 Solo hay archivos de .bak archivados (baks-…zip), no una "
                                 "copia de datos que restaurar. Di «haz una copia de "
                                 "seguridad» y a partir de ahí habrá algo a lo que volver."}
            return {"reply": "🛟 No tengo ninguna copia que restaurar. Di «haz una copia de "
                             "seguridad» y a partir de ahí habrá algo a lo que volver."}
        root, dest = _dirs()
        prev = previsualizar_restaurar(dest / diaria["name"])
        if not prev["es_backup"]:
            return {"reply": f"🛟 No puedo restaurar `{diaria['name']}`: {prev['motivo']}.\n"
                             "Tu data/ sigue como está: no he tocado nada.",
                    "data": {"confirm": False}}
        fecha = prev["fecha"] or "fecha desconocida"
        sufijo = prev["fecha"] or f"{dt.date.today():%Y-%m-%d}"
        destino = Path(root).parent / (f"restaurado-{sufijo}-"
                                       f"{dt.datetime.now():%H%M%S}")
        if prev["manifiesto"]["presente"] and prev["manifiesto"]["ok"]:
            integridad = ("Verificado: el contenido coincide con su manifiesto (sha256 por "
                          "archivo).")
        elif prev["manifiesto"]["presente"]:
            integridad = "⚠ El manifiesto NO cuadra; mejor no restaurar esto."
        else:
            integridad = ("Esta copia NO lleva manifiesto (es de una versión anterior): la "
                          "restauro tal cual, pero no puedo demostrar que sea el original.")
        lista = "\n".join(f"    • {a['ruta']} ({a['bytes']} bytes)"
                          for a in prev["archivos"][:10])
        resto = (f"\n    … y {prev['total_archivos'] - 10} más"
                 if prev["total_archivos"] > 10 else "")
        resumen = (
            f"🛟 Voy a restaurar `{diaria['name']}` — {prev['total_archivos']} archivos, "
            f"{round(prev['bytes'] / 1e6, 2)} MB de zip, del {fecha}.\n"
            f"{integridad}\n"
            f"Va a una carpeta NUEVA: {destino}\n"
            "Y NO toco nada de lo tuyo: tu data/ actual, tu config/ (claves y tokens) y "
            "los zips de data/backups/ se quedan como están.\n"
            "El zip NO va cifrado: su contenido es texto legible; config/ no está dentro.\n"
            f"Contenido:\n{lista}{resto}\n"
            "Después, para USAR los datos, hay que cerrar nexus y renombrar carpetas "
            "(te lo explico al terminar). ¿Lo confirmas? «sí» o «no».")
        return {"reply": confirm.request(
            channel=(ctx.get("channel") or "pc"), kind="restaurar_backup",
            summary=resumen, action=lambda: _restaurar_y_contar(prev["ruta"], destino),
            request_text=text, destructive=False,
            targets=[{"path": a["ruta"]} for a in prev["archivos"][:20]],
            cancel_reply="Vale, no restauro nada: todo sigue como estaba."),
            "data": {"confirm": True, "archivos": prev["total_archivos"]}}

    return {"reply": "Orden de backup no reconocida. Prueba «haz una copia de seguridad», "
                     "«qué copias de seguridad hay», «archiva los bak» (te pido "
                     "confirmación) o «restaura la copia de seguridad» (te la dejo en una "
                     "carpeta nueva, preguntándote antes)."}
