"""
nexus — Configuración central.

Carga variables de .env y del archivo config/settings.json (editable en caliente
desde el HUD).  Prioridad: settings.json > .env > valores por defecto.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

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
    BUNDLE = ROOT = Path(__file__).resolve().parents[2]


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
    "perm_files": "todo",              # sandbox | carpetas | todo
    "perm_folders": [],                # carpetas permitidas si perm_files='carpetas'
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
    indivisible), así el archivo NUNCA queda truncado aunque dos procesos escriban a
    la vez o el proceso muera a mitad —el bug que rompía settings.json/secrets.json—.
    Antes respalda en `.bak` la versión actual SOLO si es JSON válido."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))     # valida la versión previa
            import shutil
            shutil.copy2(path, path.with_name(path.name + ".bak"))
    except Exception:
        pass                                                 # no respaldar basura
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)                                    # atómico


def _load_json() -> dict:
    return _read_json_safe(CONFIG_FILE)


def _load_secrets() -> dict:
    return _read_json_safe(SECRETS_FILE)


class Settings:
    """Acceso a configuración con recarga y guardado en caliente.

    Las API keys se guardan en config/secrets.json (editable desde el HUD ⚙)
    o en .env — nunca en settings.json ni se devuelven por la API.
    """

    SECRET_KEYS = ("openai_api_key", "anthropic_api_key", "gemini_api_key",
                   "elevenlabs_api_key", "cloud_llm_api_key",
                   "google_client_id", "google_client_secret",
                   "telegram_bot_token", "ig_access_token", "picovoice_key",
                   "n8n_api_key", "discord_webhook_url",
                   "spotify_client_id", "spotify_client_secret", "link_token",
                   "homeassistant_token", "samsung_tv_token", "hermes_api_key",
                   "openrouter_api_key",
                   # Auditoría 30/07/2026: la cadena de conexión LLEVA LA CONTRASEÑA
                   # de Postgres y salía en claro por GET /api/config, porque
                   # as_dict() solo añadía indicadores «has_*» y nunca quitaba nada.
                   "db_url", "db_password")

    def __init__(self):
        self._json = _load_json()
        self._secrets = _load_secrets()

    def get(self, key: str, default=None):
        if key in self._json:
            return self._json[key]
        env_val = os.getenv(f"NEXUS_{key.upper()}") or os.getenv(key.upper())
        if env_val is not None:
            return env_val
        return DEFAULTS.get(key, default)

    # ---------- secretos ----------
    def secret(self, key: str) -> str:
        return (self._secrets.get(key) or os.getenv(key.upper(), "") or "").strip()

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
        _write_json_atomic(SECRETS_FILE, self._secrets)

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
