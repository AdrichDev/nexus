# -*- coding: utf-8 -*-
r"""
nexus — REVISIÓN ANTES DE SUBIR A GITHUB.

Un secreto commiteado no se arregla borrando el archivo: queda en el historial
para siempre y hay que rotar la credencial. Así que se revisa ANTES, y si algo
huele a clave, esto ABORTA la subida.

Mira SOLO lo que git tiene preparado para subir (el índice), así que respeta el
.gitignore. Dos niveles:

  ✖ PELIGRO  → un nombre de archivo prohibido o un patrón inequívoco de clave.
               Aborta (código de salida 1). No se sube nada.
  ⚠ REVISA   → algo que PODRÍA ser una clave pero suele ser código legítimo
               (una variable llamada «token», un regex…). No aborta, se lista
               para que le eches un ojo.

Uso:
    .venv\Scripts\python.exe scripts\revisar_antes_de_subir.py          (desde la carpeta nexus)
    .venv\Scripts\python.exe scripts\revisar_antes_de_subir.py --json   (salida para otro programa)

Lo llama SUBIR_A_GITHUB.bat automáticamente.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Este archivo vive en scripts/, pero TODO lo que mira es relativo a la raíz del
# repositorio: `git ls-files` desde una subcarpeta solo listaría esa subcarpeta,
# y las rutas que devuelve git son relativas a la raíz. Si ROOT apuntara a
# scripts/, `ruta.is_file()` fallaría para todos los archivos y la revisión diría
# «LIMPIO» sin haber leído ni un byte: el peor fallo posible aquí.
ROOT = Path(__file__).resolve().parent.parent
LIMITE_BYTES = 2_000_000          # no se lee el contenido de archivos enormes
AVISO_TAMANO = 5_000_000          # se avisa de cualquier archivo de más de 5 MB

# ── 1. NOMBRES QUE NO PUEDEN ESTAR EN EL ÍNDICE, PASE LO QUE PASE ─────────────
NOMBRES_PROHIBIDOS = [
    (r"(^|/)\.env$", "el .env con tus claves reales"),
    (r"(^|/)config/secrets\.json", "el almacén de secretos"),
    (r"(^|/)config/settings\.json", "tu configuración real (lleva rutas y ajustes)"),
    (r"(^|/)config/.*token.*\.json", "un token de sesión"),
    (r"(^|/)config/.*credential.*\.json", "credenciales"),
    (r"(^|/)config/(docker-compose|ha-compose)\.yml", "una compose con contraseñas"),
    (r"\.(keystore|jks|p12|pfx|pem|crt)$", "una clave de firma o certificado"),
    (r"\.(key)$", "un archivo de clave"),
    (r"\.bak$|\.bak_v|\.backup$", "una COPIA de otro archivo (suele llevar lo mismo)"),
    (r"\.(wav|mp3|ogg|opus|m4a|aac|flac|mp4|mov|mkv)$", "audio o vídeo personal"),
    (r"transcripts\d*\.json$", "transcripciones de audio"),
    (r"WhatsApp", "material de WhatsApp"),
    (r"_b64\.txt$", "un volcado en base64 de otro archivo"),
    (r"\.(apk|aab|exe|msi)$", "un binario compilado"),
]
_NOMBRES_RX = [(re.compile(p, re.IGNORECASE), d) for p, d in NOMBRES_PROHIBIDOS]

# ── 2. PATRONES INEQUÍVOCOS DE CREDENCIAL (abortan) ──────────────────────────
PATRONES_PELIGRO = [
    (r"sk-ant-[A-Za-z0-9_\-]{20,}", "clave de Anthropic"),
    (r"sk-proj-[A-Za-z0-9_\-]{20,}", "clave de OpenAI"),
    (r"sk-[A-Za-z0-9]{32,}", "clave estilo OpenAI"),
    (r"AIza[0-9A-Za-z_\-]{30,}", "clave de Google"),
    (r"gh[pousr]_[A-Za-z0-9]{30,}", "token de GitHub"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "token de GitHub"),
    (r"xox[baprs]-[A-Za-z0-9\-]{10,}", "token de Slack"),
    (r"hf_[A-Za-z0-9]{20,}", "token de Hugging Face"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "clave privada"),
    # Cadena de conexión con contraseña LITERAL. Se exige que usuario y clave sean
    # texto plano (sin {var}, $, ( o [ ) y que la clave no EMPIECE por una palabra
    # de manual. Así no salta con los f-string, los regex, los
    # «postgresql://user:pass@host/db» de la interfaz ni los ejemplos de la
    # documentación de knowledge/ (que enseñan a propósito cosas como
    # «postgresql://admin:password123@prod-db:5432/main» para decir qué NO hacer).
    (r"(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp)://"
     r"[A-Za-z0-9_.\-]{2,}:"
     r"(?!(?i:pass|password|passwd|pwd|clave|contrasena|secret|token|credential|"
     r"changeme|change-me|mypass|hunter2|letmein|admin|root|usuario|user|"
     r"tu[_\-]|your|xxx+|test|demo|dummy|fake|sample|ejemplo|example|"
     r"placeholder|123456|abc123))"
     r"[A-Za-z0-9_.\-!%^&+]{6,}@",
     "cadena de conexión CON contraseña"),
    # Contrasenas de FIRMA de aplicaciones. Esto se le escapo al detector el
    # 30/07/2026: `movil/COMO_SE_COMPILO.md` llevaba la clave real del keystore
    # de Android en claro, en un archivo que SI se subia. Las formas seguras
    # (`env:` y `file:`) se aceptan; `pass:<literal>` no.
    (r"--(?:ks|key)-pass\s+pass:(?!<|\$|env:|file:|TU|CAMBIA)\S{4,}",
     "la contrasena de un keystore (apksigner)"),
    (r"-(?:storepass|keypass)\s+(?!<|\$|%|TU|CAMBIA)[A-Za-z0-9_.@!\-]{4,}",
     "la contrasena de un keystore (keytool/jarsigner)"),
    (r"(?:POSTGRES_PASSWORD|MYSQL_ROOT_PASSWORD|MONGO_INITDB_ROOT_PASSWORD)\s*[:=]\s*"
     r"(?!\$|<|\{|CAMBIA|TU_)[A-Za-z0-9_.\-]{6,}",
     "la contrasena de una base de datos en un compose"),
    (r"eyJ[A-Za-z0-9_\-]{15,}\.eyJ[A-Za-z0-9_\-]{15,}\.", "un JWT"),
    (r"ya29\.[A-Za-z0-9_\-]{20,}", "token de acceso de Google"),
]
_PELIGRO_RX = [(re.compile(p), d) for p, d in PATRONES_PELIGRO]

# ── 3. PATRONES QUE SOLO MERECEN UNA MIRADA (no abortan) ─────────────────────
_REVISA_RX = re.compile(
    r"""(?ix)
    \b(api[_\-]?key|apikey|access[_\-]?token|auth[_\-]?token|client[_\-]?secret|
       password|passwd|contrase|secret)\b
    \s*[:=]\s*
    ["']?([A-Za-z0-9_\-!@\#$%^&*+/=.]{12,})["']?
    """)
# Lo que NO es un secreto aunque lo parezca: placeholders, código y regex.
_INOCENTE = re.compile(
    r"""(?ix)
    (tu[_\- ]|<[^>]+>|x{4,}|\.{3}|ejemplo|example|placeholder|cambia|your[_\- ]|
     dummy|fake|sample|USUARIO|CONTRASENA|os\.environ|getenv|settings\.(get|set|secret)|
     payload|keyField|self\._key|\{[^}]*\}|\$\{|%s|\\b|\[a-z|re\.compile|
     description|prohibid|def\s|return\s)""")

# ── 3b. DATOS PERSONALES: no son secretos, pero tampoco deberian publicarse ──
# Avisan, no abortan: es decision suya. Salen de la auditoria del 30/07/2026.
_PERSONALES = [
    (r"[A-Za-z]:\\Users\\(?!usuario|TuUsuario|TU_USUARIO|%|<)[A-Za-z0-9_.\-]{3,}",
     "una ruta con un nombre de usuario de Windows real"),
    (r"D:\\Adrian|/home/adri(?:an)?\b", "una ruta personal del autor"),
    (r"\b(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}\b", "una direccion MAC"),
    (r"\b192\.168\.\d{1,3}\.\d{1,3}\b|\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
     "una IP de red local"),
    (r"[A-Za-z0-9._%+\-]+@(?!ejemplo|example|dominio|y\.com|correo)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
     "una direccion de correo"),
]
_PERSONALES_RX = [(re.compile(p), d) for p, d in _PERSONALES]
# MACs e IPs que son de MANUAL y no dicen nada de nadie.
_NEUTROS = re.compile(
    r"(?i)aa:bb:cc:dd:ee:ff|11:22:33:44:55:66|00:00:00:00:00:00|"
    r"192\.168\.1\.(?:1|5|10|40|50|51|52|53|100)\b|192\.168\.0\.1\b|10\.0\.0\.1\b")

EXCEPCIONES_RUTA = re.compile(
    r"(?i)(^|/)(revisar_antes_de_subir\.py|\.gitignore|README\.md)$"
    r"|(^|/)docs/|(^|/)tests/|(^|/)knowledge/|\.example\.|_ejemplo\.")


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} → {r.stderr.strip()[:300]}")
    return r.stdout


def archivos_en_el_indice() -> list[str]:
    salida = _git("ls-files", "-c", "--exclude-standard")
    return [l.strip() for l in salida.splitlines() if l.strip()]


def _es_binario(datos: bytes) -> bool:
    return b"\x00" in datos[:4096]


def _tapar(texto: str) -> str:
    """Nunca se imprime el secreto entero: lo suficiente para localizarlo."""
    t = texto.strip()
    return (t[:6] + "…" + t[-3:]) if len(t) > 12 else (t[:3] + "…")


def revisar() -> dict:
    peligros: list[dict] = []
    revisar_: list[dict] = []
    personales: list[dict] = []
    grandes: list[dict] = []
    total = 0

    for rel in archivos_en_el_indice():
        ruta = ROOT / rel
        for rx, desc in _NOMBRES_RX:
            if rx.search(rel):
                peligros.append({"archivo": rel, "motivo": f"es {desc}",
                                 "linea": 0, "muestra": ""})
                break
        if not ruta.is_file():
            continue
        tam = ruta.stat().st_size
        total += tam
        if tam >= AVISO_TAMANO:
            grandes.append({"archivo": rel, "mb": round(tam / 1e6, 2)})
        if tam > LIMITE_BYTES:
            continue
        datos = ruta.read_bytes()
        if _es_binario(datos):
            continue
        texto = datos.decode("utf-8", "replace")
        exento = bool(EXCEPCIONES_RUTA.search(rel))
        for n, linea in enumerate(texto.splitlines(), 1):
            if len(linea) > 600:
                continue
            for rx, desc in _PELIGRO_RX:
                m = rx.search(linea)
                if m:
                    peligros.append({"archivo": rel, "linea": n,
                                     "motivo": f"parece {desc}",
                                     "muestra": _tapar(m.group(0))})
            if exento:
                continue
            m = _REVISA_RX.search(linea)
            if m and not _INOCENTE.search(linea):
                revisar_.append({"archivo": rel, "linea": n,
                                 "motivo": "asignación con pinta de credencial",
                                 "muestra": _tapar(m.group(0))})
            for rx, desc in _PERSONALES_RX:
                mp = rx.search(linea)
                if mp and not _NEUTROS.search(mp.group(0)):
                    personales.append({"archivo": rel, "linea": n,
                                       "motivo": f"parece {desc}",
                                       "muestra": mp.group(0)[:48]})
                    break

    return {"archivos": len(archivos_en_el_indice()), "mb": round(total / 1e6, 2),
            "peligros": peligros, "revisar": revisar_, "grandes": grandes,
            "personales": personales}


# ── AUTOCOMPROBACIÓN ─────────────────────────────────────────────────────────
# Un detector de secretos que no se prueba a sí mismo no vale nada: o deja pasar
# claves, o aborta con ejemplos de la documentación y acabas desactivándolo.
# Cada caso de aquí ha salido de algo REAL de este proyecto.
#
# OJO al truco de los `+`: los casos que DEBEN saltar se montan por trozos a
# propósito, para que la cadena completa no exista literalmente en este archivo.
# Si estuvieran escritos de una pieza, este propio archivo daría positivo y
# habría que exceptuarlo del análisis — es decir, dejar un agujero justo en el
# guardia. Así se prueba el detector de verdad sin abrir ninguna puerta.
_Q = "@localhost:5433/nexus_core"
CASOS_DEBE_SALTAR = [
    ('    "db_url": "postgresql://nexus_admin:nexus' + '_dev_2026' + _Q + '",',
     "la contraseña que estaba escrita en backend/core/config.py"),
    ('{"openai_api_key":"sk-' + 'proj-A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2"}',
     "una clave de OpenAI en config/secrets.json.bak"),
    ('K = "sk-' + 'ant-api03-QQQQwwwwEEEErrrrTTTTyyyyUUUU"', "una clave de Anthropic"),
    ('token: gh' + 'p_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8', "un token de GitHub"),
    ('"token": "ya' + '29.a0AfB_byC1d2E3f4G5h6I7j8K9l0M1n2O3p4Q5"',
     "un token de acceso de Google"),
    ('-----BEGIN RSA ' + 'PRIVATE KEY-----', "una clave privada"),
    ('MONGO = "mongodb+srv://nexo:Zq7' + 'Kx2Rt9Lm@cluster0.mongodb.net/db"',
     "una cadena de Mongo con contraseña"),
    ('apksigner sign --ks nexus.keystore --ks-pass pass:' + 'nexus2026x --out a.apk',
     "la contraseña del keystore de Android (se le escapó el 30/07)"),
    ('jarsigner -keystore k.jks -storepass ' + 'Sup3rSecreta1 app.apk alias',
     "la contraseña de un keystore con keytool"),
    ('      POSTGRES_PASSWORD: ' + 'nexus_dev_2026',
     "la contraseña de Postgres en un docker-compose"),
]
CASOS_NO_DEBE_SALTAR = [
    ('settings.set("db_url", f"postgresql://{user}:{pwd}@localhost:5433/{db}")',
     "un f-string de backend/app.py"),
    ('r"mysql://(?:(?P<u>[^:@]+)(?::(?P<p>[^@]*))?@)?(?P<h>[^:/]+)"',
     "el regex de skills/datos/skill.py"),
    ("'conéctate a la base de datos postgresql://user:pass@host:5432/db'",
     "el ejemplo del HUD"),
    ('placeholder="postgresql://usuario:clave@192.168.1.10:5432/nexus_core"',
     "el placeholder de setup.html"),
    ('"DB_URL": "postgresql://admin:password123@prod-db:5432/main"',
     "el ejemplo de knowledge/awesome-copilot/mcp-security-audit"),
    ('NEXUS_DB_URL=postgresql://USUARIO:CONTRASENA@localhost:5433/nexus_core',
     "el .env.example ya saneado"),
    ('redis://default:changeme@localhost:6379', "un ejemplo con «changeme»"),
    ('"db_url": os.environ.get("NEXUS_DB_URL", ""),', "el config.py ya corregido"),
    ('apksigner sign --ks nexus.keystore --ks-pass env:KS_PASS --out a.apk',
     "la forma SEGURA de pasar la contraseña del keystore"),
    ('      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}', "un compose con variable"),
    ('-storepass <TU_CONTRASENA> app.apk', "un placeholder de keystore"),
]


def autotest() -> int:
    fallos = 0
    print("Autocomprobación del detector\n" + "─" * 60)
    for linea, desc in CASOS_DEBE_SALTAR:
        pillado = next((d for rx, d in _PELIGRO_RX if rx.search(linea)), "")
        if pillado:
            print(f"  ✔ detecta {desc} → {pillado}")
        else:
            print(f"  ✖ SE LE ESCAPA {desc}\n      {linea[:90]}")
            fallos += 1
    print()
    for linea, desc in CASOS_NO_DEBE_SALTAR:
        pillado = next((d for rx, d in _PELIGRO_RX if rx.search(linea)), "")
        if pillado:
            print(f"  ✖ FALSA ALARMA con {desc} → lo llama «{pillado}»\n      {linea[:90]}")
            fallos += 1
        else:
            print(f"  ✔ no molesta con {desc}")
    print("─" * 60)
    print("Todo correcto." if not fallos else f"{fallos} fallo(s) en el detector.")
    return 1 if fallos else 0


def main() -> int:
    if "--autotest" in sys.argv:
        return autotest()
    try:
        info = revisar()
    except RuntimeError as e:
        print("No he podido leer el índice de git:", e)
        print("¿Has hecho «git add» antes? SUBIR_A_GITHUB.bat lo hace por ti.")
        return 2

    if "--json" in sys.argv:
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return 1 if info["peligros"] else 0

    print(f"\nArchivos preparados para subir: {info['archivos']}  ·  {info['mb']} MB")
    if info["grandes"]:
        print("\nArchivos grandes (>5 MB) — mira si de verdad tienen que estar:")
        for g in info["grandes"][:15]:
            print(f"   {g['mb']:>7.2f} MB  {g['archivo']}")

    if info["revisar"]:
        print(f"\n⚠ REVISA ({len(info['revisar'])}) — probablemente código, "
              f"pero échales un ojo:")
        for r in info["revisar"][:20]:
            print(f"   {r['archivo']}:{r['linea']}  {r['muestra']}")
        if len(info["revisar"]) > 20:
            print(f"   … y {len(info['revisar']) - 20} más")

    if info.get("personales"):
        vistos, lista = set(), []
        for x in info["personales"]:
            clave = (x["archivo"], x["muestra"])
            if clave not in vistos:
                vistos.add(clave)
                lista.append(x)
        print(f"\n· DATOS PERSONALES ({len(lista)}) — no son claves, pero tampoco "
              f"hacen falta en un repositorio:")
        for x in lista[:25]:
            print(f"   {x['archivo']}:{x['linea']}  {x['muestra']}  ({x['motivo']})")
        if len(lista) > 25:
            print(f"   … y {len(lista) - 25} más")

    if info["peligros"]:
        print(f"\n{'='*66}\n✖ ABORTADO: {len(info['peligros'])} cosa(s) que NO "
              f"pueden subir a GitHub\n{'='*66}")
        for p in info["peligros"]:
            donde = f":{p['linea']}" if p["linea"] else ""
            extra = f"  ({p['muestra']})" if p["muestra"] else ""
            print(f"   {p['archivo']}{donde}  →  {p['motivo']}{extra}")
        print("\nQué hacer:")
        print("  1. Si es un archivo que no debe subir → añádelo al .gitignore")
        print("     y ejecuta:  git rm --cached \"<archivo>\"")
        print("  2. Si es una clave dentro del código → sácala a .env y usa")
        print("     settings.secret(...) o os.environ para leerla.")
        print("  3. Vuelve a lanzar SUBIR_A_GITHUB.bat.")
        return 1

    print(f"\n{'='*66}\n✔ LIMPIO: nada con pinta de secreto en lo que se va a subir."
          f"\n{'='*66}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
