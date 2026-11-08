# -*- coding: utf-8 -*-
"""EL ALMACÉN DE SECRETOS DEJA DE ESTAR EN CLARO — SEC-09 (roadmap P2-6, T13).

Qué se prueba, y por qué:

  A. Un `secrets.json` con valores en claro se CIFRA solo al cargarlo: en disco
     quedan `dpapi:v1:…` y NI UN BYTE del valor original. Es el hallazgo: una
     copia del perfil, un backup sin cifrar o un `git add -A` accidental leían
     las API keys enteras.
  B. Ida y vuelta exacta (`settings.secret()` devuelve lo mismo, carácter a
     carácter) y una segunda carga NO reescribe el archivo.
  C. Un almacén MEZCLADO (ya cifrado + en claro + basura que no entendemos)
     conserva todo; solo se cifra lo que estaba en claro.
  D. Un valor que no se puede descifrar (otra máquina, otra cuenta de Windows, o
     un blob tocado) NO se convierte en un vacío silencioso: avisa en castellano,
     el resto del almacén sigue funcionando y el blob NO se destruye.
  E. Si DPAPI falla al cifrar, el archivo se queda EXACTAMENTE como estaba (byte
     a byte) y nexus sigue funcionando con los valores en claro.
  F. Se verifica ANTES de reemplazar: si la comprobación de ida y vuelta falla
     para un solo valor, no se escribe nada (nunca medio migrado).
  G. Fuera de Windows (los contenedores de CI son Linux) se comporta como hoy:
     JSON plano, funciona y no se cae.
  H. `as_dict()` y `GET /api/config` siguen sin sacar ni el valor ni la marca: el
     control C-09 no se toca. Se comprueba por la interfaz HTTP de verdad, en
     proceso (httpx.ASGITransport, sin lifespan ni puertos).
  I. El escáner de antes de subir NO confunde un blob `dpapi:v1:` con una clave
     (no aborta una subida legítima) y SIGUE detectando una `sk-…` en crudo —
     tampoco si va PEGADA a la etiqueta (`"dpapi:v1:sk-…"`) ni disfrazada detrás
     de dos letras (`"dpapi:v1:AA" + "sk-…"`), y no neutraliza un valor con `_`
     o `-`, que no es base64 estándar (advisories del verificador sobre 562c777).
  J. Un almacén que NO se puede escribir (solo lectura, o el destino bloqueado
     por otra copia de nexus) se queda byte a byte igual, avisa en castellano,
     conserva las claves en memoria y no deja ni un `.tmp`. Cómo se impide
     escribir depende de la plataforma —en Windows vale el bit del ARCHIVO, en
     POSIX manda el de la CARPETA porque el guardado publica un `.tmp` con
     `os.replace`— y sin DPAPI la carga no escribe, así que ahí el intento real
     que se prueba es `set_secret`. Suponer lo contrario ponía la suite roja
     SOLO en el runner de Ubuntu (CI run 42525331409).
  K. Un valor que NO es texto (número, booleano, nulo, objeto) sobrevive intacto
     a la migración y a cualquier escritura, se nombra en los avisos y no rompe
     `secret()`, que cae a la variable de entorno.
  L. Poner "" en una clave que aquí no se puede abrir la borra del archivo —solo
     a ella— y deja intactos los vecinos.
  M. `GET /api/status` publica los NOMBRES de esas claves ilegibles (y nunca sus
     valores ni la marca `dpapi:`): un fallo de descifrado por DPAPI no puede
     quedarse sólo en la consola del que importó el módulo.

NUNCA se toca el material del operador: `NEXUS_CONFIG_DIR` / `NEXUS_DATA_DIR`
apuntan a carpetas de usar y tirar ANTES de importar el backend, cada caso usa su
propio archivo de secretos y todos los valores de esta suite son inventados
(«sk-TEST-VALUE-…»). No se abre, copia ni imprime ningún archivo real.

En Windows las pruebas llaman a la DPAPI DE VERDAD: es una llamada local, sin
red y sin efectos fuera del proceso, y es justo la evidencia que se quiere. En
otra plataforma `cripto.disponible()` es False y las secciones A-F se sustituyen
por el camino de repliegue (G): la suite lo DICE en su salida en vez de fingir
que probó el cifrado.

Ejecutar:  .venv\\Scripts\\python.exe tests\\unit\\core\\test_secretos_cifrado.py
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

# ANTES de importar backend: ni config/settings.json ni config/secrets.json del
# operador se leen ni se escriben desde aquí (regla H2 de la tarea T13).
_CFG = tempfile.mkdtemp(prefix="nexus_secretos_cfg_")
_DATA = tempfile.mkdtemp(prefix="nexus_secretos_data_")
os.environ["NEXUS_CONFIG_DIR"] = _CFG
os.environ["NEXUS_DATA_DIR"] = _DATA

from backend.core.comun import config, cripto                        # noqa: E402

_fail: list[str] = []
_pass = 0
_saltados: list[str] = []

# Valores INVENTADOS. Ninguno es una credencial: son cadenas que sólo existen en
# este archivo, para poder afirmar «esta cadena no aparece en el disco».
V1 = "sk-TEST-VALUE-1234"
V2 = "ghp-TEST-VALUE-5678-wxyz"
V3 = "postgresql://nexus:TEST-VALUE-9999@db.local:5433/nexus_core"


def check(cond, msg: str) -> bool:
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  ✖", msg)
    return bool(cond)


class _Doble:
    """Cambia un atributo de un módulo y lo devuelve pase lo que pase."""

    def __init__(self, obj, nombre, valor):
        self.obj, self.nombre, self.valor, self.previo = obj, nombre, valor, None

    def __enter__(self):
        self.previo = getattr(self.obj, self.nombre)
        setattr(self.obj, self.nombre, self.valor)
        return self.valor

    def __exit__(self, *_exc):
        setattr(self.obj, self.nombre, self.previo)
        return False


class Almacen:
    """Un `secrets.json` de usar y tirar, y un `Settings()` nuevo contra él.

    Se apaña `config.SECRETS_FILE` (la ruta se resuelve al importar el módulo,
    con `NEXUS_CONFIG_DIR`) para que cada caso tenga SU archivo: así una prueba
    no arrastra el estado de la anterior."""

    def __init__(self, crudos: dict | None = None):
        self.carpeta = Path(tempfile.mkdtemp(prefix="nexus_secretos_alm_"))
        self.ruta = self.carpeta / "secrets.json"
        if crudos is not None:
            self.ruta.write_text(json.dumps(crudos, ensure_ascii=False), encoding="utf-8")

    # -- interfaz
    def cargar(self):
        """(Settings nuevo, avisos que ha escrito por consola)."""
        getattr(config, "AVISOS_SECRETOS", []).clear()
        buf = io.StringIO()
        with _Doble(config, "SECRETS_FILE", self.ruta):
            with redirect_stdout(buf):
                ajustes = config.Settings()
        return ajustes, buf.getvalue()

    def crudo(self) -> dict:
        return json.loads(self.ruta.read_text(encoding="utf-8"))

    def bytes(self) -> bytes:
        return self.ruta.read_bytes() if self.ruta.exists() else b"<no existe>"

    def borrar(self) -> None:
        shutil.rmtree(self.carpeta, ignore_errors=True)


def _ilegibles(ajustes) -> list:
    """Los nombres de secreto que ese `Settings` no ha podido abrir."""
    f = getattr(ajustes, "secretos_ilegibles", None)
    return sorted(f()) if callable(f) else []


def _sin_valor(texto: str, valor: str) -> bool:
    """El valor no aparece NI ENTERO ni troceado en un fragmento reconocible.
    Se comprueban los trozos de 8 caracteres: un blob base64 no puede contener
    una cadena de texto en claro, y esto lo demuestra sin depender del formato."""
    if valor in texto:
        return False
    return not any(valor[i:i + 8] in texto for i in range(0, max(len(valor) - 8, 0) + 1))


HAY_DPAPI = cripto.disponible()

# ══════════════════════════════════════════════════════════════════════════
print("== 0) la capa de cifrado, llamada directamente ==")
# ══════════════════════════════════════════════════════════════════════════
check(hasattr(cripto, "cifrar") and hasattr(cripto, "descifrar"),
      "backend/core/comun/cripto.py no expone cifrar()/descifrar()")
check(cripto.PREFIJO == "dpapi:v1:",
      f"el formato etiquetado no es «dpapi:v1:» sino {getattr(cripto, 'PREFIJO', None)!r}")
check(cripto.es_cifrado("dpapi:v1:AAAA") and not cripto.es_cifrado("sk-abc"),
      "es_cifrado() no distingue un valor cifrado de uno en claro")
check(not cripto.es_cifrado("dpapi:v2:AAAA"),
      "es_cifrado() da por bueno un formato de una versión que no conoce")
check(cripto.es_de_dpapi("dpapi:v2:AAAA") and not cripto.es_de_dpapi("sk-abc"),
      "es_de_dpapi() no reconoce la marca de cualquier versión")

if HAY_DPAPI:
    marca = cripto.cifrar(V1)
    check(marca.startswith("dpapi:v1:"), "cifrar() no devuelve el valor etiquetado")
    check(_sin_valor(marca, V1), "la marca cifrada contiene el valor en claro")
    check(cripto.descifrar(marca) == V1, "descifrar(cifrar(x)) no devuelve x")
    check(cripto.cifrar(V1) != marca,
          "dos cifrados del mismo valor dan el mismo blob: DPAPI debería añadir sal")
    check(cripto.descifrar(cripto.cifrar("contraseña con ñ y €")) == "contraseña con ñ y €",
          "no sobreviven los acentos ni el euro en la ida y vuelta")
    # base64 ESTÁNDAR: sin «-» no puede colarse un «sk-…» dentro del blob.
    check("-" not in marca[len(cripto.PREFIJO):],
          "el blob usa un alfabeto que puede contener «-» y confundir al escáner")
    roto = cripto.PREFIJO + base64.b64encode(b"basura" * 8).decode("ascii")
    try:
        cripto.descifrar(roto)
        check(False, "descifrar() se ha tragado un blob que no es suyo (devolvería basura)")
    except cripto.CriptoError:
        check(True, "")
    try:
        cripto.descifrar("dpapi:v2:AAAA")
        check(False, "descifrar() ha aceptado un formato que no conoce")
    except cripto.CriptoError:
        check(True, "")
else:
    _saltados.append("0) cifrar/descifrar reales (DPAPI no disponible en esta plataforma)")
    check(cripto.disponible() is False, "disponible() no dice la verdad fuera de Windows")

# ══════════════════════════════════════════════════════════════════════════
print("== 1) el almacén en claro se cifra solo al cargarlo (A) ==")
# ══════════════════════════════════════════════════════════════════════════
if not HAY_DPAPI:
    _saltados.append("1-6) migración y cifrado del almacén (necesita DPAPI de Windows)")
    print("  (saltado: en esta plataforma cripto.disponible() es False; ver sección 6)")
else:
    alm = Almacen({"openai_api_key": V1, "telegram_bot_token": V2, "db_url": V3})
    antes = alm.bytes()
    ajustes, avisos = alm.cargar()
    crudo = alm.crudo()
    despues = alm.bytes()

    check(set(crudo) == {"openai_api_key", "telegram_bot_token", "db_url"},
          f"la migración se ha comido o renombrado claves: {sorted(crudo)}")
    check(all(cripto.es_cifrado(v) for v in crudo.values()),
          f"quedan valores sin cifrar en el archivo: {[k for k, v in crudo.items() if not cripto.es_cifrado(v)]}")
    texto = despues.decode("utf-8")
    for nombre, valor in (("openai_api_key", V1), ("telegram_bot_token", V2), ("db_url", V3)):
        check(_sin_valor(texto, valor),
              f"el valor de «{nombre}» sigue legible en el archivo en disco")
    check(despues != antes, "el archivo no se ha reescrito: sigue en claro")
    check(ajustes.secret("openai_api_key") == V1, "tras migrar, secret() no devuelve el valor")
    check(ajustes.secret("telegram_bot_token") == V2, "tras migrar, secret() perdió el segundo valor")
    check(ajustes.secret("db_url") == V3, "tras migrar, secret() perdió la cadena de conexión")
    check(not (alm.carpeta / "secrets.json.bak").exists(),
          "se ha escrito un secrets.json.bak: sería una copia EN CLARO del almacén")
    check(avisos == "", f"la migración normal no debería avisar de nada: {avisos.strip()[:120]}")

    # ══════════════════════════════════════════════════════════════════════
    print("== 2) ida y vuelta exacta y segunda carga estable (B) ==")
    # ══════════════════════════════════════════════════════════════════════
    bytes_antes = alm.bytes()
    otra, avisos2 = alm.cargar()
    check(otra.secret("openai_api_key") == V1, "la segunda carga no devuelve el mismo valor")
    check(alm.bytes() == bytes_antes,
          "la segunda carga ha REESCRITO el archivo: algo lo re-cifra en cada arranque")
    check(avisos2 == "", f"la segunda carga avisa de algo que no debería: {avisos2.strip()[:120]}")
    check(otra.secret("no_existe_esta_clave") == "", "una clave inexistente no devuelve vacío")
    alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 3) almacén mezclado: cifrado + en claro + basura (C) ==")
# ══════════════════════════════════════════════════════════════════════════
if not HAY_DPAPI:
    _saltados.append("3) almacén mezclado (necesita DPAPI)")
else:
    ya_cifrado = cripto.cifrar(V1)
    alm = Almacen({
        "openai_api_key": ya_cifrado,                 # ya estaba cifrado
        "anthropic_api_key": V2,                      # en claro
        "futuro": "dpapi:v2:AAAA",                    # formato que no conocemos
        "raro": {"a": 1},                             # ni siquiera es texto
    })
    ajustes, avisos = alm.cargar()
    crudo = alm.crudo()

    check(ajustes.secret("openai_api_key") == V1, "el valor ya cifrado no se abrió")
    check(ajustes.secret("anthropic_api_key") == V2, "el valor en claro se perdió al migrar")
    check(crudo["openai_api_key"] == ya_cifrado,
          "se ha RE-CIFRADO un valor que ya estaba cifrado (el archivo cambia en cada arranque)")
    check(cripto.es_cifrado(crudo["anthropic_api_key"]),
          "el valor que estaba en claro no se ha cifrado")
    check(crudo["futuro"] == "dpapi:v2:AAAA",
          "un formato que no conocemos se ha reescrito: no se toca lo que no se entiende")
    check(crudo["raro"] == {"a": 1}, "un valor que no es texto se ha perdido")
    check("futuro" in _ilegibles(ajustes),
          "el valor de formato desconocido no se nombra en secretos_ilegibles()")
    check(ajustes.secret("futuro") == "", "un secreto ilegible no devuelve vacío")
    check("AVISO" in avisos and "futuro" in avisos,
          f"no se ha avisado del secreto ilegible «futuro»: {avisos.strip()[:150]}")
    alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 4) un blob que no se puede descifrar: aviso, no vacío silencioso (D) ==")
# ══════════════════════════════════════════════════════════════════════════
if not HAY_DPAPI:
    _saltados.append("4) blob ajeno (necesita DPAPI)")
else:
    ajeno = cripto.PREFIJO + base64.b64encode(b"basura de otra maquina" * 4).decode("ascii")
    alm = Almacen({"openai_api_key": ajeno, "telegram_bot_token": V2})
    ajustes, avisos = alm.cargar()
    crudo = alm.crudo()

    check(ajustes.secret("openai_api_key") == "",
          "un blob ajeno devuelve algo: no puede devolver nada, pero tiene que avisar")
    check("openai_api_key" in _ilegibles(ajustes),
          "el secreto ilegible no se puede consultar: el fallo sería silencioso")
    check("AVISO" in avisos and "openai_api_key" in avisos,
          f"no se ha avisado en castellano del secreto ilegible: {avisos.strip()[:150]}")
    check(V2 not in avisos, "el aviso imprime OTRO secreto del almacén")
    check(ajustes.secret("telegram_bot_token") == V2,
          "un secreto roto ha tumbado el resto del almacén")
    check(crudo["openai_api_key"] == ajeno,
          "el blob que no se pudo abrir se ha reescrito o borrado (se perdería la clave)")
    check(cripto.es_cifrado(crudo["telegram_bot_token"]),
          "el vecino en claro no se ha cifrado al migrar")
    alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 4b) escribir NO destruye lo que no se puede abrir (D, contrato de antes) ==")
# ══════════════════════════════════════════════════════════════════════════
if not HAY_DPAPI:
    _saltados.append("4b) escritura con un blob ajeno en el almacén (necesita DPAPI)")
else:
    ajeno = cripto.PREFIJO + base64.b64encode(b"basura de otra maquina" * 4).decode("ascii")
    alm = Almacen({"openai_api_key": ajeno})
    ajustes, _avisos = alm.cargar()
    with _Doble(config, "SECRETS_FILE", alm.ruta):
        ajustes.set_secret("telegram_bot_token", V2)
        crudo = alm.crudo()
        check(crudo.get("openai_api_key") == ajeno,
              "guardar otra clave se ha llevado por delante el blob que no se puede abrir")
        check(cripto.es_cifrado(crudo.get("telegram_bot_token", "")),
              "la clave nueva se ha guardado sin cifrar")
        check(ajustes.secret("telegram_bot_token") == V2,
              "la clave nueva no se lee después de guardarla")
        # Un nombre que NO es un secreto no escribe nada (contrato de siempre).
        antes = alm.bytes()
        ajustes.set_secret("llm_provider", "openai")
        check(alm.bytes() == antes,
              "set_secret() ha reescrito el almacén por un nombre que no es un secreto")
    alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 5) si DPAPI falla al cifrar, el archivo se queda igual (E) ==")
# ══════════════════════════════════════════════════════════════════════════
if not HAY_DPAPI:
    _saltados.append("5) fallo de DPAPI (necesita DPAPI)")
else:
    def _rompe(_texto):
        raise cripto.CriptoError("DPAPI no pudo cifrar (error 5, simulado)")

    alm = Almacen({"openai_api_key": V1, "anthropic_api_key": V2})
    antes = alm.bytes()
    with _Doble(cripto, "cifrar", _rompe):
        ajustes, avisos = alm.cargar()
    check(alm.bytes() == antes,
          "con DPAPI roto el archivo NO se ha quedado igual: se ha reescrito a medias")
    check(ajustes.secret("openai_api_key") == V1 and ajustes.secret("anthropic_api_key") == V2,
          "con DPAPI roto nexus deja de tener las claves (debería seguir en claro y funcionar)")
    check("AVISO" in avisos, "con DPAPI roto no se avisa de nada")
    check(not (alm.carpeta / "secrets.json.bak").exists(),
          "con DPAPI roto se ha escrito un .bak en claro")
    alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 6) se verifica antes de reemplazar: si falla, no se escribe nada (F) ==")
# ══════════════════════════════════════════════════════════════════════════
if not HAY_DPAPI:
    _saltados.append("6) verificación antes de reemplazar (necesita DPAPI)")
else:
    def _miente(_marca):
        return "OTRA-COSA"

    alm = Almacen({"openai_api_key": V1, "anthropic_api_key": V2})
    antes = alm.bytes()
    with _Doble(cripto, "descifrar", _miente):
        ajustes, avisos = alm.cargar()
    check(alm.bytes() == antes,
          "la comprobación de ida y vuelta falló y AUN ASÍ se reescribió el almacén")
    check(alm.crudo() == {"openai_api_key": V1, "anthropic_api_key": V2},
          "medio migrado: el archivo quedó con parte cifrada y parte en claro")
    check("AVISO" in avisos and ("vuelta" in avisos or "comprob" in avisos.lower()),
          f"no se ha avisado de que la comprobación falló: {avisos.strip()[:150]}")
    check(ajustes.secret("openai_api_key") == V1,
          "al no poder migrar se han perdido los valores en memoria")
    alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 7) fuera de Windows: como hoy, JSON plano y sin romperse (G) ==")
# ══════════════════════════════════════════════════════════════════════════
alm = Almacen({"openai_api_key": V1, "telegram_bot_token": V2})
antes = alm.bytes()
_plataforma = sys.platform
try:
    sys.platform = "linux"                    # los contenedores de CI son Linux
    check(cripto.disponible() is False, "disponible() dice que sí en Linux")
    ajustes, avisos = alm.cargar()
    check(alm.bytes() == antes,
          "en Linux se ha reescrito el almacén (tiene que quedarse como está)")
    check(ajustes.secret("openai_api_key") == V1,
          "en Linux nexus se queda sin las claves: el repliegue no funciona")
    check(avisos == "", f"en Linux no hay nada de lo que avisar: {avisos.strip()[:120]}")
finally:
    sys.platform = _plataforma
check(cripto.disponible() == HAY_DPAPI, "disponible() no ha vuelto a su valor tras el doble")
alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 8) as_dict() y GET /api/config no sacan ni el valor ni la marca (H) ==")
# ══════════════════════════════════════════════════════════════════════════
try:
    import asyncio

    import httpx

    import backend.app as servidor
except Exception as exc:                                       # noqa: BLE001
    check(False, f"no he podido importar la aplicación para la prueba HTTP: {exc}")
    servidor = None

if servidor is not None:
    alm = Almacen()
    with _Doble(config, "SECRETS_FILE", alm.ruta):
        config.settings.set_secret("openai_api_key", V1)
        config.settings.set_secret("telegram_bot_token", V2)

        en_disco = alm.bytes().decode("utf-8")
        if HAY_DPAPI:
            check(_sin_valor(en_disco, V1),
                  "POST de una clave y sigue en claro en el disco")
        else:
            _saltados.append("8) el archivo cifrado tras escribir por la API (necesita DPAPI)")

        d = config.settings.as_dict()
        check("openai_api_key" not in d, "as_dict() devuelve la clave en claro (C-09 roto)")
        check(d.get("has_openai_api_key") is True, "as_dict() pierde el indicador has_*")
        check(V1 not in json.dumps(d, ensure_ascii=False), "as_dict() lleva el valor dentro")
        check("dpapi:" not in json.dumps(d, ensure_ascii=False),
              "as_dict() saca la marca cifrada: no aporta nada y confunde al HUD")

        async def _pide():
            transporte = httpx.ASGITransport(app=servidor.app, client=("127.0.0.1", 4321))
            async with httpx.AsyncClient(transport=transporte,
                                         base_url="http://127.0.0.1:8177") as c:
                return await c.get("/api/config", headers={"host": "127.0.0.1:8177"})

        try:
            r = asyncio.run(_pide())
        except Exception as exc:                               # noqa: BLE001
            check(False, f"GET /api/config ha reventado: {exc}")
        else:
            check(r.status_code == 200, f"GET /api/config devolvió {r.status_code}")
            cuerpo = r.text
            check(V1 not in cuerpo and V2 not in cuerpo,
                  "GET /api/config devuelve una clave en claro")
            check("dpapi:" not in cuerpo, "GET /api/config devuelve la marca cifrada")
            check('"has_openai_api_key":true' in cuerpo.replace(" ", ""),
                  f"GET /api/config no informa de has_openai_api_key: {cuerpo[:200]}")

        # se deja el proceso como estaba: el secreto de prueba no sobrevive
        config.settings.set_secret("openai_api_key", "")
        config.settings.set_secret("telegram_bot_token", "")
    alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 9) el escáner de antes de subir no confunde un blob con una clave (I) ==")
# ══════════════════════════════════════════════════════════════════════════
_ruta_escaner = ROOT / "scripts" / "revisar_antes_de_subir.py"
try:
    _spec = importlib.util.spec_from_file_location("revisar_antes_de_subir", _ruta_escaner)
    escaner = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(escaner)
except Exception as exc:                                       # noqa: BLE001
    check(False, f"no he podido cargar el escáner {_ruta_escaner}: {exc}")
    escaner = None

if escaner is not None and not check(
        hasattr(escaner, "_sin_blobs_cifrados"),
        "el escáner no neutraliza los blobs cifrados antes de mirar la línea"):
    escaner = None

if escaner is not None:

    # Un blob que, por mala suerte, lleva dentro una subcadena con pinta de clave
    # de Google. Un base64 real puede contenerla (1 entre 16 millones por
    # posición, y un secrets.json tiene cientos de miles de posiciones).
    linea = '"gemini_api_key": "' + cripto.PREFIJO + "AIza" + "A" * 40 + '",'
    pelado = escaner._sin_blobs_cifrados(linea)
    check(cripto.PREFIJO not in pelado, "el escáner no quita la marca del blob")
    check(not any(rx.search(pelado) for rx, _d in escaner._PELIGRO_RX),
          "el escáner ABORTA la subida por una subcadena dentro de un blob cifrado")
    check(escaner._REVISA_RX.search(pelado) is None,
          "el escáner lista el blob cifrado como «asignación con pinta de credencial»")

    crudo = '"openai_api_key": "sk-' + "A" * 32 + '",'
    check(any(rx.search(escaner._sin_blobs_cifrados(crudo)) for rx, _d in escaner._PELIGRO_RX),
          "el escáner YA NO detecta una clave de OpenAI en crudo")
    crudo_google = '"gemini_api_key": "AIza' + "A" * 40 + '",'
    check(any(rx.search(escaner._sin_blobs_cifrados(crudo_google)) for rx, _d in escaner._PELIGRO_RX),
          "el escáner ya no detecta una clave de Google en crudo")

    # 9c) ADVISORY DEL VERIFICADOR SOBRE 562c777: la neutralización sólo puede
    # comerse la FORMA que produce de verdad `cripto.cifrar()` —base64 ESTÁNDAR
    # (sin `-` ni `_`), un tramo largo, pegado a la etiqueta y cerrado ahí—. Si se
    # come cualquier cosa que empiece por «dpapi:v1:», un secreto en crudo se
    # esconde detrás de la etiqueta y el escáner lo deja pasar.
    _pegada = '"openai_api_key": "dpapi:v1:sk-proj-' + "A" * 32 + '",'
    _pelada = escaner._sin_blobs_cifrados(_pegada)
    check(_pelada == _pegada,
          "el escáner neutraliza una clave PEGADA a la etiqueta: se come el «sk» y la clave pasa")
    check(any(rx.search(_pelada) for rx, _d in escaner._PELIGRO_RX),
          "una clave pegada a la etiqueta del cifrado se le escapa al escáner")

    _disfrazada = '"openai_api_key": "dpapi:v1:AA" + "sk-proj-' + "A" * 32 + '",'
    check(any(rx.search(escaner._sin_blobs_cifrados(_disfrazada))
              for rx, _d in escaner._PELIGRO_RX),
          "un secreto disfrazado con «dpapi:v1:AA» delante se le escapa al escáner")

    for _sufijo in ("_", "-"):
        _parecido = '"a": "dpapi:v1:' + "A" * 40 + _sufijo + '",'
        check(escaner._sin_blobs_cifrados(_parecido) == _parecido,
              f"el escáner neutraliza un valor con «{_sufijo}» que NO es base64 estándar: "
              "se come texto sospechoso")

    # La forma REAL se sigue dejando pasar, con y sin DPAPI disponible aquí.
    _largo = '"gemini_api_key": "' + cripto.PREFIJO + "AIza" + "A" * 300 + '",'
    _pelada = escaner._sin_blobs_cifrados(_largo)
    check(cripto.PREFIJO not in _pelada,
          "un blob largo (la forma real) ya no se neutraliza: saltaría una alarma falsa")
    check(not any(rx.search(_pelada) for rx, _d in escaner._PELIGRO_RX),
          "un blob largo con «AIza» dentro hace abortar la subida")
    if HAY_DPAPI:
        _real = '"openai_api_key": "' + cripto.cifrar(V1) + '",'
        _pelada = escaner._sin_blobs_cifrados(_real)
        check(cripto.PREFIJO not in _pelada and
              not any(rx.search(_pelada) for rx, _d in escaner._PELIGRO_RX),
              "un blob REAL de DPAPI (320 caracteres) hace abortar la subida")
    else:
        _saltados.append("9c) el blob real del escáner (necesita DPAPI)")

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            codigo = escaner.autotest()
    except Exception as exc:                                   # noqa: BLE001
        check(False, f"la autocomprobación del escáner ha reventado: {exc}")
        codigo = 1
    salida = buf.getvalue()
    check(codigo == 0, f"--autotest del escáner falla:\n{salida[-800:]}")
    check("SE LE ESCAPA" not in salida and "FALSA ALARMA" not in salida,
          f"el escáner se delata en su autocomprobación:\n{salida[-800:]}")

    # El informe de lo que sigue en claro: nombres y tamaños, NUNCA valores.
    if hasattr(cripto, "estado_del_almacen"):
        info = cripto.estado_del_almacen(alm_dir := Path(tempfile.mkdtemp(prefix="nexus_info_")))
        try:
            check(info["carpeta"] == str(alm_dir), "el informe no dice de qué carpeta habla")
            nombres = {f["archivo"] for f in info["archivos"]}
            check({"secrets.json", "secrets.json.bak", "google_token.json",
                   "spotify_token.json"} <= nombres,
                  f"el informe no nombra los archivos de credenciales: {sorted(nombres)}")
            check(all(f["existe"] is False for f in info["archivos"]),
                  "el informe dice que existen archivos en una carpeta vacía")
            check(info["secretos"]["legible"] is False and info["secretos"]["total"] == 0,
                  "el informe se inventa secretos donde no hay archivo")
            check(info.get("otros") == [],
                  "el informe inventa archivos raros en una carpeta vacía")
            (alm_dir / "google_credentials.OLD.json").write_text("{}", encoding="utf-8")
            info = cripto.estado_del_almacen(alm_dir)
            nombres_otros = {f["archivo"] for f in info.get("otros") or []}
            check("google_credentials.OLD.json" in nombres_otros,
                  f"el informe no ve una copia vieja de credenciales: {sorted(nombres_otros)}")
            check("settings.json" not in str(info.get("otros")),
                  "el informe mete settings.json entre las credenciales")
            (alm_dir / "google_credentials.OLD.json").unlink()
            (alm_dir / "secrets.json").write_text(
                json.dumps({"a": cripto.cifrar(V1) if HAY_DPAPI else V1, "b": V2}),
                encoding="utf-8")
            (alm_dir / "secrets.json.bak").write_text("{}", encoding="utf-8")
            info = cripto.estado_del_almacen(alm_dir)
            check(info["secretos"]["legible"] is True, "el informe no lee un secrets.json válido")
            check(info["secretos"]["total"] == 2, "el informe no cuenta los valores")
            check(info["secretos"]["cifrados"] == (1 if HAY_DPAPI else 0),
                  f"el informe no distingue un valor cifrado: {info['secretos']}")
            check(not any(V1 in str(f) or V2 in str(f) for f in info["archivos"]),
                  "el informe de estado lleva valores dentro")
        finally:
            shutil.rmtree(alm_dir, ignore_errors=True)
    else:
        check(False, "cripto.estado_del_almacen() no existe: no hay informe del hueco que queda")

# ══════════════════════════════════════════════════════════════════════════
print("== 9b) --proteger-backups informa de lo que sigue en claro y no borra nada (5) ==")
# ══════════════════════════════════════════════════════════════════════════
if escaner is None or not hasattr(escaner, "proteger_backups"):
    check(False, "el escáner no tiene el punto de mantenimiento proteger_backups()")
else:
    # Carpeta de usar y tirar: este comando NUNCA se lanza contra config/ real.
    cfg = Path(tempfile.mkdtemp(prefix="nexus_proteger_"))
    try:
        (cfg / "secrets.json").write_text(
            json.dumps({"a": V1}), encoding="utf-8")
        (cfg / "secrets.json.bak").write_text(
            json.dumps({"a": "viejo-pero-en-claro"}), encoding="utf-8")
        (cfg / "google_token.json").write_text("{}", encoding="utf-8")
        (cfg / "google_credentials.OLD.json").write_text("{}", encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            codigo = escaner.proteger_backups(cfg)
        salida = buf.getvalue()
        check(codigo == 0, f"proteger_backups() devolvió {codigo}: es un informe, no un veto")
        check("secrets.json.bak" in salida, "el informe no nombra la copia en claro")
        check("google_token.json" in salida, "el informe no nombra el token de Google")
        check("google_credentials.OLD.json" in salida,
              "el informe no nombra la copia vieja de credenciales de Google")
        check("EN CLARO" in salida, "el informe no dice qué está en claro")
        check("del config" in salida or "Bórrala" in salida,
              "el informe no dice CÓMO quitar la copia en claro")
        check(V1 not in salida and "viejo-pero-en-claro" not in salida,
              "el informe imprime el contenido de un secreto")
        check((cfg / "secrets.json.bak").exists(),
              "proteger_backups() ha borrado un archivo del operador: no es su trabajo")
        check((cfg / "google_token.json").exists(),
              "proteger_backups() ha borrado el token del operador")
    finally:
        shutil.rmtree(cfg, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════════
print("== 11) almacén que NO se puede escribir: intacto, con aviso y sin .tmp ==")
# ══════════════════════════════════════════════════════════════════════════
# El caso real que ve el operador: el almacén está bloqueado (otra copia de nexus
# abierta, el antivirus, una copia de seguridad en curso) o su carpeta es de solo
# lectura. La escritura tiene que fallar HACIA LO SEGURO: el archivo queda byte a
# byte como estaba, se avisa en castellano, las claves de esta sesión siguen
# sirviendo y no queda basura `.tmp`.
#
# CÓMO se impide escribir depende de la plataforma, y suponerlo fue el fallo que
# destapó CI (run 42525331409, job «Suites por perfil seguro»). La prueba ponía
# el ARCHIVO en `chmod 444` y esperaba el aviso; en Windows eso es exactamente el
# atributo de solo lectura y la migración choca con él al publicar, pero:
#   * en POSIX `chmod 444` en el archivo NO impide nada: el guardado escribe un
#     `.tmp` en la CARPETA y lo publica con `os.replace` (comun/atomicos.py), y
#     reemplazar un archivo sin bit de escritura dentro de una carpeta escribible
#     funciona. Lo que manda es el bit de la CARPETA (`0o555`), y ahí el que
#     falla es la creación del `.tmp` con PermissionError;
#   * y sin DPAPI (Linux) la CARGA no escribe nada —no hay valor que cifrar, es
#     el repliegue de la sección 6, no un fallo—, así que no había ningún intento
#     de guardado que pudiera avisar de nada. El intento REAL y portable que
#     prueba esta sección es `set_secret`, que es el mismo camino de escritura
#     que usa el operador desde ⚙ → Claves API.
# Lo que NO se supone es que el sistema de archivos obedezca: se prueba con
# `_no_se_puede_guardar` (como root, o en un FS que ignore los modos, no protege
# nada) y si no protege se dice en la salida en vez de fingir que se probó.


def _no_se_puede_guardar(ruta: Path) -> bool:
    """¿Está el almacén protegido DE VERDAD contra un guardado aquí?

    Se prueba lo mismo que hace el producto al guardar: crear un `.tmp` en la
    carpeta y publicarlo con `os.replace` sobre el archivo. Basta con que UNA de
    las dos cosas falle, y cuál falla cambia con la plataforma (ver arriba)."""
    sonda = ruta.with_name(f"{ruta.name}.{os.getpid():x}.sonda.tmp")
    try:
        sonda.write_text("", encoding="utf-8")
    except OSError:
        return True                   # sin `.tmp` en la carpeta no hay guardado posible
    try:
        sonda.unlink()
    except OSError:
        pass
    try:
        with open(ruta, "a", encoding="utf-8"):
            pass
    except OSError:
        return True                   # destino de solo lectura: os.replace fallará
    return False


def _guardar_y_avisar(ajustes, ruta: Path, clave: str, valor: str) -> str:
    """Guarda de verdad por el camino público (set_secret) y devuelve lo avisado."""
    getattr(config, "AVISOS_SECRETOS", []).clear()
    buf = io.StringIO()
    with _Doble(config, "SECRETS_FILE", ruta), redirect_stdout(buf):
        ajustes.set_secret(clave, valor)
    return buf.getvalue()


alm = Almacen({"openai_api_key": V1, "telegram_bot_token": V2})
antes = alm.bytes()
modo_archivo = alm.ruta.stat().st_mode
modo_carpeta = alm.carpeta.stat().st_mode
try:
    # Las dos cosas a la vez: el archivo (lo que manda en Windows) y la carpeta
    # (lo que manda en POSIX). Ninguna molesta a la otra plataforma.
    os.chmod(alm.ruta, 0o444)
    os.chmod(alm.carpeta, 0o555)
    if _no_se_puede_guardar(alm.ruta):
        if HAY_DPAPI:
            # Con DPAPI la migración se intenta al CARGAR y el sistema de
            # archivos la para: es el caso de Windows, tal cual lo ve el operador.
            ajustes, avisos = alm.cargar()
            etiqueta = "con el almacén en solo lectura de verdad"
        else:
            # Sin DPAPI la carga no escribe (no hay nada que cifrar): el intento
            # real es set_secret, con la carpeta cerrada.
            ajustes, _ = alm.cargar()
            avisos = _guardar_y_avisar(ajustes, alm.ruta, "openai_api_key", V1)
            etiqueta = "con la carpeta en solo lectura de verdad"
    else:
        # Etiquetado: como root (o en un FS que ignora los modos) no se puede
        # imponer solo lectura, así que se dobla el MISMO fallo que da el sistema
        # al publicar (WinError 5 / PermissionError) y se prueba el manejo del error.
        _saltados.append("11) solo lectura impuesto por el sistema de archivos")
        _real_replace = os.replace

        def _bloqueado(_src, _dst):
            raise PermissionError(13, "Acceso denegado (simulado: archivo en uso)")

        os.replace = _bloqueado
        try:
            ajustes, _ = alm.cargar()
            avisos = _guardar_y_avisar(ajustes, alm.ruta, "openai_api_key", V1)
        finally:
            os.replace = _real_replace
        etiqueta = "con el reemplazo bloqueado (equivalente etiquetado)"

    check(alm.bytes() == antes,
          f"{etiqueta} el almacén se ha reescrito igual: tenía que quedar intacto")
    check(alm.crudo() == {"openai_api_key": V1, "telegram_bot_token": V2},
          f"{etiqueta} el almacén ha quedado medio migrado (parte cifrado, parte en claro)")
    check("AVISO" in avisos and "secrets.json" in avisos,
          f"{etiqueta} no se avisa de que no se ha podido guardar: {avisos.strip()[:160]}")
    check(V1 not in avisos and V2 not in avisos,
          "el aviso de fallo de escritura imprime el VALOR de una clave")
    check(ajustes.secret("openai_api_key") == V1,
          f"{etiqueta} nexus se queda sin la clave (tiene que seguir en memoria)")
    check(ajustes.secret("telegram_bot_token") == V2,
          f"{etiqueta} nexus pierde la segunda clave")
    check(not list(alm.carpeta.glob("*.tmp")),
          f"{etiqueta} el .tmp se queda en la carpeta: {[x.name for x in alm.carpeta.glob('*.tmp')]}")
    check(set(alm.crudo()) == {"openai_api_key", "telegram_bot_token"},
          f"{etiqueta} el almacén cambió de claves al no poder escribirse")
finally:
    # Se devuelve el permiso ANTES de borrar: `rmtree` necesita escribir en la
    # carpeta para deshacerla.
    os.chmod(alm.carpeta, modo_carpeta)
    os.chmod(alm.ruta, modo_archivo | 0o600)
alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 12) un valor que NO es texto sobrevive a cualquier escritura ==")
# ══════════════════════════════════════════════════════════════════════════
# El almacén es un JSON cualquiera: si una versión futura (o el operador a mano)
# deja ahí un número, un booleano, un nulo o un objeto, NADA de esto puede perder
# ni reescribir ese valor. No se entiende, así que no se usa — pero no es de
# nexus borrarlo.
_ajenos = {"int_key": 5, "bool_key": True, "nul_key": None, "dict_key": {"a": 1}}
alm = Almacen({**_ajenos, "telegram_bot_token": V2})
ajustes, avisos = alm.cargar()
crudo = alm.crudo()
for _nombre, _valor in _ajenos.items():
    check(crudo.get(_nombre) == _valor and type(crudo.get(_nombre)) is type(_valor),
          f"tras migrar, «{_nombre}» ya no está EXACTAMENTE como estaba: {crudo.get(_nombre)!r}")
    check(_nombre in avisos,
          f"el aviso no nombra «{_nombre}»: el operador no sabría qué se ha ignorado")
    check(_nombre in _ilegibles(ajustes),
          f"«{_nombre}» no aparece entre los valores que nexus no puede usar")
check(ajustes.secret("telegram_bot_token") == V2,
      "un valor que no es texto ha tumbado el resto del almacén")
# Y una escritura normal tampoco los toca.
with _Doble(config, "SECRETS_FILE", alm.ruta):
    ajustes.set_secret("openai_api_key", V1)
crudo = alm.crudo()
for _nombre, _valor in _ajenos.items():
    check(crudo.get(_nombre) == _valor and type(crudo.get(_nombre)) is type(_valor),
          f"escribir otra clave ha reescrito o perdido «{_nombre}»: {crudo.get(_nombre)!r}")
check(ajustes.secret("openai_api_key") == V1,
      "la clave nueva no se lee después de guardarla al lado de valores no-texto")
# `secret()` sobre un nombre así no revienta: cae a la variable de entorno, como
# cualquier clave que no esté en el almacén.
os.environ["INT_KEY"] = "desde-el-entorno"
try:
    check(ajustes.secret("int_key") == "desde-el-entorno",
          "secret() sobre un valor no-texto no cae a la variable de entorno")
    check(ajustes.secret("nul_key") == "",
          "secret() sobre un nulo no devuelve vacío")
finally:
    os.environ.pop("INT_KEY", None)
alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 13) borrar un secreto ilegible: desaparece del disco y los vecinos quedan ==")
# ══════════════════════════════════════════════════════════════════════════
# Poner «» es la forma que tiene el operador de quitarse de en medio una clave
# que aquí no se puede abrir (otra máquina, otra cuenta de Windows). Antes no se
# podía: el blob volvía al archivo en cada escritura. Ahora se borra, y solo ese.
if not HAY_DPAPI:
    _saltados.append("13) borrado de un blob ajeno (necesita DPAPI)")
else:
    ajeno = cripto.PREFIJO + base64.b64encode(b"basura de otra maquina" * 4).decode("ascii")
    alm = Almacen({"openai_api_key": ajeno, "telegram_bot_token": V2,
                   "anthropic_api_key": V1})
    ajustes, _avisos = alm.cargar()
    check("openai_api_key" in _ilegibles(ajustes),
          "el blob ajeno no se nombra como ilegible antes de borrarlo")
    check(ajustes.secret("openai_api_key") == "",
          "un blob ajeno devuelve algo antes de borrarlo")
    with _Doble(config, "SECRETS_FILE", alm.ruta):
        ajustes.set_secret("openai_api_key", "")
    crudo = alm.crudo()
    check("openai_api_key" not in crudo,
          "tras borrarlo, el secreto ilegible SIGUE en el archivo (no se puede quitar)")
    check(ajeno not in alm.bytes().decode("utf-8"),
          "el blob ilegible sigue escrito en el archivo después de borrarlo")
    check("openai_api_key" not in _ilegibles(ajustes),
          "el secreto borrado sigue apareciendo entre los ilegibles")
    check(ajustes.secret("openai_api_key") == "",
          "el secreto borrado sigue devolviendo un valor")
    check(ajustes.secret("telegram_bot_token") == V2,
          "borrar un ilegible se ha llevado por delante a su vecino")
    check(ajustes.secret("anthropic_api_key") == V1,
          "borrar un ilegible se ha llevado por delante al segundo vecino")
    check(cripto.es_cifrado(crudo.get("telegram_bot_token", ""))
          and cripto.es_cifrado(crudo.get("anthropic_api_key", "")),
          "los vecinos han quedado sin cifrar después del borrado")
    alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 14) GET /api/status publica los NOMBRES de las que aquí no se abren ==")
# ══════════════════════════════════════════════════════════════════════════
# Advisory iv sobre 562c777: un fallo de descifrado de DPAPI sólo se veía por la
# consola AL IMPORTAR el módulo. En una ventana sin consola —el .exe, y el día
# que nexus arranca como servicio— eso es un silencio: el operador ve «no hay
# clave» cuando lo que pasa es «la clave está y no se puede abrir desde esta
# cuenta». El estado que el HUD ya pide tiene que poder decirlo. NUNCA devuelve
# valores, SOLO los nombres: un nombre no es un secreto.
if servidor is None:
    check(False, "sin la aplicación no se puede comprobar /api/status")
else:
    async def _pide_estado():
        transporte = httpx.ASGITransport(app=servidor.app, client=("127.0.0.1", 4321))
        async with httpx.AsyncClient(transport=transporte,
                                     base_url="http://127.0.0.1:8177") as c:
            return await c.get("/api/status", headers={"host": "127.0.0.1:8177"})

    try:
        estado = asyncio.run(_pide_estado())
    except Exception as exc:                                   # noqa: BLE001
        check(False, f"GET /api/status ha reventado: {exc}")
        estado = None
    if estado is not None:
        check(estado.status_code == 200, f"GET /api/status devolvió {estado.status_code}")
        cuerpo = estado.json()
        check("secretos_ilegibles" in cuerpo,
              "GET /api/status no publica secretos_ilegibles: el fallo de descifrado "
              "sigue siendo invisible fuera de la consola")
        check(cuerpo.get("secretos_ilegibles") == [],
              f"en un estado limpio la lista no está vacía: {cuerpo.get('secretos_ilegibles')!r}")
        check({"metrics", "memory", "stt", "tts", "llm", "skills"} <= set(cuerpo),
              f"el estado ha perdido datos que ya publicaba: {sorted(cuerpo)}")

    if not HAY_DPAPI:
        _saltados.append("14) la clave ilegible en /api/status (necesita DPAPI)")
    else:
        ajeno = cripto.PREFIJO + base64.b64encode(b"basura de otra maquina" * 4).decode("ascii")
        alm = Almacen({"openai_api_key": ajeno, "telegram_bot_token": V1})
        with _Doble(config, "SECRETS_FILE", alm.ruta):
            ajustes, _avisos = alm.cargar()
        check("openai_api_key" in _ilegibles(ajustes),
              "el almacén de la prueba no tiene una clave ilegible: no probaría nada")
        # `app.py` lee el `settings` de su módulo: se le da el almacén de la prueba.
        with _Doble(servidor, "settings", ajustes):
            try:
                estado = asyncio.run(_pide_estado())
            except Exception as exc:                           # noqa: BLE001
                check(False, f"GET /api/status ha reventado con un almacén ilegible: {exc}")
                estado = None
        if estado is not None:
            texto = estado.text
            datos = estado.json()
            check(estado.status_code == 200,
                  f"GET /api/status devolvió {estado.status_code} con un almacén ilegible")
            check(datos.get("secretos_ilegibles") == ["openai_api_key"],
                  "el estado no nombra la clave que aquí no se puede abrir: "
                  f"{datos.get('secretos_ilegibles')!r}")
            check("dpapi:" not in texto,
                  "el estado publica la marca del cifrado (no aporta nada y confunde)")
            check(ajeno not in texto,
                  "el estado publica el BLOB que no se puede abrir")
            check(V1 not in texto,
                  "el estado publica el VALOR de una clave en claro")
            check("telegram_bot_token" not in (datos.get("secretos_ilegibles") or []),
                  "el estado nombra como ilegible una clave que sí se puede usar")
        alm.borrar()

# ══════════════════════════════════════════════════════════════════════════
print("== 10) el almacén de esta suite nunca fue el del operador ==")
# ══════════════════════════════════════════════════════════════════════════
check(str(config.CONFIG_DIR) == _CFG,
      f"la suite ha leído la config real del operador: {config.CONFIG_DIR}")
check(str(config.SECRETS_FILE).startswith(_CFG),
      f"SECRETS_FILE apunta al almacén real del operador: {config.SECRETS_FILE}")
check(str(config.DATA_DIR) == _DATA, f"la suite ha escrito en data/ del operador: {config.DATA_DIR}")

for _d in (_CFG, _DATA):
    shutil.rmtree(_d, ignore_errors=True)

print()
for s in _saltados:
    print(f"  (degradado en esta plataforma: {s})")
if HAY_DPAPI:
    print("  cifrado real comprobado con la DPAPI de Windows (máquina + usuario)")
else:
    print("  SIN cifrado real: esta plataforma no tiene DPAPI. La suite NO prueba el "
          "cifrado, solo el repliegue.")
print(f"\n{'#' * 54}\ntest_secretos_cifrado: {_pass} OK, {len(_fail)} fallos"
      f"{f', {len(_saltados)} secciones degradadas' if _saltados else ''}")
for m in _fail:
    print("  -", m)
sys.exit(1 if _fail else 0)
