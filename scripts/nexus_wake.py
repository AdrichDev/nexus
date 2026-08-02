"""
nexus — Activación por DOS PALMADAS (abrir el programa con un gesto sonoro).

Proceso LIGERO e independiente que corre en segundo plano escuchando el micrófono.
Cuando detecta DOS PALMADAS seguidas (dos GOLPES SECOS y cortos, cada uno precedido
de silencio, con una pequeña pausa entre ellos), LANZA el programa (ventana HUD).

Por qué palmadas y no voz: el reconocimiento de voz (whisper) no siempre entendía
bien «despierta nexus» y dependía de la GPU/DLLs. Las palmadas son un detector de
energía muy simple y robusto: solo necesita sounddevice + numpy (NADA de modelos,
GPU ni claves), así que va fino en cualquier PC.

ANTI-FALSOS-POSITIVOS (v2): un ruido fuerte y SOSTENIDO (música, voces, un golpe
largo) ya NO abre el programa. Para contar como palmada, el sonido tiene que ser un
GOLPE SECO: pico alto, con el instante ANTERIOR en silencio (flanco de subida brusco)
y PRECEDIDO de un silencio real. Como la música/ruido continuo no tiene esos silencios
entre golpes, no dispara. Hacen falta DOS de esos golpes seguidos.

Deja rastro en data/wake.log (qué oye, picos, palmadas) y captura el arranque del
programa en data/wake_launch.log para diagnosticar si algo fallara. Escribe su PID en
data/wake.pid para que scripts/quitar_arranque_voz.bat pueda pararlo de forma fiable.

Arranque automático al encender Windows: usa scripts/instalar_arranque_voz.bat.
"""
from __future__ import annotations

import atexit
import datetime as _dt
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

# Este archivo vive en scripts/, pero ROOT tiene que ser la RAÍZ del proyecto:
# de ahí cuelgan .venv/, data/ (log y PID) y el paquete backend que se lanza con
# `-m backend.desktop`. Apuntando a scripts/ no encontraría ni el intérprete ni
# el módulo, y las palmadas dejarían de abrir nada.
ROOT = Path(__file__).resolve().parent.parent
HOST, PORT = "127.0.0.1", 8177

# ---- parámetros de detección de palmadas (ajustables) ----
SR = 16000            # frecuencia de muestreo
BLOCK = 512           # tamaño de bloque (~32 ms) → buena resolución del transitorio
ABS_MIN = 0.28        # pico mínimo absoluto (0..1) para considerar «palmada» (subido)
RATIO = 6.0           # cuántas veces por encima del ruido de fondo
ONSET_DROP = 0.6      # el bloque ANTERIOR debe estar por debajo de umbral×esto (flanco seco)
QUIET_BEFORE = 0.10   # s de SILENCIO necesarios ANTES de una palmada (mata el ruido sostenido)
MIN_GAP = 0.15        # s: separación MÍNIMA entre las dos palmadas
MAX_GAP = 0.90        # s: separación MÁXIMA entre las dos palmadas
COOLDOWN = 2.5        # s: pausa tras activar (anti-rebote)

# REGISTRO: el escuchador corre OCULTO (pythonw, sin consola) → deja rastro en fichero.
LOG = ROOT / "data" / "wake.log"
PIDFILE = ROOT / "data" / "wake.pid"


def _log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{_dt.datetime.now():%H:%M:%S}  {msg}\n")
    except Exception:
        pass
    try:
        print(f"[WAKE] {msg}")
    except Exception:
        pass


def _write_pid() -> None:
    """Deja el PID para que el desinstalador pueda pararnos con seguridad."""
    try:
        PIDFILE.parent.mkdir(parents=True, exist_ok=True)
        PIDFILE.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(_clear_pid)
    except Exception:
        pass


def _clear_pid() -> None:
    try:
        PIDFILE.unlink(missing_ok=True)
    except Exception:
        pass


def _app_running() -> bool:
    """True si nexus ya está abierto (su servidor responde en 127.0.0.1:8177)."""
    try:
        with socket.create_connection((HOST, PORT), timeout=0.4):
            return True
    except OSError:
        return False


