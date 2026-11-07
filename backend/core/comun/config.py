"""
nexus — Configuración central.

Carga variables de .env y del archivo config/settings.json (editable en caliente
desde el HUD).  Prioridad: settings.json > .env > valores por defecto.

Los SECRETOS viven aparte, en `config/secrets.json`, y desde la tarea T13
(hallazgo SEC-09 de la auditoría del 30/07/2026, roadmap P2-6) se guardan
CIFRADOS con DPAPI: cada valor es una cadena etiquetada `dpapi:v1:…` dentro del
mismo JSON. `CLAUDE.md` decía que estaban «cifradas» y era mentira; ahora es
verdad, y la migración de un almacén en claro ocurre sola al cargarlo (ver
`_abrir_secretos`). En un equipo sin DPAPI —Linux, Docker, los contenedores de
CI— se comporta exactamente como antes: JSON plano y funcionando.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import cripto
from .atomicos import escribir_json_atomico

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv es opcional
    def load_dotenv(*a, **k):
        return False

# Raíz del proyecto (…/nexus).
# Empaquetado con PyInstaller: el bundle (_MEIPASS) trae una copia de respaldo de
# frontend/skills, pero si existen esas carpetas JUNTO al .exe se usan ESAS. Así
# un arreglo del HUD o de una skill entra reemplazando la carpeta (sin recompilar):
# el .exe queda «en línea» con solo copiar frontend/ actualizado al lado.
import sys

if getattr(sys, "frozen", False):
    BUNDLE = Path(sys._MEIPASS)               # respaldo de solo lectura dentro del exe
    ROOT = Path(sys.executable).resolve().parent   # carpeta del nexus.exe
else:
    BUNDLE = ROOT = Path(__file__).resolve().parents[3]


def _prefer_external(name: str) -> Path:
    """Carpeta de al lado del exe si existe (actualizable en caliente); si no, la del bundle."""
    ext = ROOT / name
    return ext if ext.is_dir() else (BUNDLE / name)

# v23 (T22): las pruebas end-to-end arrancan nexus de verdad, pero NUNCA pueden
# tocar los datos reales del operador. Con NEXUS_DATA_DIR / NEXUS_CONFIG_DIR se
# apunta a carpetas desechables, y así las pruebas son reproducibles en otro equipo.
_ENV_DATA = os.environ.get("NEXUS_DATA_DIR", "").strip()
_ENV_CONFIG = os.environ.get("NEXUS_CONFIG_DIR", "").strip()

DATA_DIR = Path(_ENV_DATA) if _ENV_DATA else ROOT / "data"
SKILLS_DIR = _prefer_external("skills")
FRONTEND_DIR = _prefer_external("frontend")
CONFIG_DIR = Path(_ENV_CONFIG) if _ENV_CONFIG else ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "settings.json"
# La ruta a settings.example.json NO vive aquí: quien copia la plantilla cuando
# falta el settings.json es run.bat, no el backend (02/08/2026).

load_dotenv(ROOT / ".env")

SECRETS_FILE = CONFIG_DIR / "secrets.json"

DEFAULTS = {
    # ---- LLM ----
    "llm_provider": "ollama",          # ollama | openai | anthropic | gemini | cloud | mock
    "llm_local": True,                 # check "modelo local" del panel ⚙
    # RESERVA DEL CEREBRO (AI-01/PRIV-02 de la auditoría del 30/07/2026). Si el
    # proveedor elegido no responde, nexus solo cambia a otro de la MISMA clase
    # (ver LOCALIDAD en llm.py): un cerebro local cae en otro local, nunca en la
    # nube. Para que la nube pueda hacer de reserva hay que decirlo AQUÍ: por el
    # prompt viajan la memoria, el perfil del operador y los documentos
    # recuperados, y eso no sale del equipo por decisión de nadie más que su dueño.
    "permitir_fallback_nube": False,
    "ollama_url": "http://localhost:11434",
    # Con cuál se miran las portadas de los reels. Vacío = se coge solo el
    # primero de visión que tenga Ollama instalado.
    "vision_model": "",
    "hermes_url": "http://127.0.0.1:8642",   # API local de Hermes Agent (Nous)
    "hermes_auto": True,                     # nexus delega SOLO en Hermes lo agéntico
    "hermes_autostart": True,                # nexus ARRANCA el gateway de Hermes bajo demanda
    "hermes_exe": "",                        # ruta a hermes.exe (vacío = autodetectar)
    "hermes_provider": "",                   # cerebro de Hermes: openai|anthropic|gemini|openrouter
    "hermes_model": "",                      # modelo concreto del cerebro de Hermes
    # DELEGAR EN UN EJECUTOR CON CEREBRO DE NUBE (T25/P3-6). NO es lo mismo que
    # `permitir_fallback_nube`: aquel gobierna un CAMBIO de cerebro que nadie
    # pidió (el elegido cae y nexus se planta en otro proveedor), y este gobierna
    # si se puede ENTREGAR un encargo a un ejecutor cuyo modelo el dueño eligió a
    # propósito (Hermes con Gemini, por ejemplo). Son dos consentimientos
    # distintos y por eso son dos claves: con el de arriba como condición, toda
    # delegación de un Hermes que el dueño configuró él mismo quedaba apagada sin
    # que nadie lo hubiera pedido. Defecto TRUE: la función no se apaga sola; la
    # frontera real de cada encargo sigue siendo la confirmación (un «sí» por
    # orden) y el aviso por el bus de qué cerebro es y a dónde va. Quien quiera
    # una política estricta de «nada sale por la delegación» la pone en false.
    "permitir_delegacion_nube": True,
    "openrouter_model": "openai/gpt-4o-mini",  # modelo si el proveedor cloud es OpenRouter
    "ollama_model": "llama3.1",
    "openai_model": "gpt-5.6-luna",          # barato; el tope es gpt-5.6-sol
    "anthropic_model": "claude-sonnet-5",     # equilibrio; el tope es claude-fable-5
    "gemini_model": "gemini-2.5-flash",       # (gemini-2.0-flash está DEPRECADO)
    "cloud_base_url": "https://api.openai.com/v1",  # cualquier API compatible OpenAI
    "cloud_model": "gpt-5.6-luna",
    "embed_model": "nomic-embed-text", # embeddings para el RAG (Ollama)
    "model_scan_paths": [],            # carpetas extra donde buscar modelos locales
    "smart_router": True,              # si el regex no casa, el LLM interpreta y reescribe la orden
    "web_augment": True,               # busca en la web para preguntas de actualidad
    "devil_mode": True,                # SIEMPRE activo: skill propia de nexus (no apagable)
    # ---- Voz ----
    "tts_engine": "auto",              # auto | elevenlabs | local | off
    "tts_voice": "Rachel",
    "stt_engine": "auto",              # auto | whisper | mock
    "stt_device": "auto",              # auto (cuda→cpu) | cuda | cpu
    "whisper_model": "small",
    "input_device": "",                # micrófono de ENTRADA (nombre; "" = predeterminado del SO)
    "output_sink_id": "",              # dispositivo de SALIDA de audio (deviceId del navegador; "" = predeterminado)
    "hotkey": "f9",
    # ---- Memoria ----
    # La CONTRASEÑA no va en el código: sale de NEXUS_DB_URL (.env, que no se
    # sube al repositorio) o de config/settings.json, que tampoco. Antes estaba
    # aquí escrita y se habría publicado en el primer commit (25/07/2026).
    "db_url": os.environ.get("NEXUS_DB_URL", ""),
    "db_password": "",                 # se genera al azar en la 1ª instalación (setup/docker)
    "memory_backend": "auto",          # auto (DB si responde, si no grafo) | db | files
    # ---- HUD ----
    "palette": "neon-green",
    # Sin nombre por defecto: lo pregunta el asistente de primera ejecucion.
    # Estaba aqui el del autor, y se distribuia a todo el que instalara nexus.
    "operator_name": "",
    # ---- IDENTIDAD DEL SISTEMA (white-label: cada instalación se llama como quiera) ----
    # El NOMBRE del asistente. Va a los prompts, la interfaz, la voz, la wake word y
    # los nombres de Docker/BD (por su slug). Por defecto «nexus»; en la instalación
    # cada persona puede llamar a su sistema como quiera (white-label).
    "assistant_name": "nexus",
    "assistant_pron": "",              # cómo se PRONUNCIA en voz (vacío = se lee el nombre tal cual;
                                       #  rellénalo solo si tu nombre se lee raro en la voz)
    "assistant_logo": "",              # URL o data-URL de un logo propio (vacío = logo por defecto)
    # ---- Instalación / primera ejecución ----
    "setup_done": False,               # el asistente de instalación marca True al terminar
    "personality": "jarvis",           # personalidad del bot (ver PERSONALITIES en llm.py)
    # ---- Razonamiento / auto-reentrenamiento ----
    "reasoning_level": "rapido",       # rapido | equilibrado | profundo (cuánto «piensa» → velocidad)
    "retrain_model": "auto",           # modelo para el auto-reentreno: 'auto' = tu cerebro activo
                                       # (NO consume de más); o un modelo concreto de cualquier LLM
    "self_learning": True,             # auto-reentrenamiento continuo (cíclico) activado
    "retrain_hours": 6,                # cada cuántas horas se reentrena y reindexa el RAG
    # ---- Embeddings / RAG (el modelo que haya; el almacén es la DB si está montada) ----
    # embed_provider: auto (sigue el cerebro elegido en la instalación) | ollama | openai | gemini
    "embed_provider": "auto",
    "embed_model_openai": "text-embedding-3-small",
    "embed_model_gemini": "text-embedding-004",
    # ---- Proactividad (Project Manager que toma la iniciativa) ----
    "proactive": True,                 # nexus avisa/recuerda sin que le hables
    "proactive_minutes": 30,           # cada cuánto revisa recordatorios/citas
    "proactive_hours": "9-21",         # franja horaria para el empujón diario
    "proactive_speak": True,           # además de mostrarlo, lo dice en voz
    "pm_strong": True,                 # PM FUERTE: auto-crea tareas de lo que hablas
                                       # y mueve tareas según respondas al empujón diario
    # ---- Permisos (estilo sandbox) ----
    "perm_hardware": True,             # leer CPU/RAM/placa/discos del equipo
    # Alcance del acceso a archivos (SEC-04 / roadmap P1-6). El defecto era «todo»
    # y eso convertía cualquier canal comprometido (SEC-01/02/03) o una prompt
    # injection en un «léeme el disco entero»: claves SSH, config/secrets.json,
    # tokens de Google. Ahora el defecto es «carpetas»:
    #   sandbox  : SOLO data/sandbox, la carpeta de nexus
    #   carpetas : SOLO perm_folders (por defecto Documentos/Escritorio/Descargas)
    #   todo     : todo el equipo — elección EXPLÍCITA del operador en ⚙ → Permisos,
    #              y aun así sigue vetando el material de credenciales
    #              (permissions.denied).
    "perm_files": "carpetas",         # sandbox | carpetas | todo
    # Carpetas del modo «carpetas». Lista VACÍA = Documentos, Escritorio y
    # Descargas del perfil (ver carpetas_permiso_por_defecto(): se resuelve en
    # cada uso, así que una redirección a OneDrive o un perfil que se mueve no
    # deja la lista obsoleta ni exige migrar ningún settings.json).
    "perm_folders": [],
    # ---- Voz ----
    "mic_muted": False,                # muteo del usuario: el micro abierto no te oye
    # ---- Música ----
    "music_service": "youtube",         # por defecto; «en spotify»/«en youtube» mandan siempre
    # ---- Conversación fluida ----
    "open_mic": False,                 # micro abierto (requiere whisper + micrófono)
    "wake_word": "despierta nexus",              # palabra de activación (se deriva del nombre)
    "wake_enabled": False,             # escucha en segundo plano la wake word
    # ---- Instagram / Content OS ----
    "ig_user_id": "",
    # Cuenta Business/Creator para la skill de reels (ID numerico, no el @).
    "ig_business_account_id": "",
    # ---- Automatizaciones ----
    "n8n_webhook_url": "",             # ej: http://localhost:5678/webhook/nexus
    "n8n_base_url": "http://localhost:5678",   # n8n local (para crear flujos por API)
    # ---- Engram: memoria de PROYECTO/código compartida con otras IA (opcional) ----
    "engram_autostart": True,          # nexus ARRANCA «engram serve» bajo demanda si está instalado
    "engram_autoinstall": True,        # nexus INSTALA el binario solo si falta (go install o binario oficial verificado)
    "engram_exe": "",                  # ruta al binario engram (vacío = autodetectar en PATH)
    "engram_port": 7437,               # puerto de «engram serve» (por defecto de la herramienta)
    # ---- Wake-on-LAN ----
    "wol_mac": "",                     # MAC del PC a encender (aa:bb:cc:dd:ee:ff)
    "wol_broadcast": "255.255.255.255",
    # ---- Casa / Domótica ----
    "homeassistant_url": "",           # ej. http://homeassistant.local:8123 (token en secrets)
    "known_devices": [],               # [{name, ip, mac, brand}] de TVs/aparatos conocidos
    "my_devices": [],                  # MIS DISPOSITIVOS del panel (los que usas y controlas)
    # ---- Copias de seguridad (P2-10 / PRIV-04) ----
    # Segunda copia del zip diario en OTRO sitio: la letra de un disco externo, un
    # NAS montado, una carpeta sincronizada con tu nube personal… Vacío (el
    # defecto) = no se copia a ninguna parte. Importante: si la copia se queda en
    # el MISMO disco que `data/`, no protege de un fallo de disco ni de un
    # ransomware; apúntala a otro disco físico. nexus no habla con ninguna nube:
    # solo copia el archivo con el sistema de archivos.
    "backup_destino_extra": "",
}


def _read_json_safe(path: Path) -> dict:
    """Lee un JSON tolerando corrupción. Si el archivo principal no parsea (p. ej.
    quedó truncado), recurre a su `.bak` (última versión buena guardada por
    _write_json_atomic). {} solo si NADA es usable. Así una truncación puntual NO
    hace perder toda la configuración."""
    for cand in (path, path.with_name(path.name + ".bak")):
        try:
            if cand.exists():
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return {}


def _write_json_atomic(path: Path, data: dict) -> None:
    """Guarda un JSON de forma ATÓMICA: escribe a un `.tmp` y hace os.replace (que es
    indivisible), así el archivo NUNCA queda truncado aunque el proceso muera a
    mitad —el bug que rompía settings.json/secrets.json—. Antes respalda en `.bak`
    la versión actual SOLO si es JSON válido.

    La implementación vive en `comun/atomicos.py` desde la tarea T16 (ARQ-05):
    el tablero, el panel de multitarea, Content OS y la proactividad escribían a
    pelo y ahora escriben por el MISMO sitio. Este nombre se queda porque
    `dominio/reglas.py` lo llama, y `respaldo=True` porque `_read_json_safe()`
    recurre a ese `.bak` cuando settings.json quedó truncado.

    `secrets.json` ya NO se escribe por aquí (T13): su `.bak` era una copia en
    CLARO del almacén al lado del almacén. Lo escribe `_guardar_secretos_en_disco`
    con `respaldo=False`."""
    escribir_json_atomico(path, data, indent=2, respaldo=True)


def carpetas_permiso_por_defecto() -> list[str]:
    """Documentos, Escritorio y Descargas del perfil ACTUAL (semilla de perm_folders).

    Por qué así y no con la API de «Known Folders» de Windows: el proyecto no
    tenía ningún ayudante de carpetas conocidas (se buscó en skills/system_pc,
    backend/core/infraestructura/hardware.py y skills/files) más allá del mapa
    por NOMBRE de `skills/files/skill.py::_known_dir`, que es de otra capa y no
    debe importarse desde aquí. Se sigue la MISMA convención que ese ayudante
    —`USERPROFILE`, y antes la redirección a OneDrive, que en Windows suele
    mover Escritorio y Documentos—, más el nombre en español, para que el
    operador reconozca sus carpetas.

    Se resuelve en CADA llamada (no se cachea) por dos razones: el perfil puede
    moverse sin reiniciar, y las pruebas necesitan un perfil de mentira.
    Las carpetas que falten se crean al usarlas (ver permissions._allowed_roots),
    nunca aquí: leer la configuración no debe tocar el disco.
    """
    home = Path(os.environ.get("USERPROFILE", "").strip() or Path.home())
    od = (os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or "").strip()
    odir = Path(od) if od else None

    def _elige(candidatas: list[Path], defecto: Path) -> str:
        """La primera candidata que EXISTE (la redirección a OneDrive manda) o el
        nombre de siempre. `defecto` va aparte a propósito: si ninguna existe,
        crear «Escritorio» en vez de «Desktop» le cambiaría el nombre a la
        carpeta del operador."""
        for c in candidatas:
            if c.exists():
                return str(c)
        return str(defecto)

    docs = _elige(([odir / "Documents", odir / "Documentos"] if odir else [])
                  + [home / "Documents", home / "Documentos"], home / "Documents")
    escritorio = _elige(([odir / "Desktop", odir / "Escritorio"] if odir else [])
                        + [home / "Desktop", home / "Escritorio"], home / "Desktop")
    descargas = _elige([home / "Downloads", home / "Descargas"], home / "Downloads")
    return [docs, escritorio, descargas]


def _load_json() -> dict:
    return _read_json_safe(CONFIG_FILE)


# ─────────────────────────── el almacén de secretos ───────────────────────────
# Hallazgo SEC-09 (roadmap P2-6, tarea T13). Antes: `config/secrets.json` era
# JSON PLANO, y cualquiera que pudiera leer el archivo —cualquier proceso del
# usuario, cualquier copia de seguridad del perfil— leía las API keys enteras.
#
# Ahora: el archivo sigue siendo JSON (se abre con `cat` y solo se ven NOMBRES),
# y cada valor es una cadena etiquetada `dpapi:v1:<base64>` que solo descifra la
# misma cuenta de Windows en el mismo equipo. Ver `comun/cripto.py` para la
# llamada exacta a DPAPI y para lo que NO cubre.
#
# Los avisos se acumulan y se imprimen porque la migración ocurre al IMPORTAR
# este módulo: todavía no hay bucle de eventos y el bus no sirve. El texto NUNCA
# lleva el valor, solo el nombre de la clave.
AVISOS_SECRETOS: list[str] = []


def _avisar_secretos(msg: str) -> None:
    """Un problema del almacén de claves se cuenta SIEMPRE.

    Callar un fallo aquí significa que nexus arranca sin la clave de OpenAI y el
    operador cree que la ha perdido. Un aviso en la consola y en
    `AVISOS_SECRETOS` cuesta una línea y ahorra esa tarde entera.

    El `print` va protegido a propósito: esto corre al IMPORTAR el módulo, y en un
    ejecutable sin consola `sys.stdout` puede ser None. Un aviso que revienta el
    arranque sería peor que el problema que anuncia."""
    AVISOS_SECRETOS.append(msg)
    try:
        print(f"[nexus] AVISO secretos: {msg}")
    except Exception:                                          # noqa: BLE001
        pass


def _leer_secretos_crudos() -> dict:
    """El JSON tal cual está en disco (con el repliegue al `.bak` de siempre)."""
    return _read_json_safe(SECRETS_FILE)


def _abrir_secretos(crudos: dict) -> tuple[dict, dict, dict]:
    """Reparte el almacén en tres cubos y MIGRA a cifrado lo que esté en claro.

    Devuelve `(planos, ajenos, marcas)`:

      * `planos` — nombre → valor EN CLARO en memoria (nunca se guarda así en
        Windows; el disco siempre lleva la marca).
      * `ajenos` — nombre → lo que hay en disco, TAL CUAL, cuando aquí no se
        puede usar: cifrado con otra máquina u otra cuenta de Windows, formato
        de cifrado que no conocemos, o un valor que no es texto (un número, un
        booleano, un objeto). Eso es lo que se devuelve al archivo byte a byte
        en cada escritura, para no destruir ni reinterpretar lo que hay.

        OJO A LA FRONTERA, que es lo que T13 contó mal: «no es un secreto» NO
        significa «no se toca». Cualquier valor de TEXTO en claro se cifra al
        migrar, aunque su nombre no esté en `Settings.SECRET_KEYS` — el almacén
        entero es de credenciales, así que no elige por nombre. De esos valores
        sobrevive el VALOR, comprobado uno a uno con la ida y vuelta
        `descifrar(cifrar(v)) == v`; sus BYTES en disco cambian a propósito
        (cifrar cambia los bytes, ésa es la idea). Byte a byte sólo se conserva
        lo que aquí no se puede usar: lo que no es texto y los blobs ajenos.
      * `marcas` — nombre → el `dpapi:v1:` que ya estaba, para no volver a
        cifrar (DPAPI añade sal: el blob cambiaría) lo que no ha cambiado. La
        migración actualiza este diccionario EN SU SITIO tras escribir.

    La migración solo se intenta si hay algún valor en claro y hay DPAPI. Si
    falla la verificación, el archivo se queda EXACTAMENTE como estaba.
    """
    planos: dict = {}
    ajenos: dict = {}
    marcas: dict = {}
    en_claro: list[str] = []
    for clave, valor in (crudos or {}).items():
        if cripto.es_cifrado(valor):
            try:
                planos[clave] = cripto.descifrar(valor)
            except cripto.CriptoError as exc:
                ajenos[clave] = valor
                _avisar_secretos(
                    f"la clave «{clave}» está cifrada con otra máquina u otra "
                    f"cuenta de Windows y aquí no se puede abrir ({exc}). No la "
                    "toco ni la borro: vuelve a pegarla en ⚙ → Claves API desde "
                    "esta cuenta.")
                continue
            marcas[clave] = valor
            continue
        if cripto.es_de_dpapi(valor):
            ajenos[clave] = valor
            _avisar_secretos(
                f"la clave «{clave}» está guardada con un formato de cifrado que "
                "esta versión de nexus no conoce. No la toco: actualiza nexus o "
                "vuelve a pegarla en ⚙ → Claves API.")
            continue
        if not isinstance(valor, str):
            ajenos[clave] = valor
            _avisar_secretos(
                f"el valor de «{clave}» en secrets.json no es texto "
                f"({type(valor).__name__}): lo dejo como está y no se usa.")
            continue
        planos[clave] = valor
        if valor.strip():
            en_claro.append(clave)
    if en_claro:
        _migrar_secretos(planos, ajenos, marcas)
    return planos, ajenos, marcas


def _migrar_secretos(planos: dict, ajenos: dict, marcas: dict) -> None:
    """Cifra el almacén que estaba en claro, en el sitio, sin pérdidas.

    Sin DPAPI (Linux, Docker, los contenedores de CI) NO se hace nada: el
    archivo se queda en JSON plano y nexus funciona igual que antes. Ese
    repliegue es deliberado —el contenedor de CI es Linux y ahí no hay perfil de
    Windows que pueda descifrar nada— y está escrito en el docstring de
    `comun/cripto.py`.
    """
    if not cripto.disponible():
        return
    disco = _cifrar_y_verificar(planos, ajenos, marcas)
    if disco is None:
        return                                   # ya se ha avisado del motivo
    if not _guardar_secretos_en_disco(disco):
        return
    marcas.clear()
    marcas.update({k: v for k, v in disco.items() if cripto.es_cifrado(v)})


def _cifrar_y_verificar(planos: dict, ajenos: dict, marcas: dict) -> dict | None:
    """El JSON que hay que escribir, o None si NO se puede escribir con garantías.

    Antes de tocar el archivo se comprueba, VALOR A VALOR, que
    `descifrar(cifrar(v)) == v`, y después que el JSON resultante se vuelve a
    leer igual. Si algo falla no se escribe NADA: medio almacén migrado es peor
    que ninguno, porque el valor que se quede en claro no se nota y el que se
    pierda tampoco.
    """
    nuevo: dict = {}
    for clave, valor in planos.items():
        if not isinstance(valor, str) or not valor.strip():
            nuevo[clave] = valor                 # una cadena vacía no es un secreto
            continue
        marca = None
        previa = marcas.get(clave)
        if previa and cripto.es_cifrado(previa):
            # Ya estaba cifrado: se REUTILIZA el blob si el valor no ha cambiado
            # (y se comprueba descifrándolo, que es la misma garantía).
            try:
                if cripto.descifrar(previa) == valor:
                    marca = previa
            except cripto.CriptoError:
                marca = None
        if marca is None:
            try:
                marca = cripto.cifrar(valor)
            except cripto.CriptoError as exc:
                _avisar_secretos(
                    f"no he podido cifrar «{clave}» ({exc}). El almacén se queda "
                    "EXACTAMENTE como estaba, en claro, y nexus sigue "
                    "funcionando con esas claves.")
                return None
        try:
            vuelta = cripto.descifrar(marca)
        except cripto.CriptoError as exc:
            vuelta = f"<no descifra: {exc}>"
        if vuelta != valor:
            _avisar_secretos(
                f"la comprobación de ida y vuelta falló para «{clave}»: lo que se "
                "descifra no es lo que se cifró. NO reescribo el almacén —una "
                "migración a medias perdería claves—.")
            return None
        nuevo[clave] = marca
    for clave, valor in ajenos.items():
        nuevo.setdefault(clave, valor)           # lo que no se puede abrir, intacto
    # Y el archivo tiene que volver a leerse EXACTAMENTE igual.
    try:
        if json.loads(json.dumps(nuevo, ensure_ascii=False)) != nuevo:
            _avisar_secretos(
                "el almacén cifrado no vuelve a leerse igual al serializarlo: NO "
                "lo reescribo.")
            return None
    except (TypeError, ValueError) as exc:
        _avisar_secretos(
            f"el almacén no se puede escribir como JSON ({exc}): NO lo reescribo.")
        return None
    return nuevo


def _guardar_secretos_en_disco(disco: dict) -> bool:
    """Escribe `secrets.json` SIN `.bak`, y solo si el archivo está entero.

    Por qué se acaba el `.bak` del almacén de claves (T13): era una copia EN
    CLARO del almacén, al lado del almacén. Cerrar SEC-09 en el principal y
    dejar la copia en claro no cierra nada. La escritura ya es atómica, así que el
    `.bak` tampoco hacía falta para eso; el archivo cifrado ES la copia (está en
    `config/`, que el operador respalda entero).

    El `.bak` que ya exista NO se borra desde aquí: es un archivo del operador.
    Lo cuenta `scripts/revisar_antes_de_subir.py --proteger-backups`.
    """
    try:
        escribir_json_atomico(SECRETS_FILE, disco, indent=2, respaldo=False)
        return True
    except (OSError, TypeError, ValueError) as exc:
        _avisar_secretos(
            f"no he podido guardar secrets.json ({exc}). Las claves de esta "
            "sesión siguen en memoria y el archivo anterior queda intacto.")
        return False


class Settings:
    """Acceso a configuración con recarga y guardado en caliente.

    Las API keys se guardan en config/secrets.json (editable desde el HUD ⚙) o
    en .env — nunca en settings.json ni se devuelven por la API. En disco van
    CIFRADAS con DPAPI desde T13 (SEC-09); en memoria, llanas, que es lo que
    necesitan los clientes HTTP.
    """

    SECRET_KEYS = ("openai_api_key", "anthropic_api_key", "gemini_api_key",
                   "elevenlabs_api_key", "cloud_llm_api_key",
                   "google_client_id", "google_client_secret",
                   "telegram_bot_token", "ig_access_token", "picovoice_key",
                   "n8n_api_key", "discord_webhook_url",
                   "spotify_client_id", "spotify_client_secret", "link_token",
                   "homeassistant_token", "samsung_tv_token", "hermes_api_key",
                   "openrouter_api_key",
                   # Secreto compartido de POST /api/n8n (auditoría, SEC-01). Va
                   # aquí para que set_secret lo guarde en secrets.json y para
                   # que as_dict() lo quite SIEMPRE de GET /api/config.
                   "n8n_secret",
                   # Auditoría 30/07/2026: la cadena de conexión LLEVA LA CONTRASEÑA
                   # de Postgres y salía en claro por GET /api/config, porque
                   # as_dict() solo añadía indicadores «has_*» y nunca quitaba nada.
                   "db_url", "db_password")

    def __init__(self):
        self._json = _load_json()
        # Tres cubos (ver _abrir_secretos): lo que se puede usar, lo que aquí NO
        # se puede abrir y se conserva intacto, y la marca de los que ya estaban
        # cifrados (para no re-cifrarlos en cada escritura).
        (self._secrets, self._secretos_ajenos,
         self._secretos_marcas) = _abrir_secretos(_leer_secretos_crudos())

    def get(self, key: str, default=None):
        if key in self._json:
            return self._json[key]
        env_val = os.getenv(f"NEXUS_{key.upper()}") or os.getenv(key.upper())
        if env_val is not None:
            return env_val
        return DEFAULTS.get(key, default)

    # ---------- secretos ----------
    def secret(self, key: str) -> str:
        """El valor en claro, con la precedencia de siempre: secrets.json > env > «».

        Si el valor está cifrado con OTRA máquina u otra cuenta de Windows, no
        está en el almacén utilizable y se cae a la variable de entorno (o «»).
        Eso NO es un vacío silencioso: al cargar se avisó en castellano con el
        nombre de la clave, y `secretos_ilegibles()` la sigue nombrando."""
        valor = self._secrets.get(key)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
        return (os.getenv(key.upper(), "") or "").strip()

    def secretos_ilegibles(self) -> list[str]:
        """Nombres de los secretos guardados que aquí NO se pueden usar.

        Cifrados con otra máquina u otra cuenta de Windows, guardados con un
        formato que no conocemos, o con un valor que no es texto. Están en el
        archivo —no se han borrado— pero `secret()` no los devuelve. Se nombran
        para que el fallo se pueda ver en vez de parecer «aquí no hay clave»."""
        return sorted(self._secretos_ajenos)

    def _es_secreto(self, key: str) -> bool:
        """¿Es este nombre un secreto?

        Además de la lista fija, valen los nombres DERIVADOS con sufijo:
        la skill de domótica guarda un token POR TELEVISOR
        («samsung_tv_token_<id>»), y como no estaba literalmente en la lista,
        `set_secret` lo tiraba EN SILENCIO. Resultado: cada orden a la tele
        volvía a emparejar desde cero y la tele acababa preguntando otra vez si
        permite el mando — o dejando de responder (30/07/2026)."""
        if key in self.SECRET_KEYS:
            return True
        return any(key.startswith(k + "_") for k in self.SECRET_KEYS)

    def set_secret(self, key: str, value: str) -> None:
        if not self._es_secreto(key):
            return
        if value:
            self._secrets[key] = value.strip()
        else:
            self._secrets.pop(key, None)
        # El valor ha cambiado (o se ha borrado): su marca vieja ya no vale y, si
        # estaba en el cubo de los que no se pueden abrir, el operador acaba de
        # poner uno bueno. Ponerlo a «» es justo la forma de quitarlo de en medio.
        self._secretos_marcas.pop(key, None)
        self._secretos_ajenos.pop(key, None)
        self._guardar_secretos()

    def _guardar_secretos(self) -> None:
        """Escribe el almacén: cifrado y verificado donde hay DPAPI, plano donde no.

        `set_secret` NO puede dejar el archivo a medias: si la verificación o el
        cifrado fallan, se avisa y el archivo se queda como estaba; el valor
        nuevo vive en memoria hasta la siguiente ocasión."""
        if cripto.disponible():
            disco = _cifrar_y_verificar(self._secrets, self._secretos_ajenos,
                                        self._secretos_marcas)
            if disco is None:
                return
        else:
            # Sin DPAPI se escribe exactamente como antes (JSON plano) y los
            # blobs que no se puedan abrir se devuelven intactos al archivo.
            disco = {**self._secrets, **self._secretos_ajenos}
        if _guardar_secretos_en_disco(disco):
            self._secretos_marcas = {k: v for k, v in disco.items()
                                     if cripto.es_cifrado(v)}

    @property
    def elevenlabs_key(self) -> str:
        return self.secret("elevenlabs_api_key")

    @property
    def cloud_api_key(self) -> str:
        return self.secret("cloud_llm_api_key") or self.secret("openai_api_key")

    def set(self, key: str, value) -> None:
        self._json[key] = value
        _write_json_atomic(CONFIG_FILE, self._json)

    def as_dict(self) -> dict:
        """La configuración TAL COMO SALE POR LA API. Ningún secreto en claro.

        Antes esto añadía los indicadores «has_*» pero NO borraba el valor: si un
        secreto acababa en settings.json (p. ej. por un POST /api/config), el
        siguiente GET lo devolvía entero. Ahora se quita primero y se informa
        después."""
        out = dict(DEFAULTS)
        out.update(self._json)
        # Una lista VACÍA no significa «ninguna carpeta»: significa «las de
        # siempre» (Documentos/Escritorio/Descargas). El HUD tiene que ver la
        # lista EFECTIVA para poder enseñarla en ⚙ → Permisos, y así lo que
        # enseña es lo que permissions aplica de verdad.
        if not out.get("perm_folders"):
            out["perm_folders"] = carpetas_permiso_por_defecto()
        for k in self.SECRET_KEYS:
            presente = bool(self.secret(k)) or bool(str(out.get(k) or "").strip())
            out.pop(k, None)                      # fuera el valor, siempre
            out[f"has_{k}"] = presente            # solo si lo hay o no
        # y los derivados («samsung_tv_token_<id>»), que también son secretos
        for k in [x for x in out if self._es_secreto(x)]:
            out.pop(k, None)
        return out


settings = Settings()


# ---------------- IDENTIDAD DEL SISTEMA (white-label) ----------------
def assistant_name() -> str:
    """Nombre del asistente elegido en la instalación (por defecto «nexus»)."""
    return (settings.get("assistant_name") or "nexus").strip() or "nexus"


def assistant_slug() -> str:
    """Slug seguro del nombre para Docker/BD (minúsculas, ascii, guiones_bajos).
    «Helios»→`helios`, «Mi Casa IA»→`mi_casa_ia`. Por defecto `nexus`."""
    import re as _re
    import unicodedata as _u
    n = _u.normalize("NFKD", assistant_name().lower())
    n = "".join(c for c in n if not _u.combining(c))
    n = _re.sub(r"[^a-z0-9]+", "_", n).strip("_")
    return n or "nexus"


def assistant_pron() -> str:
    """Cómo se PRONUNCIA en voz. Si no se especifica, se lee el nombre tal cual
    («nexus» se pronuncia «nexus»); se puede forzar otra grafía con assistant_pron."""
    p = (settings.get("assistant_pron") or "").strip()
    if p:
        return p
    return assistant_name()


def voice_gender() -> str:
    """'f' o 'm' según la VOZ TTS elegida, para que el asistente hable DE SÍ MISMO en el
    género correcto (Elvira/Dalia/Elena/Salomé… = f; Álvaro/Jorge/Tomás… = m). Si el
    usuario pone una voz de mujer, nexus se refiere a sí en femenino, y viceversa.
    Por defecto 'f' (la voz de serie es Elvira)."""
    v = (settings.get("tts_voice") or "").strip().lower()
    masc = ("álvaro", "alvaro", "jorge", "tomás", "tomas", "adam", "antoni", "guy",
            "diego", "masculin", "male", "hombre", "(m)")
    fem = ("elvira", "dalia", "elena", "salom", "rachel", "bella", "aria", "jenny",
           "paloma", "femenin", "female", "mujer", "(f)")
    if any(h in v for h in masc):
        return "m"
    if any(h in v for h in fem):
        return "f"
    return "f"
