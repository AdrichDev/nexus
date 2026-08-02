"""
nexus — Lanzador de escritorio (punto de entrada del .exe).

Arranca el servidor FastAPI en un hilo y abre el HUD en una ventana
PyWebview SIN MARCO (arrastrable desde la cabecera, minimizable desde
el propio HUD). Si PyWebview no está disponible, abre el navegador.

Ejecución en desarrollo:   python -m backend.desktop
Ejecución empaquetada:     nexus.exe (PyInstaller, ver installer/nexus.spec)
"""
from __future__ import annotations

import os
import socket
import threading
import time
import warnings
import webbrowser

# Silenciar avisos inofensivos de HuggingFace/whisper (symlinks en Windows, HF_TOKEN)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
warnings.filterwarnings("ignore", category=UserWarning, module="huggingface_hub")

# Permitir el AUDIO AUTOMÁTICO en la ventana: WebView2/Chromium bloquea por defecto
# el sonido antes del primer clic del usuario, y eso dejaba MUDA la música de la
# secuencia de arranque. Debe fijarse ANTES de importar/arrancar webview.
os.environ.setdefault(
    "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
    "--autoplay-policy=no-user-gesture-required",
)

import uvicorn

# BIND es a QUÉ interfaces se ata uvicorn; HOST es a dónde apunta la ventana.
# No son lo mismo y confundirlos rompe una de las dos cosas: «0.0.0.0» significa
# «escucha en todas», pero como destino no vale nada — la ventana tiene que ir a
# 127.0.0.1. Atado solo a loopback, el móvil NO podía entrar por la WiFi: el QR
# ofrecía «MIPC.local:8177» y esa dirección rechazaba la conexión (31/07/2026).
# Abrirlo a la LAN es seguro porque el middleware de app.py exige el token del QR
# a todo origen que no sea este mismo equipo.
BIND, HOST, PORT = "0.0.0.0", "127.0.0.1", 8177
URL = f"http://{HOST}:{PORT}"


class JsApi:
    """API expuesta a JavaScript (window.pywebview.api.*).

    IMPORTANTE: la referencia a la ventana debe ser PRIVADA (_window).
    pywebview serializa los atributos públicos del js_api y, si guardas la
    ventana en uno público, entra en recursión infinita intentando serializar
    window.native.AccessibilityObject.Bounds.Empty.Empty... (bug conocido).
    """

    def __init__(self):
        self._window = None
        self._maximized = False

    def set_window(self, window):
        self._window = window

    def minimize(self):
        if self._window:
            self._window.minimize()

    def maximize(self):
        """Alterna maximizado/restaurado (fallback a fullscreen en pywebview viejos)."""
        if not self._window:
            return
        try:
            if self._maximized:
                self._window.restore()
            else:
                self._window.maximize()
            self._maximized = not self._maximized
        except AttributeError:
            self._window.toggle_fullscreen()

    def close(self):
        if self._window:
            self._window.destroy()


def _run_server():
    from backend.app import app
    uvicorn.run(app, host=BIND, port=PORT, log_level="warning")


def _wait_for_server(timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main():
    threading.Thread(target=_run_server, daemon=True).start()
    if not _wait_for_server():
        raise SystemExit("El servidor nexus no ha arrancado a tiempo.")

    try:
        import webview
        api = JsApi()
        window = webview.create_window(
            "nexus — COMMAND CENTER",
            URL,
            width=1480, height=860,
            frameless=True,          # el HUD dibuja su propia cabecera
            easy_drag=False,         # se arrastra solo desde .pywebview-drag-region
            background_color="#070e18",
            js_api=api,
        )
        api.set_window(window)
        webview.start(debug=False)
    except Exception as exc:
        # Fallback: navegador del sistema. Mostramos el MOTIVO para poder diagnosticar
        # (lo más común: pywebview no puede crear la ventana nativa porque pythonnet
        # no funciona en tu Python —típico en 3.13/3.14— o falta el WebView2 Runtime).
        import traceback
        print("\n[nexus] No pude abrir la VENTANA DE ESCRITORIO (pywebview):")
        print(f"         {type(exc).__name__}: {exc}")
        print("         Causa habitual: Python 3.13/3.14 (pythonnet no va ahí) o falta")
        print("         el «Microsoft Edge WebView2 Runtime».")
        print("         Solución: usa Python 3.12 (borra la carpeta .venv y ejecuta run.bat,")
        print("         que ahora lo recrea solo), o instala el WebView2 Runtime.")
        traceback.print_exc()
        print(f"\n[nexus] Mientras tanto, abro el HUD en el navegador: {URL}\n")
        webbrowser.open(URL)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