def _launch_app() -> None:
    """Abre el HUD. Si nexus ya está corriendo, NO relanza. Registra qué hace y
    captura la salida del arranque en data/wake_launch.log para diagnosticar."""
    if _app_running():
        _log("nexus ya estaba ABIERTO (responde en 127.0.0.1:8177) → no lo relanzo.")
        return
    py = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    py = py if py.exists() else Path(sys.executable)
    cmd = [str(py), "-m", "backend.desktop"]
    _log(f"lanzando nexus: {py.name} -m backend.desktop (cwd={ROOT.name})")
    try:
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        logf = open(ROOT / "data" / "wake_launch.log", "a", encoding="utf-8", buffering=1)
        logf.write(f"\n===== lanzamiento {_dt.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        subprocess.Popen(cmd, cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT)
    except Exception as exc:
        _log(f"FALLO al lanzar: {type(exc).__name__}: {exc}")
        return
    for _ in range(16):                 # ¿arrancó? hasta ~8 s para que uvicorn responda
        time.sleep(0.5)
        if _app_running():
            _log("nexus ARRANCÓ ✓ (el servidor ya responde).")
            return
    _log("lanzado, pero el servidor NO respondió a tiempo → revisa data/wake_launch.log")


class ClapDetector:
    """Máquina de estados para detectar DOS PALMADAS SECAS. Se alimenta con el PICO de
    cada bloque de audio y devuelve un evento por bloque (sin audio dentro → testeable).

    Una palmada válida = GOLPE SECO: pico ≥ umbral, con el bloque ANTERIOR en silencio
    (flanco de subida) y PRECEDIDO de ≥ QUIET_BEFORE de silencio. El ruido fuerte y
    sostenido NO cumple (no hay silencios entre medias) → no dispara."""

    def __init__(self):
        self.nf = 0.02          # ruido de fondo estimado (se adapta solo en silencio)
        self.first_t = 0.0      # instante de la 1ª palmada (0 = ninguna aún)
        self.prev = 0.0         # pico del bloque anterior (para detectar el flanco)
        self.quiet = 1.0        # s en silencio acumulados (arranca "en silencio")
        self.last_t = None      # para calcular dt real entre bloques

    def feed(self, peak: float, now: float) -> str:
        """Devuelve: 'trigger' (dos palmadas), 'first' (1ª palmada), o '' (nada)."""
        dt = 0.032 if self.last_t is None else max(0.0, min(0.2, now - self.last_t))
        self.last_t = now
        thr = max(ABS_MIN, self.nf * RATIO)
        evt = ""
        loud = peak >= thr
        # GOLPE SECO: alto AHORA, el anterior por debajo del umbral (flanco brusco) y
        # con silencio suficiente por delante (si el ruido es sostenido, self.quiet≈0).
        onset = loud and self.prev < thr * ONSET_DROP and self.quiet >= QUIET_BEFORE
        if onset:
            if self.first_t and (MIN_GAP <= now - self.first_t <= MAX_GAP):
                self.first_t = 0.0
                evt = "trigger"
            else:
                self.first_t = now                  # 1ª palmada: espera la 2ª
                evt = "first"
            self.quiet = 0.0
        elif not loud:
            self.quiet += dt                        # sumando silencio
            self.nf = 0.98 * self.nf + 0.02 * peak  # adapta el ruido de fondo
        else:
            self.quiet = 0.0                        # ruido alto pero no seco → reinicia silencio
        if self.first_t and (now - self.first_t) > MAX_GAP:
            self.first_t = 0.0                      # pasó demasiado sin la 2ª → reinicia
        self.prev = peak
        return evt

    def reset(self) -> None:
        self.first_t = 0.0
        self.prev = 0.0
        self.quiet = 1.0

    def threshold(self) -> float:
        return max(ABS_MIN, self.nf * RATIO)


def run_claps() -> None:
    """Bucle principal: detecta DOS palmadas y abre nexus."""
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        _log(f"falta sounddevice/numpy: {exc}. Instálalo con run.bat.")
        return
    try:
        _log(f"micrófono de entrada: {sd.query_devices(kind='input')['name']}")
    except Exception:
        pass

    det = ClapDetector()
    last_hb = 0.0
    _log("ESCUCHANDO dos palmadas SECAS… 👏👏 (da dos palmadas fuertes y separadas)")
    try:
        stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=BLOCK)
        stream.start()
    except Exception as exc:
        _log(f"NO pude abrir el micrófono: {exc}")
        return

    while True:
        try:
            data, _of = stream.read(BLOCK)
            peak = float(np.max(np.abs(data))) if getattr(data, "size", 0) else 0.0
            now = time.monotonic()
            evt = det.feed(peak, now)
            if evt == "trigger":
                _log(f"👏👏 ¡DOS PALMADAS! (pico {peak:.2f}, umbral {det.threshold():.2f}) → abriendo nexus")
                _launch_app()
                det.reset()
                time.sleep(COOLDOWN)
            elif evt == "first":
                _log(f"palmada 1 (pico {peak:.2f}, umbral {det.threshold():.2f}); esperando la 2ª…")
            if now - last_hb > 30:                  # latido cada ~30 s (sigue vivo + ruido)
                last_hb = now
                _log(f"(vivo · ruido de fondo {det.nf:.3f} · umbral {det.threshold():.2f})")
        except Exception as exc:
            _log(f"error en el bucle: {exc}")
            time.sleep(1)


def main() -> None:
    _log("=== arranque del escuchador de PALMADAS (nexus_wake) ===")
    _write_pid()
    run_claps()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _log(f"CAÍDA del escuchador: {type(exc).__name__}: {exc}")
        raise
