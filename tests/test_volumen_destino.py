# -*- coding: utf-8 -*-
"""El volumen SIEMPRE lleva destino, y nexus no se lo inventa.

Tres familias y una regla:

  * la TELE  -> `domotica/tv_volume`, que EXIGE la palabra tele/tv, igual que
    ya hacía `tv_mute`. Antes no la exigía y se quedaba con «baja el volumen de
    chrome», porque va antes que `system_pc` por orden alfabético.
  * el PC    -> `system_pc/volume`, mezclador maestro de Windows por pycaw.
  * una APP  -> `system_pc/volume_app`, la sesión de audio de ese proceso.
  * SIN destino -> `system_pc/volume_ask`, que PREGUNTA. Ni actúa ni cae al
    planificador.

No basta con comprobar el enrutado: aquí se ejecuta `handle()` y se mira lo que
devuelve. Y si la máquina tiene pycaw (el .venv del proyecto lo tiene), se
escribe en el dispositivo de verdad y se lee de vuelta, restaurando el estado
original al terminar.

Ejecutar:  python tests\\test_volumen_destino.py
           .venv\\Scripts\\python.exe tests\\test_volumen_destino.py   (con pycaw)
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus_volumen_"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                          # noqa: BLE001
    pass

_fail: list[str] = []
_pass = 0


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


from backend.core import skills_loader as sl                # noqa: E402

REG = sl.load_skills()
SPC = REG["system_pc"].module
DOM = REG["domotica"].module


def _ruta(frase: str) -> str:
    r = sl.route(frase)
    return f"{r[0].folder}/{r[1]}" if r else "NADIE"


def _corre(frase: str) -> str:
    """Ejecuta el handler de verdad y devuelve la respuesta."""
    r = sl.route(frase)
    assert r, f"«{frase}» no enruta"
    skill, intent, m = r
    return asyncio.run(skill.module.handle(intent, frase, m, {"bus": None}))["reply"]


# =================== 1) ENRUTADO: cada destino a su sitio ====================
print("== 1) el destino manda: tele, PC, aplicación o pregunta ==")

DESTINOS = {
    # La tele solo si la orden la nombra
    "domotica/tv_volume": ["sube el volumen de la tele", "bájale el volumen a la tv",
                           "más volumen en la televisión", "baja el volumen del televisor",
                           "menos volumen en la tele", "súbeme el volumen de la smart tv"],
    # Este PC
    "system_pc/volume": ["sube el volumen del pc", "baja el volumen del ordenador",
                         "pon el volumen del pc al 40", "sube el volumen del equipo",
                         "sube el volumen del sistema", "silencia el pc",
                         "quita el sonido del ordenador", "quita el silencio del pc",
                         "desilencia el pc"],
    # Una aplicación por su nombre
    "system_pc/volume_app": ["sube el volumen de spotify", "baja el volumen de chrome",
                             "pon el volumen de discord al 30", "silencia spotify",
                             "quita el sonido de chrome", "quita el silencio de spotify",
                             "silencia el spotify", "sube el volumen de firefox"],
    # Sin destino: se pregunta
    "system_pc/volume_ask": ["sube el volumen", "más volumen", "sube un poco el volumen",
                             "pon el volumen al 50", "volumen al 75%", "baja el volumen",
                             "menos volumen", "silencia", "quita el sonido",
                             "bájale al volumen que está muy alto"],
}
for esperado, frases in DESTINOS.items():
    for f in frases:
        check(_ruta(f) == esperado, f"«{f}» → {_ruta(f)}, se esperaba {esperado}")


# ============ 2) LO QUE MOTIVÓ EL CAMBIO: domotica no se lo queda =============
print("== 2) domotica ya no se queda el volumen que no es de la tele ==")
for f in ("sube el volumen", "más volumen", "pon el volumen al 50",
          "baja el volumen de chrome", "sube el volumen de spotify",
          "sube el volumen del pc", "silencia", "quita el sonido"):
    r = sl.route(f)
    check(r is not None and r[0].folder != "domotica",
          f"«{f}» sigue yéndose a domotica: el volumen sin tele no es de la tele")

check("(?!" not in DOM.SKILL["patterns"]["tv_volume"],
      "tv_volume sigue acotándose por lista de exclusión: con la tele exigida sobra")
for tv in ("tele", "tv", "televisi", "televisor"):
    check(tv in DOM.SKILL["patterns"]["tv_volume"],
          f"tv_volume no exige la palabra «{tv}»")


# ================ 3) NADA SE QUEDA SIN CONTESTAR (ni de más) =================
print("== 3) el orden de los patrones y las frases ajenas ==")
ORDEN = list(REG["system_pc"].patterns)
check(ORDEN.index("volume") < ORDEN.index("volume_app"),
      "volume tiene que ir ANTES que volume_app, o «del pc» se lee como un programa")
check(ORDEN.index("volume_app") < ORDEN.index("volume_ask"),
      "volume_app tiene que ir ANTES que volume_ask, o la app se pierde en la pregunta")

# La forma corta «silencia X» no puede robarle la frase a otras skills
for f in ("silencia los recordatorios", "silencia las notificaciones",
          "silencia el móvil", "silencia la tele"):
    r = sl.route(f)
    check(r is None or r[0].folder != "system_pc" or r[1] not in ("volume_app", "volume_ask"),
          f"«{f}» se la queda el volumen del PC y no es suya: → {_ruta(f)}")


# ============ 4) EL HANDLER: pregunta, no adivina, no miente ================
print("== 4) el handler: sin destino pregunta y no dice que ha hecho nada ==")
for f in ("sube el volumen", "pon el volumen al 50", "silencia", "quita el sonido"):
    txt = _corre(f)
    check("?" in txt, f"«{f}»: no pregunta nada: {txt[:80]}")
    for opcion in ("tele", "pc", "aplicaci"):
        check(opcion in txt.lower(), f"«{f}»: no nombra la opción «{opcion}»: {txt[:110]}")
    check("✔" not in txt, f"«{f}»: se apunta un tanto sin haber tocado nada: {txt[:80]}")


# ============ 5) EL HANDLER: emparejar la aplicación con su proceso ==========
print("== 5) emparejado de aplicaciones: exacto antes que subcadena ==")


class _Vol:
    """Sesión de audio de mentira, con la misma interfaz que SimpleAudioVolume."""

    def __init__(self, nivel=1.0, mute=0):
        self.nivel, self.mute = nivel, mute

    def GetMasterVolume(self):
        return self.nivel

    def SetMasterVolume(self, v, _):
        self.nivel = v

    def GetMute(self):
        return self.mute

    def SetMute(self, m, _):
        self.mute = m


class _Parche:
    """Sustituye funciones del módulo mientras dura el bloque."""

    def __init__(self, **kw):
        self.kw = kw
        self.old = {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(SPC, k)
            setattr(SPC, k, v)

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(SPC, k, v)


SES = [("Spotify.exe", _Vol()), ("chrome.exe", _Vol()), ("codecs_host.exe", _Vol())]
with _Parche(_porque_no_pycaw=lambda: "", _sesiones_audio=lambda: SES):
    check([n for n, _ in SPC._sesiones_de("spotify")] == ["Spotify.exe"],
          "«spotify» no encuentra Spotify.exe (el emparejado distingue mayúsculas)")
    check([n for n, _ in SPC._sesiones_de("SPOTIFY.EXE")] == ["Spotify.exe"],
          "«SPOTIFY.EXE» no encuentra Spotify.exe")
    check([n for n, _ in SPC._sesiones_de("chrome")] == ["chrome.exe"],
          "«chrome» no encuentra chrome.exe")
    # el nombre exacto manda: «codecs» no debe llevarse nada que solo lo contenga
    check([n for n, _ in SPC._sesiones_de("codecs_host")] == ["codecs_host.exe"],
          "el nombre exacto no gana a la subcadena")
    check([n for n, _ in SPC._sesiones_de("codecs")] == ["codecs_host.exe"],
          "la subcadena no funciona cuando no hay nombre exacto")
    check(SPC._sesiones_de("noexiste") == [],
          "encuentra sesiones de una aplicación que no está sonando")
    # el alias coloquial también vale: «la música» es Spotify
    check([n for n, _ in SPC._sesiones_de("musica")] == ["Spotify.exe"],
          "el alias «musica» no llega a Spotify.exe")


# ============ 6) EL HANDLER: actúa de verdad sobre la sesión =================
print("== 6) el handler de aplicación escribe y lee de vuelta ==")
spo = _Vol(nivel=0.80, mute=0)
with _Parche(_porque_no_pycaw=lambda: "", _sesiones_audio=lambda: [("Spotify.exe", spo)]):
    txt = _corre("pon el volumen de spotify al 30")
    check(abs(spo.nivel - 0.30) < 0.01, f"no ha escrito el 30% en la sesión: {spo.nivel}")
    check("30" in txt and "✔" in txt, f"no confirma con la cifra leída: {txt}")

    txt = _corre("sube el volumen de spotify")
    check(abs(spo.nivel - 0.40) < 0.01, f"subir no ha movido la sesión: {spo.nivel}")
    check("40" in txt, f"no dice el nivel al que ha quedado: {txt}")

    txt = _corre("baja el volumen de spotify")
    check(abs(spo.nivel - 0.30) < 0.01, f"bajar no ha movido la sesión: {spo.nivel}")

    txt = _corre("silencia spotify")
    check(spo.mute == 1, "«silencia spotify» no ha silenciado la sesión")
    check("silencio" in txt.lower(), f"no dice que la ha silenciado: {txt}")

    txt = _corre("quita el silencio de spotify")
    check(spo.mute == 0, "«quita el silencio de spotify» no la ha devuelto al sonido")
    check("suena" in txt.lower() or "sonar" in txt.lower(),
          f"no dice que vuelve a sonar: {txt}")

# Una aplicación que no suena se dice, no se finge. `_proceso_en_marcha` se
# parchea a propósito: sin eso la respuesta dependía de si el Spotify de la
# máquina estaba abierto en ese momento, y un test que cambia según lo que tengas
# abierto no prueba nada.
with _Parche(_porque_no_pycaw=lambda: "", _sesiones_audio=lambda: [("chrome.exe", _Vol())],
             _proceso_en_marcha=lambda n: False):
    txt = _corre("sube el volumen de spotify")
    check("✔" not in txt, f"dice que ha tocado el volumen de algo que no suena: {txt}")
    check("spotify" in txt.lower() and "sesión de audio" in txt.lower(),
          f"no explica que esa aplicación no tiene sesión de audio: {txt}")
    check("chrome" in txt.lower(), f"no enumera lo que SÍ está sonando: {txt}")

# sin pycaw no hay volumen por aplicación, y se admite
with _Parche(_porque_no_pycaw=lambda: "ModuleNotFoundError: No module named 'pycaw'", _sesiones_audio=lambda: []):
    txt = _corre("sube el volumen de spotify")
    check("✔" not in txt, f"finge haber actuado sin pycaw: {txt}")
    check("pycaw" in txt.lower(), f"no dice qué falta: {txt}")


# ============ 7) EL HANDLER DEL PC: pycaw primero, nircmd de respaldo ========
print("== 7) el volumen del PC: pycaw primero, nircmd de respaldo, honestidad si no hay ==")


class _Endpoint:
    """Dispositivo de salida de mentira, con la interfaz de IAudioEndpointVolume."""

    def __init__(self, nivel=0.5, mute=0):
        self.nivel, self.mute = nivel, mute

    def GetMasterVolumeLevelScalar(self):
        return self.nivel

    def SetMasterVolumeLevelScalar(self, v, _):
        self.nivel = v

    def GetMute(self):
        return self.mute

    def SetMute(self, m, _):
        self.mute = m


end = _Endpoint(nivel=0.50)
with _Parche(_mezclador_maestro=lambda: end):
    txt = _corre("pon el volumen del pc al 40")
    check(abs(end.nivel - 0.40) < 0.01, f"no ha escrito el 40% en el dispositivo: {end.nivel}")
    check("40" in txt and "✔" in txt, f"no confirma con la cifra leída: {txt}")

    _corre("sube el volumen del pc")
    check(abs(end.nivel - 0.50) < 0.01, f"subir no ha movido el maestro: {end.nivel}")
    _corre("baja el volumen del ordenador")
    check(abs(end.nivel - 0.40) < 0.01, f"bajar no ha movido el maestro: {end.nivel}")

    txt = _corre("silencia el pc")
    check(end.mute == 1, "«silencia el pc» no ha silenciado el dispositivo")
    txt = _corre("quita el silencio del pc")
    check(end.mute == 0, "«quita el silencio del pc» no ha devuelto el sonido")

    # subir el volumen de algo silenciado no se oye: se avisa en vez de callarlo
    end.mute = 1
    txt = _corre("pon el volumen del pc al 60")
    check("silenciado" in txt.lower(), f"sube el volumen de un PC mudo sin avisar: {txt}")
    end.mute = 0

# sin pycaw y sin nircmd no se toca nada, y se dice
with _Parche(_mezclador_maestro=lambda: None, _hay_nircmd=lambda: False):
    txt = _corre("sube el volumen del pc")
    check("✔" not in txt, f"finge haber subido el volumen sin nada con qué hacerlo: {txt}")
    check("pycaw" in txt.lower() and "nircmd" in txt.lower(),
          f"no dice qué le falta para poder actuar: {txt}")


# ============ 8) LO QUE PROMETE EL SKILL.md, LLEGA =========================
print("== 8) los SKILL.md de volumen no prometen nada que no enrute ==")
for carpeta, esperado in (("system_pc", "system_pc"), ("domotica", "domotica")):
    doc = (ROOT / "skills" / carpeta / "SKILL.md").read_text(encoding="utf-8")
    cuerpo = doc.split("## Fronteras")[0].split("## Qué necesita configurado")[0]
    for linea in cuerpo.splitlines():
        if not linea.strip().startswith("- «") or "volumen" not in linea.lower():
            continue
        for frase in re.findall(r"«([^»\n]{6,70})»", linea):
            if "…" in frase:
                continue
            r = sl.route(frase)
            check(r is not None and r[0].folder == esperado,
                  f"{carpeta}/SKILL.md promete «{frase}» y va a {_ruta(frase)}")


# ============ 9) CON pycaw DE VERDAD: se escribe y se restaura ==============
print("== 9) con pycaw instalado, contra el dispositivo real ==")
_ev = SPC._mezclador_maestro()
if _ev is None:
    print("  (sin pycaw en este intérprete: la prueba real la hace .venv/Scripts/python.exe)")
else:
    _vol0, _mute0 = _ev.GetMasterVolumeLevelScalar(), _ev.GetMute()
    try:
        _corre("pon el volumen del pc al 42")
        check(round(_ev.GetMasterVolumeLevelScalar() * 100) == 42,
              f"el dispositivo real no se ha quedado al 42%: "
              f"{round(_ev.GetMasterVolumeLevelScalar() * 100)}%")
        _corre("sube el volumen del pc")
        check(round(_ev.GetMasterVolumeLevelScalar() * 100) == 52,
              "subir no ha movido el dispositivo real 10 puntos")
        _corre("silencia el pc")
        check(_ev.GetMute() == 1, "el dispositivo real no se ha silenciado")
        _corre("quita el silencio del pc")
        check(_ev.GetMute() == 0, "el dispositivo real no ha vuelto del silencio")
    finally:
        _ev.SetMasterVolumeLevelScalar(_vol0, None)
        _ev.SetMute(_mute0, None)
    check(abs(_ev.GetMasterVolumeLevelScalar() - _vol0) < 0.001 and _ev.GetMute() == _mute0,
          "la prueba no ha dejado el volumen como estaba")


# ============ 10) QUITAR EL SILENCIO ES LO CONTRARIO DE PONERLO =============
print("== 10) quitar el silencio no es subir el volumen, ni silenciar otra vez ==")

# EL BUG, visto usando nexus: «quítale el silencio» no llegaba a NINGUNA skill.
# Caía al planificador, que contestaba «✔» sin haber tocado nada; y al insistir,
# «sigue en silencio» volvía a SILENCIAR. Además `_accion_volumen` clasificaba
# «quítale el mute» como el caso por defecto, que es SUBIR el volumen: pedir que
# vuelva a sonar te subía el volumen de un PC que seguía mudo.
for _frase in ("quítale el silencio", "quita el silencio", "quítale el mute",
               "desilencia", "vuelve a sonar"):
    check(_ruta(_frase) == "system_pc/volume_ask",
          f"«{_frase}» sin destino debe preguntar, no caer al planificador "
          f"(fue a {_ruta(_frase)})")
    check(SPC._accion_volumen(_frase)[0] == "unmute",
          f"«{_frase}» se interpreta como {SPC._accion_volumen(_frase)[0]}, no como quitar "
          "el silencio")

for _frase in ("quítale el silencio al pc", "quita el silencio del pc",
               "desilencia el pc", "quítale el mute al pc", "vuelve a sonar el pc"):
    check(_ruta(_frase) == "system_pc/volume",
          f"«{_frase}» nombra el PC y debe ir al volumen del PC (fue a {_ruta(_frase)})")
    check(SPC._accion_volumen(_frase)[0] == "unmute",
          f"«{_frase}» no se interpreta como quitar el silencio")

for _frase in ("quítale el silencio a spotify", "desilencia spotify",
               "quítale el mute a chrome"):
    check(_ruta(_frase) == "system_pc/volume_app",
          f"«{_frase}» nombra una aplicación (fue a {_ruta(_frase)})")

# Silenciar SIGUE siendo silenciar: el arreglo no puede invertirse.
for _frase, _esperada in (("silencia el pc", "mute"), ("silencia spotify", "mute"),
                          ("sube el volumen del pc", "step"),
                          ("pon el volumen del pc al 40", "set")):
    check(SPC._accion_volumen(_frase)[0] == _esperada,
          f"«{_frase}» debía ser {_esperada} y es {SPC._accion_volumen(_frase)[0]}")


# ============ 11) ABIERTA Y CALLADA NO ES LO MISMO QUE CERRADA ==============
print("== 11) una aplicación abierta pero sin sonar se distingue de una cerrada ==")

# Windows solo crea la sesión de audio cuando la aplicación EMPIEZA a sonar.
# Decir «no tiene sesión de audio» a secas suena a que no está abierta, y son
# dos situaciones con dos arreglos distintos: darle al play, o abrirla.
with _Parche(_porque_no_pycaw=lambda: "", _sesiones_audio=lambda: [],
             _proceso_en_marcha=lambda n: True):
    _txt = SPC._volumen_app("baja el volumen de spotify", "spotify")["reply"]
    check("abierto" in _txt.lower() and "reproduciendo" in _txt.lower(),
          f"no dice que está abierta pero callada: {_txt}")
    check("✔" not in _txt, f"finge haber actuado sobre algo que no suena: {_txt}")

with _Parche(_porque_no_pycaw=lambda: "", _sesiones_audio=lambda: [],
             _proceso_en_marcha=lambda n: False):
    _txt = SPC._volumen_app("baja el volumen de spotify", "spotify")["reply"]
    check("ni abierto" in _txt.lower() or "no lo veo" in _txt.lower(),
          f"no distingue una aplicación cerrada de una abierta y callada: {_txt}")


print(f"\n{'#' * 54}\ntest_volumen_destino: {_pass} OK, {len(_fail)} fallos")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
