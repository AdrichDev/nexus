"""
nexus — Cliente de la API de Spotify (autoplay REAL).

Con una cuenta Spotify PREMIUM y una app creada en developer.spotify.com,
nexus puede buscar una canción y REPRODUCIRLA de verdad en la app de
escritorio (sin que tengas que pulsar play).

Configuración (una sola vez):
  1. https://developer.spotify.com/dashboard → Create app.
  2. En "Redirect URIs" añade EXACTAMENTE:  http://127.0.0.1:8177/api/spotify/callback
  3. Copia el Client ID y el Client Secret en ⚙ (Configuración → SPOTIFY).
  4. Di «pon <canción> en spotify»: la PRIMERA vez se abre el navegador para
     autorizar (30 segundos); después, autoplay directo para siempre.

El token se guarda en config/spotify_token.json y se refresca solo.

Las DOS rutas de estado se montan con `CONFIG_DIR` (comun/config.py), nunca con
la raíz del proyecto a mano: el 30/07/2026 se descubrió (task T36, al cerrar T13)
que `spotify.py` las construía desde `ROOT`, así que ignoraba `NEXUS_CONFIG_DIR`
y dejaba un `spotify_pending.json` y un `spotify_token.json` en el `config/` del
repositorio incluso con una carpeta de usar y tirar. `CONFIG_DIR` es la única
fuente de verdad para "dónde vive la configuración".

El `state` del OAuth (SEC-15, auditoría 30/07/2026) se guarda aparte, en
config/spotify_pending.json, y VIVE UN SOLO USO: lo escribe `auth_url()`, lo
comprueba y lo gasta `consumir_estado()`, y caduca a los `TTL_ESTADO` segundos.
Sin él, cualquiera podía pegar en el callback un `code` de SU cuenta y dejar el
nexus del operador vinculado a la cuenta del atacante (login CSRF).
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
import secrets
import time
from urllib.parse import quote, urlencode


from ..comun import net
from ..comun.atomicos import escribir_json_atomico
from ..comun.config import CONFIG_DIR, settings

TOKEN_FILE = CONFIG_DIR / "spotify_token.json"
PENDING_FILE = CONFIG_DIR / "spotify_pending.json"
REDIRECT_URI = "http://127.0.0.1:8177/api/spotify/callback"
SCOPES = "user-modify-playback-state user-read-playback-state"
# Diez minutos para ir al navegador, iniciar sesión y volver: de sobra, y corto
# para que un enlace viejo no sirva mañana.
TTL_ESTADO = 600
_API = "https://api.spotify.com/v1"


# ------------------------------------------------------------------ credenciales
def client_id() -> str:
    return settings.secret("spotify_client_id")


def client_secret() -> str:
    return settings.secret("spotify_client_secret")


def is_configured() -> bool:
    """¿Hay Client ID + Secret guardados en ⚙?"""
    return bool(client_id() and client_secret())


def _load_token() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_token(tok: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok, indent=2), encoding="utf-8")


def is_authorized() -> bool:
    """¿El usuario ya autorizó a nexus (hay refresh_token guardado)?"""
    return bool(_load_token().get("refresh_token"))


def auth_url() -> str:
    """URL para que el usuario autorice a nexus (se abre una sola vez).

    Cada llamada genera un `state` NUEVO y lo deja pendiente en disco: el
    callback tiene que traer ESE, exacto. Si se abre dos veces, el segundo es el
    que vale (el primero queda inservible), que es lo que espera quien acaba de
    pedir la canción."""
    return "https://accounts.spotify.com/authorize?" + urlencode({
        "client_id": client_id(),
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": _nuevo_estado(),
    })


# --------------------------------------------------------------- `state` OAuth
def _nuevo_estado() -> str:
    """Genera y APUNTA el `state` pendiente. 24 bytes al azar: no se adivina."""
    estado = secrets.token_urlsafe(24)
    escribir_json_atomico(PENDING_FILE, {"state": estado, "creado": time.time()})
    return estado


def _borra_pendiente() -> None:
    try:
        PENDING_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _pendiente() -> dict:
    try:
        dato = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        return dato if isinstance(dato, dict) else {}
    except Exception:                                          # noqa: BLE001
        return {}


def consumir_estado(state: str) -> bool:
    """¿Este `state` es el que acabo de generar? Si sí, LO GASTA antes de devolver.

    Tres cosas a la vez, y las tres importan:
      * comparación en TIEMPO CONSTANTE (`hmac.compare_digest`): un `!=` normal
        deja adivinar el valor carácter a carácter midiendo lo que tarda.
        Se compara en BYTES porque `compare_digest` con `str` exige ASCII puro y
        lanza TypeError con un carácter raro (500 en vez de «no vale»).
      * se CONSUME aquí, antes de canjear el `code`: un callback repetido con el
        mismo enlace no puede gastar dos códigos.
      * un intento FALLIDO no toca el pendiente: si lo borrara, cualquiera que
        mande un callback falso tumbaría la autorización que está en curso.

    Callback sin `state`, con otro `state` o caducado → False, y el que llama
    contesta en cristiano sin canjear nada."""
    pend = _pendiente()
    esperado = str(pend.get("state") or "")
    recibido = "" if state is None else str(state)
    if not esperado or not recibido:
        return False
    if not hmac.compare_digest(esperado.encode("utf-8", "surrogatepass"),
                               recibido.encode("utf-8", "surrogatepass")):
        return False
    try:
        creado = float(pend.get("creado") or 0)
    except (TypeError, ValueError):
        creado = 0.0
    if creado and time.time() - creado > TTL_ESTADO:
        _borra_pendiente()          # un `state` viejo no puede revivir
        return False
    _borra_pendiente()              # SE GASTA AQUÍ, antes del intercambio
    return True


def _basic_auth() -> str:
    raw = f"{client_id()}:{client_secret()}".encode()
    return "Basic " + base64.b64encode(raw).decode()


async def exchange_code(code: str) -> bool:
    """Cambia el 'code' del callback OAuth por tokens (primera autorización)."""
    r = await net.client().post("https://accounts.spotify.com/api/token",
                                headers={"Authorization": _basic_auth()},
                                data={"grant_type": "authorization_code",
                                      "code": code, "redirect_uri": REDIRECT_URI},
                                timeout=15)
    if r.status_code != 200:
        return False
    tok = r.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    _save_token(tok)
    return True


async def _access_token() -> str:
    """Access token vigente (refresca solo si caducó). '' si no hay autorización."""
    tok = _load_token()
    if not tok.get("refresh_token"):
        return ""
    if tok.get("access_token") and time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    r = await net.client().post("https://accounts.spotify.com/api/token",
                                headers={"Authorization": _basic_auth()},
                                data={"grant_type": "refresh_token",
                                      "refresh_token": tok["refresh_token"]},
                                timeout=15)
    if r.status_code != 200:
        return ""
    new = r.json()
    tok["access_token"] = new.get("access_token", "")
    tok["expires_at"] = time.time() + new.get("expires_in", 3600) - 60
    if new.get("refresh_token"):
        tok["refresh_token"] = new["refresh_token"]
    _save_token(tok)
    return tok["access_token"]


# ------------------------------------------------------------------ reproducción
async def search_track(query: str) -> dict | None:
    """Primer resultado de canción: {uri, name, artist} o None."""
    at = await _access_token()
    if not at:
        return None
    r = await net.client().get(f"{_API}/search",
                               headers={"Authorization": f"Bearer {at}"},
                               params={"q": query, "type": "track", "limit": 1,
                                       "market": "ES"}, timeout=12)
    if r.status_code != 200:
        return None
    items = (r.json().get("tracks") or {}).get("items") or []
    if not items:
        return None
    t = items[0]
    return {"uri": t["uri"], "name": t["name"],
            "artist": ", ".join(a["name"] for a in t.get("artists", []))}


async def _devices(at: str) -> list[dict]:
    r = await net.client().get(f"{_API}/me/player/devices",
                               headers={"Authorization": f"Bearer {at}"}, timeout=12)
    return (r.json().get("devices") or []) if r.status_code == 200 else []


async def _play_on(at: str, uri: str, device_id: str | None) -> int:
    params = {"device_id": device_id} if device_id else {}
    r = await net.client().put(f"{_API}/me/player/play", params=params,
                               headers={"Authorization": f"Bearer {at}"},
                               json={"uris": [uri]}, timeout=12)
    return r.status_code


async def play_track(uri: str) -> tuple[bool, str]:
    """Reproduce la canción. Si Spotify está cerrado, lo abre y reintenta.
    Devuelve (ok, detalle)."""
    at = await _access_token()
    if not at:
        return False, "sin autorización"
    code = await _play_on(at, uri, None)
    if code in (200, 202, 204):
        return True, ""
    # 404 = no hay dispositivo activo → abrimos la app de Spotify y reintentamos
    if code == 404:
        try:
            os.startfile("spotify:")           # Windows: abre/activa la app
        except Exception:
            pass
        for wait in (3, 3, 4):                 # hasta ~10 s a que registre el device
            await asyncio.sleep(wait)
            devs = await _devices(at)
            if devs:
                dev = next((d for d in devs if d.get("type") == "Computer"), devs[0])
                code = await _play_on(at, uri, dev.get("id"))
                if code in (200, 202, 204):
                    return True, ""
                break
        return False, "no encuentro un dispositivo de Spotify activo (¿sesión iniciada?)"
    if code == 403:
        return False, "Spotify dice 403 — el autoplay por API requiere cuenta PREMIUM"
    if code == 401:
        return False, "token caducado o revocado — vuelve a autorizar"
    return False, f"Spotify respondió HTTP {code}"


async def play_query(query: str) -> tuple[bool, str]:
    """Busca y reproduce en un paso. Devuelve (ok, mensaje)."""
    track = await search_track(query)
    if not track:
        return False, f"no encuentro «{query}» en Spotify"
    ok, why = await play_track(track["uri"])
    if ok:
        return True, f"{track['name']} — {track['artist']}"
    return False, why


def open_search_fallback(query: str) -> None:
    """Plan B sin API: abre la app en la búsqueda (el usuario pulsa play)."""
    try:
        os.startfile("spotify:search:" + quote(query))
    except Exception:
        import webbrowser
        webbrowser.open("https://open.spotify.com/search/" + quote(query))
