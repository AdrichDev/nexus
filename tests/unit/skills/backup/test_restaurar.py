# -*- coding: utf-8 -*-
"""Skill BACKUP — restaurar de verdad (P2-10 / PRIV-04), sin pisar los datos vivos.

Lo que había antes: la skill hacía el zip diario y, ante «restaura la copia de
seguridad», EXPLICABA unos pasos a mano. La auditoría (`07` §3, PRIV-04) anotó
las consecuencias: la restauración no se había ejecutado nunca, el RTO era
desconocido, los zips vivían en el MISMO disco que los datos y nadie sabía si un
zip restauraba algo.

Contrato nuevo, y lo que se comprueba aquí, siempre por la puerta pública:

  * el zip lleva un MANIFIESTO (ruta, tamaño y sha256 de cada archivo) y
    `previsualizar_restaurar()` enseña qué hay dentro sin extraer nada;
  * `restaurar()` escribe en una carpeta NUEVA, byte a byte, y NO toca el `data/`
    actual ni `config/` — esa es la propiedad anti-pisotón;
  * se niega en firme con zip-slip (`..` o rutas absolutas), con un zip corrupto
    o truncado, con uno que no es de nexus, con un destino que ya tiene
    contenido y con un manifiesto que no cuadra (y dice QUÉ entrada falla);
  * desde el chat, restaurar pasa por `confirm.request()`: antes del «sí» no se
    extrae ni un byte, y un «no» no extrae nada;
  * la copia opcional a otro disco (`backup_destino_extra`) se hace, y si ese
    segundo disco falla, la copia local sigue siendo buena y se dice.

Todo ocurre en árboles `mktemp -d`: ni el `data/`, ni el `config/`, ni los
backups del operador se leen, se escriben ni se borran.

Ejecutar: .venv\\Scripts\\python.exe tests\\unit\\skills\\backup\\test_restaurar.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ANTES de importar backend.core.comun.config: la suite no puede leer el data/ ni
# el config/ del operador (el config/ lleva secrets.json).
TMP = Path(tempfile.mkdtemp(prefix="nexus_restaurar_"))
os.environ["NEXUS_DATA_DIR"] = str(TMP / "data_env")
os.environ["NEXUS_CONFIG_DIR"] = str(TMP / "config_env")

from backend.core.comun import config as cfg          # noqa: E402
from backend.core.comun import confirm                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_fail: list[str] = []
_ok = 0


def check(cond, msg):
    global _ok
    if cond:
        _ok += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


# ─────────────────────────────── utilidades ────────────────────────────────
def sha(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def foto(base: Path) -> dict:
    """(ruta → tamaño, sha256, mtime_ns) de TODO el árbol. Para demostrar que no
    se ha tocado ni un byte."""
    out = {}
    if not base.exists():
        return out
    for f in sorted(base.rglob("*")):
        if f.is_file():
            st = f.stat()
            out[f.relative_to(base).as_posix()] = (st.st_size, sha(f), st.st_mtime_ns)
    return out


def arbol_sintetico(base: Path) -> None:
    """Un data/ con lo típico: nota con acentos, tablero, RAG y dos cosas que la
    copia SIEMPRE ha excluido (el perfil de Chrome y los propios backups)."""
    (base / "memory").mkdir(parents=True, exist_ok=True)
    (base / "rag").mkdir(parents=True, exist_ok=True)
    (base / "backups").mkdir(parents=True, exist_ok=True)
    (base / "chrome_nexus").mkdir(parents=True, exist_ok=True)
    (base / "memory" / "nota.md").write_text(
        "# Información confidencial\n\nMañana el ñandú come piña en A Coruña — «cita» clave.\n",
        encoding="utf-8")
    (base / "board.json").write_text(
        json.dumps({"tasks": [{"id": "t1", "title": "Revisar el año"}]}, ensure_ascii=False),
        encoding="utf-8")
    (base / "rag" / "knowledge.jsonl").write_text(
        json.dumps({"txt": "el ñandú come piña"}, ensure_ascii=False) + "\n", encoding="utf-8")
    (base / "chrome_nexus" / "perfil.bin").write_bytes(b"\x00perfil")
    (base / "backups" / "nexus-data-20200101.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)


class _DobleConfirm:
    """confirm.request/answer con la auditoría recogida en memoria (mismo estilo
    que tests/unit/skills/n8n_flows/test_envios.py)."""

    def __init__(self):
        self.auditorias: list[dict] = []
        self._audit_previo = None

    def __enter__(self):
        self._audit_previo = confirm._audit
        confirm.clear()
        confirm._audit = lambda **kw: self.auditorias.append(kw)
        return self

    def __exit__(self, *a):
        confirm._audit = self._audit_previo
        confirm.clear()
        return False

    @staticmethod
    def responder(texto: str, canal: str = "pc"):
        return asyncio.run(confirm.answer(texto, canal))


def cargar_modulo():
    """Carga SOLO la skill de backup, por ruta.

    No se usa `skills_loader.load_skills()` (que importa TODAS las skills y es
    lo que etiqueta de `unsafe-legacy` a `test_skill_backup.py`): esta suite
    solo necesita este módulo y así puede correr también en CI."""
    import importlib.util
    ruta = Path(ROOT) / "skills" / "backup" / "skill.py"
    spec = importlib.util.spec_from_file_location("skill_backup_t17", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════ 1) manifiesto + vista previa ═══════════════════
def test_crear_lleva_manifiesto_y_la_previa_lo_enseña(mod):
    data = TMP / "d1"
    arbol_sintetico(data)
    cfg.DATA_DIR = data

    out, n = mod.make_backup()
    check(out.exists(), f"la copia existe: {out}")
    check(n == 3, f"cuenta 3 archivos de datos (ni el perfil de Chrome ni los backups): n={n}")

    with zipfile.ZipFile(out) as z:
        nombres = z.namelist()
    check(mod.MANIFIESTO in nombres, "el zip lleva el manifiesto dentro")
    check(len(nombres) == 4, f"3 archivos + 1 manifiesto: {sorted(nombres)}")

    with zipfile.ZipFile(out) as z:
        man = json.loads(z.read(mod.MANIFIESTO).decode("utf-8"))
    check(man.get("formato") == mod.FORMATO_MANIFIESTO,
          f"el manifiesto dice qué es: {man.get('formato')!r}")
    check(man.get("version") == mod.VERSION_MANIFIESTO, "y con qué versión")
    rutas = [a["ruta"] for a in man["archivos"]]
    check(sorted(rutas) == ["board.json", "memory/nota.md", "rag/knowledge.jsonl"],
          f"el manifiesto lista los 3 archivos de datos: {rutas}")
    nota = [a for a in man["archivos"] if a["ruta"] == "memory/nota.md"][0]
    check(nota["bytes"] == (data / "memory" / "nota.md").stat().st_size,
          "con su tamaño REAL")
    check(nota["sha256"] == sha(data / "memory" / "nota.md"),
          "y su sha256 REAL (no un relleno)")
    check(man.get("total_archivos") == 3 and man.get("total_bytes", 0) > 0,
          "y los totales")

    print("· previsualizar_restaurar() enseña el contenido sin extraer nada")
    antes = foto(data)
    prev = mod.previsualizar_restaurar(out)
    check(prev["es_backup"] is True, f"reconoce una copia de datos: {prev.get('motivo')!r}")
    check(prev["fecha"] == f"{dt.date.today():%Y-%m-%d}",
          f"la fecha la saca del NOMBRE del archivo: {prev['fecha']!r}")
    check(prev["total_archivos"] == 3, f"cuenta los archivos: {prev['total_archivos']}")
    check(prev["total_bytes"] == sum((data / r).stat().st_size for r in
                                     ("memory/nota.md", "board.json", "rag/knowledge.jsonl")),
          "y los bytes, sumando los del manifiesto")
    nombres = {a["ruta"] for a in prev["archivos"]}
    check("memory/nota.md" in nombres, f"nombra cada archivo: {sorted(nombres)}")
    check(all(a["bytes"] > 0 for a in prev["archivos"]), "cada uno con su tamaño")
    check(prev["vacio"] is False and prev["truncado"] is False, "no está vacío ni truncado")
    check(prev["manifiesto"]["ok"] is True, "y el manifiesto verifica")
    check(foto(data) == antes, "la vista previa NO extrae ni toca nada")
    check(prev["cifrado"] is False and prev["aviso_cifrado"],
          "dice la verdad sobre el cifrado (no lo finge)")

    print("· verificar_backup() y estado_backups() prueban el contenido, no la existencia")
    ver = mod.verificar_backup(out)
    check(ver["ok"] is True and ver["verificados"] == 3,
          f"verifica los 3 archivos: {ver}")
    est = mod.estado_backups()
    check(est["verificado"] is True, f"el estado dice que el último verificó: {est}")
    check(est["nombre"] == out.name, "y nombra CUÁL")
    return out


# ═══════════════════════ 2) restaurar byte a byte, sin pisar ═══════════════
def test_restaurar_byte_a_byte_y_sin_tocar_el_data_vivo(mod, zip_path):
    data = TMP / "d1"
    destino = TMP / "copia-restaurada-1"
    antes_copia = foto(data)
    check(not destino.exists(), "el destino NO existe antes de restaurar")

    print("· restaurar() escribe en una carpeta NUEVA")
    r = mod.restaurar(zip_path, destino)
    check(r.get("ok") is True, f"restaura: {r.get('motivo')!r}")
    check(r["archivos"] == 3, f"3 archivos restaurados: {r['archivos']}")
    check(r["bytes"] > 0, f"y dice cuántos bytes: {r['bytes']}")
    check(Path(r["destino"]) == destino, "devuelve a dónde lo ha dejado")
    check(not (destino / mod.MANIFIESTO).exists(),
          "el manifiesto no se escribe como si fuera un dato del operador")

    print("· y lo restaurado es IDÉNTICO, acentos incluidos")
    for rel in ("memory/nota.md", "board.json", "rag/knowledge.jsonl"):
        a, b = data / rel, destino / rel
        check(b.is_file(), f"{rel} está en la carpeta restaurada")
        if b.is_file():
            check(a.read_bytes() == b.read_bytes(), f"{rel} byte a byte")
            check(sha(a) == sha(b), f"{rel} con el mismo sha256")
    nota = (destino / "memory" / "nota.md").read_text(encoding="utf-8")
    check("ñandú" in nota and "A Coruña" in nota,
          "los acentos y la eñe sobreviven al viaje (UTF-8)")

    print("· el data/ ACTUAL sigue intacto: eso es lo que evita el pisotón")
    check(foto(data) == antes_copia, "el árbol de datos no ha cambiado ni un byte")
    check((data / "memory" / "nota.md").read_text(encoding="utf-8").startswith(
        "# Información confidencial"), "la nota viva sigue siendo la del operador")
    check((data / "backups" / "nexus-data-20200101.zip").exists(),
          "y los backups siguen donde estaban")

    print("· y dice qué NO ha tocado")
    no_tocado = " | ".join(r.get("no_tocado") or [])
    check("data/" in no_tocado, f"nombra el data/ vivo: {no_tocado}")
    check("config/" in no_tocado, "nombra el config/ (secretos y tokens)")

    print("· el config/ del operador NO está en la copia (comprobado, no supuesto)")
    cfg_dir = TMP / "config_env"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "secrets.json").write_text('{"openai_api_key": "NO-ES-UNA-CLAVE"}',
                                          encoding="utf-8")
    cfg.CONFIG_DIR = cfg_dir
    cfg.DATA_DIR = data
    out2, _n2 = mod.make_backup()
    with zipfile.ZipFile(out2) as z:
        dentro = z.namelist()
    check(not any(x.startswith("config/") for x in dentro),
          f"ningún config/ dentro del zip: {dentro}")
    check("secrets.json" not in " ".join(dentro), "y desde luego ningún secrets.json")
    check(not any("secrets" in x for x in dentro), "ninguna entrada con «secrets»")


# ══════════════════════════ 3) zip-slip: se niega ══════════════════════════
def test_zip_slip_se_niega_en_firme(mod):
    fuera = TMP / "fuera"
    fuera.mkdir(parents=True, exist_ok=True)
    caso = {
        "salta-con-puntos.zip": "../evil.txt",
        "ruta-absoluta-unix.zip": "/tmp/evil.txt",
        "ruta-absoluta-windows.zip": "C:/evil.txt",
    }
    for nombre, entrada in caso.items():
        z_path = TMP / nombre
        with zipfile.ZipFile(z_path, "w") as z:
            z.writestr(entrada, "soy malo")
            z.writestr("board.json", "{}")
        prev = mod.previsualizar_restaurar(z_path)
        check(prev["es_backup"] is False,
              f"«{nombre}»: la vista previa lo rechaza ({prev.get('motivo')!r})")
        check("evil" in (prev.get("motivo") or "") or entrada in (prev.get("motivo") or ""),
              f"«{nombre}»: el motivo nombra la entrada peligrosa: {prev.get('motivo')!r}")

        destino = TMP / f"destino-{nombre}"
        r = mod.restaurar(z_path, destino)
        check(r.get("ok") is False, f"«{nombre}»: restaurar también lo rechaza")
        check(r.get("motivo"), f"«{nombre}»: y da un motivo: {r.get('motivo')!r}")
        check(not (TMP / "evil.txt").exists(),
              f"«{nombre}»: no se ha escrito nada fuera del destino")
        check(not (TMP.parent / "evil.txt").exists(),
              f"«{nombre}»: tampoco un nivel más arriba")
        check(not destino.exists() or not any(destino.iterdir()),
              f"«{nombre}»: el destino quedó vacío, sin extracción a medias")


# ═══════════════════ 4) corrupto, truncado y «no es de nexus» ═══════════════
def test_corrupto_truncado_y_ajeno_se_niegan(mod, zip_path):
    print("· un zip truncado a la mitad")
    roto = TMP / "nexus-data-20260101.zip"
    roto.write_bytes(Path(zip_path).read_bytes()[:200])
    prev = mod.previsualizar_restaurar(roto)
    check(prev["es_backup"] is False, f"no vale como copia: {prev.get('motivo')!r}")
    check(prev["truncado"] is True or "corrupt" in (prev.get("motivo") or "").lower(),
          f"y lo dice: {prev.get('motivo')!r}")
    r = mod.restaurar(roto, TMP / "destino-roto")
    check(r.get("ok") is False and r.get("motivo"),
          f"restaurar se niega con motivo: {r.get('motivo')!r}")

    print("· basura que ni es zip")
    basura = TMP / "nexus-data-20260102.zip"
    basura.write_bytes(b"estas no son las cabeceras de un zip")
    prev = mod.previsualizar_restaurar(basura)
    check(prev["es_backup"] is False and "zip" in (prev.get("motivo") or "").lower(),
          f"se niega y dice que no es un zip: {prev.get('motivo')!r}")

    print("· un zip perfectamente válido que NO es una copia de nexus")
    ajeno = TMP / "fotos-de-vacaciones.zip"
    with zipfile.ZipFile(ajeno, "w") as z:
        z.writestr("fotos/playa.jpg", "no soy un backup")
    prev = mod.previsualizar_restaurar(ajeno)
    check(prev["es_backup"] is False, "se niega")
    check("no es una copia" in (prev.get("motivo") or "").lower()
          or "nexus" in (prev.get("motivo") or "").lower(),
          f"y explica por qué: {prev.get('motivo')!r}")
    r = mod.restaurar(ajeno, TMP / "destino-ajeno")
    check(r.get("ok") is False and not (TMP / "destino-ajeno").exists(),
          "restaurar no crea ni la carpeta")

    print("· el zip de .bak archivados tampoco se restaura como si fuera data/")
    baks = TMP / "baks-20260101.zip"
    with zipfile.ZipFile(baks, "w") as z:
        z.writestr("skills/x/skill.py.bak_v9", "viejo")
    prev = mod.previsualizar_restaurar(baks)
    check(prev["es_backup"] is False, "se niega")
    check(".bak" in (prev.get("motivo") or ""), f"y dice qué es: {prev.get('motivo')!r}")


# ═══════════════ 4b) las copias VIEJAS (sin manifiesto) siguen valiendo ══
def test_copia_vieja_sin_manifiesto_se_restaura(mod):
    """Las copias que ya están en el equipo se hicieron SIN manifiesto: se tienen
    que poder previsualizar y restaurar igual, diciendo que su contenido no se
    puede demostrar. Si no, la corrección habría dejado huérfanas las 7 copias."""
    vieja = TMP / "nexus-data-20250101.zip"
    with zipfile.ZipFile(vieja, "w") as z:
        z.writestr("board.json", "{}")
        z.writestr("memory/vieja.md", "nota de enero")
    prev = mod.previsualizar_restaurar(vieja)
    check(prev["es_backup"] is True,
          f"una copia antigua sigue siendo válida: {prev.get('motivo')!r}")
    check(prev["manifiesto"]["presente"] is False, "pero se ve que NO lleva manifiesto")
    check(prev["total_archivos"] == 2, f"y cuenta sus archivos: {prev['total_archivos']}")
    check(prev["fecha"] == "2025-01-01", f"la fecha sale del NOMBRE: {prev['fecha']!r}")

    destino = TMP / "copia-vieja-restaurada"
    r = mod.restaurar(vieja, destino)
    check(r.get("ok") is True, f"y se restaura sin manifiesto: {r.get('motivo')!r}")
    check((destino / "memory" / "vieja.md").read_text(encoding="utf-8") == "nota de enero",
          "con su contenido intacto")
    check("no puedo demostrar" in r["motivo"],
          f"diciendo que no puede demostrar el original: {r['motivo']!r}")
    ver = mod.verificar_backup(vieja)
    check(ver["ok"] is False and ver["manifiesto"] is False,
          "verificar() no finge: sin manifiesto no hay verificación")


# ═════════════════════════ 5) destino ya ocupado ═══════════════════════════
def test_destino_con_contenido_se_niega(mod, zip_path):
    destino = TMP / "destino-ocupado"
    destino.mkdir(parents=True, exist_ok=True)
    ocupante = destino / "algo-mio.txt"
    ocupante.write_text("no me pises", encoding="utf-8")

    r = mod.restaurar(zip_path, destino)
    check(r.get("ok") is False, "un destino con contenido se rechaza")
    check("vacía" in (r.get("motivo") or "") or "vacia" in (r.get("motivo") or "")
          or "contenido" in (r.get("motivo") or ""),
          f"y se explica: {r.get('motivo')!r}")
    check(ocupante.read_text(encoding="utf-8") == "no me pises",
          "el archivo que ya estaba sigue igual")
    check(sorted(p.name for p in destino.iterdir()) == ["algo-mio.txt"],
          f"y no se ha añadido nada: {sorted(p.name for p in destino.iterdir())}")

    print("· y no se restaura ENCIMA de data/ ni de una carpeta que lo contenga")
    cfg.DATA_DIR = TMP / "d1"
    for prohibido in (TMP / "d1", TMP):
        r = mod.restaurar(zip_path, prohibido)
        check(r.get("ok") is False, f"destino prohibido rechazado: {prohibido}")
    dentro = TMP / "d1" / "restaurado-dentro"
    r = mod.restaurar(zip_path, dentro)
    check(r.get("ok") is False, "ni DENTRO de data/: se mezclaría con los datos vivos")
    check(not dentro.exists(), "y no ha creado la carpeta")


# ═════════════════════ 6) manifiesto que no cuadra ═════════════════════════
def test_manifiesto_alterado_se_niega_y_dice_cual(mod, zip_path):
    data = TMP / "d1"
    alterado = TMP / "nexus-data-20991231.zip"
    with zipfile.ZipFile(zip_path) as src, zipfile.ZipFile(alterado, "w") as dst:
        for info in src.infolist():
            datos = src.read(info.filename)
            if info.filename == "memory/nota.md":
                datos = datos + "\ny una línea que nadie copió".encode("utf-8")
            dst.writestr(info.filename, datos)

    prev = mod.previsualizar_restaurar(alterado)
    check(prev["manifiesto"]["ok"] is False,
          f"la vista previa detecta que el contenido no es el del manifiesto: "
          f"{prev['manifiesto']}")
    check(prev["manifiesto"]["discrepancias"], "y dice cuáles son las discrepancias")
    r = mod.restaurar(alterado, TMP / "destino-alterado")
    check(r.get("ok") is False, "restaurar se niega con el manifiesto roto")
    check("memory/nota.md" in (r.get("motivo") or ""),
          f"y NOMBRA la entrada que no cuadra: {r.get('motivo')!r}")
    check(not (TMP / "destino-alterado").exists(), "no se ha extraído nada")
    with zipfile.ZipFile(alterado) as z:
        check("nadie copió" in z.read("memory/nota.md").decode("utf-8"),
              "control: dentro del zip alterado la nota SÍ lleva la línea añadida")


# ═══════════════════════ 7) la puerta del «sí» en el chat ══════════════════
def test_confirmacion_antes_de_extraer(mod, zip_path):
    data = TMP / "d7"
    arbol_sintetico(data)
    cfg.DATA_DIR = data
    # El zip diario vivirá en data/backups, como en producción.
    (data / "backups").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(zip_path, data / "backups" / Path(zip_path).name)

    with _DobleConfirm() as doble:
        antes = foto(TMP)
        r = asyncio.run(mod.handle("restore", "restaura la copia de seguridad",
                                  None, {"channel": "pc"}))
        respuesta = r["reply"]
        pend = confirm.pending("pc")
        check(pend is not None, "restaurar deja una confirmación ARMADA")
        check(pend and pend["kind"] == "restaurar_backup", f"con su tipo: {pend and pend['kind']}")
        check(pend and pend["destructive"] is False,
              "no es destructivo: escribe en una carpeta nueva, no encima de la tuya")
        check("¿Lo confirmas?" in respuesta, f"pregunta antes de nada: {respuesta!r}")
        check("NUEVA" in respuesta.upper(), "dice que la carpeta es nueva")
        check(str(data) in respuesta or "restaurado-" in respuesta,
              "y ENSEÑA dónde va a dejar los archivos")
        check("no toco" in respuesta.lower() or "NO toco" in respuesta,
              "y avisa de que no toca los datos vivos")
        check(foto(TMP) == antes, "antes del «sí» NO se ha extraído ni un byte")
        destino_dicho = pend and pend["summary"] and True
        check(bool(destino_dicho), "la pregunta lleva el resumen honesto")

        print("· si dices que NO, no se extrae nada")
        no = doble.responder("no")
        check(no is not None and "no" in no.lower(), f"contesta al «no»: {no!r}")
        check(foto(TMP) == antes, "y el árbol sigue exactamente igual")
        check(not list(TMP.glob("restaurado-*")), "no ha aparecido ninguna carpeta restaurada")
        check(confirm.pending("pc") is None, "la confirmación se ha desarmado")

        print("· si dices que SÍ, se restaura en la carpeta nueva")
        r = asyncio.run(mod.handle("restore", "restaura la copia de seguridad",
                                  None, {"channel": "pc"}))
        check(confirm.pending("pc") is not None, "vuelve a armarse")
        si = doble.responder("sí")
        check(si is not None and "Restaurado" in si, f"informa del resultado: {si!r}")
        check("data/" in si and "config/" in si,
              "y repite qué NO ha tocado (data/ y config/)")
        nuevas = list(TMP.glob("restaurado-*"))
        check(len(nuevas) == 1, f"hay UNA carpeta restaurada: {nuevas}")
        if nuevas:
            check((nuevas[0] / "memory" / "nota.md").is_file(),
                  "con la nota dentro")
            check(sha(nuevas[0] / "memory" / "nota.md") ==
                  sha(data / "memory" / "nota.md"),
                  "byte a byte idéntica a la que se copió")
        check((data / "memory" / "nota.md").is_file(),
              "y el data/ vivo sigue teniendo su nota")
        acciones = [a.get("action", "") for a in doble.auditorias]
        check("confirm_executed:restaurar_backup" in acciones,
              f"la ejecución queda auditada: {acciones}")


# ═══════════════════ 8) copia al segundo disco (off-disk) ══════════════════
def test_destino_extra_copia_y_su_fallo_no_rompe_nada(mod):
    data = TMP / "d2"
    arbol_sintetico(data)
    cfg.DATA_DIR = data
    otro_disco = TMP / "otro_disco"
    otro_disco.mkdir(parents=True, exist_ok=True)

    print("· con destino_extra se escribe una SEGUNDA copia en otro sitio")
    res = mod.crear(destino_extra=str(otro_disco))
    check(res["ruta"].exists(), f"la copia local existe: {res['ruta']}")
    check(res["archivos"] == 3, f"con sus 3 archivos: {res['archivos']}")
    copia = res["copia_extra"]
    check(copia["ok"] is True, f"y la copia extra se hizo: {copia}")
    gemela = otro_disco / res["nombre"]
    check(gemela.is_file(), f"está en el otro destino: {gemela}")
    check(gemela.stat().st_size == res["ruta"].stat().st_size,
          "con el mismo tamaño que la local")
    check(sha(gemela) == sha(res["ruta"]), "y el mismo contenido (sha256)")

    print("· sin configurar, no se copia a ningún sitio y no se queja")
    for f in (data / "backups").glob("nexus-data-*.zip"):
        f.unlink()
    res0 = mod.crear()
    check(res0["copia_extra"]["ok"] is None,
          f"sin destino configurado: no hay copia extra ({res0['copia_extra']})")

    print("· si el segundo disco falla, la copia LOCAL sigue siendo buena")
    un_fichero = TMP / "esto-no-es-una-carpeta"
    un_fichero.write_text("no soy un directorio", encoding="utf-8")
    for f in (data / "backups").glob("nexus-data-*.zip"):
        f.unlink()
    res2 = mod.crear(destino_extra=str(un_fichero))
    check(res2["ruta"].exists(), "la copia local se hizo igualmente")
    check(mod.verificar_backup(res2["ruta"])["ok"] is True,
          "y verifica: no se ha quedado a medias")
    check(res2["copia_extra"]["ok"] is False,
          f"la copia extra se declara FALLIDA: {res2['copia_extra']}")
    check(res2["copia_extra"].get("error"), "con el motivo del fallo, no en silencio")

    print("· y la respuesta al operador lo dice, sin drama")
    previo = dict(cfg.settings._json)
    cfg.settings._json["backup_destino_extra"] = str(otro_disco)
    try:
        r = asyncio.run(mod.handle("make", "haz una copia de seguridad", None,
                                   {"channel": "pc"}))
        check("Copia de seguridad hecha" in r["reply"], f"informa de la local: {r['reply']!r}")
        check("otro_disco" in r["reply"] or "segunda copia" in r["reply"].lower(),
              f"y de la segunda copia: {r['reply']!r}")

        cfg.settings._json["backup_destino_extra"] = str(un_fichero)
        r = asyncio.run(mod.handle("make", "haz una copia de seguridad", None,
                                   {"channel": "pc"}))
        check("Copia de seguridad hecha" in r["reply"],
              f"la local se declara hecha: {r['reply']!r}")
        check("NO" in r["reply"] or "no se ha podido" in r["reply"].lower()
              or "fall" in r["reply"].lower(),
              f"y se dice que la copia al segundo disco falló: {r['reply']!r}")
    finally:
        cfg.settings._json.clear()
        cfg.settings._json.update(previo)


# ═══════════════ 9) la copia diaria del scheduler no se vuelve interactiva ══
def test_el_scheduler_no_pregunta_nada(mod):
    data = TMP / "d3"
    arbol_sintetico(data)
    cfg.DATA_DIR = data
    (data / "backups").mkdir(parents=True, exist_ok=True)
    with _DobleConfirm() as doble:
        hecho = asyncio.run(mod.auto_backup())
        check(hecho is True, "la copia diaria se hace sola")
        check(confirm.pending("pc") is None,
              "y NO deja ninguna confirmación armada (el scheduler no habla con nadie)")
        check(all("confirm" not in a.get("action", "") for a in doble.auditorias),
              "ni pasa por confirm.request")
        otra = asyncio.run(mod.auto_backup())
        check(otra is False, "una segunda pasada el mismo día no rehace la copia")
        zips = list((data / "backups").glob(f"nexus-data-{dt.date.today():%Y%m%d}.zip"))
        check(len(zips) == 1, f"solo hay un zip del día: {[z.name for z in zips]}")

    print("· y el zip que dejó el scheduler verifica igual que uno pedido a mano")
    ver = mod.verificar_backup(zips[0])
    check(ver["ok"] is True and ver["verificados"] == 3,
          f"el zip automático lleva manifiesto que cuadra: {ver}")


# ═════════════════════════════════ main ════════════════════════════════════
def main():
    try:
        mod = cargar_modulo()
        print(f"· módulo cargado: {Path(mod.__file__).name}")

        zip_principal = None
        pasos = [
            ("manifiesto y vista previa",
             lambda: test_crear_lleva_manifiesto_y_la_previa_lo_enseña(mod)),
        ]
        for nombre, paso in pasos:
            print(f"· {nombre}")
            try:
                zip_principal = paso()
            except Exception as exc:                       # noqa: BLE001
                check(False, f"{nombre} reventó: {type(exc).__name__}: {exc}")

        resto = [
            ("restaurar byte a byte sin pisar",
             lambda: test_restaurar_byte_a_byte_y_sin_tocar_el_data_vivo(mod, zip_principal)),
            ("zip-slip", lambda: test_zip_slip_se_niega_en_firme(mod)),
            ("corrupto/truncado/ajeno",
             lambda: test_corrupto_truncado_y_ajeno_se_niegan(mod, zip_principal)),
            ("copia vieja sin manifiesto",
             lambda: test_copia_vieja_sin_manifiesto_se_restaura(mod)),
            ("destino ocupado", lambda: test_destino_con_contenido_se_niega(mod, zip_principal)),
            ("manifiesto alterado",
             lambda: test_manifiesto_alterado_se_niega_y_dice_cual(mod, zip_principal)),
            ("confirmación", lambda: test_confirmacion_antes_de_extraer(mod, zip_principal)),
            ("segundo disco", lambda: test_destino_extra_copia_y_su_fallo_no_rompe_nada(mod)),
            ("scheduler", lambda: test_el_scheduler_no_pregunta_nada(mod)),
        ]
        for nombre, paso in resto:
            print(f"· {nombre}")
            if zip_principal is None and "scheduler" not in nombre:
                check(False, f"{nombre}: no hay zip de partida (el paso 1 falló)")
                continue
            try:
                paso()
            except Exception as exc:                       # noqa: BLE001
                check(False, f"{nombre} reventó: {type(exc).__name__}: {exc}")

        print(f"\n{'=' * 50}\n{_ok} pasados, {len(_fail)} fallados")
        return 1 if _fail else 0
    finally:
        shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
