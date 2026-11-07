# -*- coding: utf-8 -*-
"""
nexus — CONTADOR DIARIO DE CONSUMO DEL MODELO (AI-07 / roadmap P2-12, tarea T19).

EL HUECO QUE ESTO CIERRA
------------------------
La auditoría del 30/07/2026 (`05` AI-07 y `07` §5 «Costes y consumo») encontró que
nexus no contaba NADA: ni llamadas, ni caracteres, ni tokens, ni por proveedor ni
por día. Un bucle que se fuera de madre, un flujo de n8n que reenvía el mismo
texto cien veces o una tarde de investigación pesada no tenían techo. Los topes
de SALIDA (`llm.max_tokens_salida`, `eebda43`) acotan UNA respuesta; esto acota
el DÍA.

QUÉ SE CUENTA, Y POR QUÉ CARACTERES
-----------------------------------
Por día de calendario y por proveedor: llamadas (`chat`, `stream`, `distill`,
`embed`), caracteres de prompt y caracteres de respuesta. Los CARACTERES son la
unidad primitiva porque nexus no recibe el uso de tokens de todos los
proveedores: si se contaran solo tokens, la mitad de las llamadas no contarían
nada. Donde el proveedor SÍ devuelve números de verdad, se guardan también —
`_anotar` recibe `tokens_entrada`/`tokens_salida` y solo los escribe si llegan—:

  * `openai` y `cloud` (compatible OpenAI) → `usage.prompt_tokens` /
    `usage.completion_tokens`.
  * `anthropic` → `usage.input_tokens` / `usage.output_tokens`.
  * `gemini` → `usageMetadata.promptTokenCount` / `candidatesTokenCount`.
  * `ollama` → `prompt_eval_count` / `eval_count`.

Ninguno de esos números se estima ni se deduce de los caracteres: si el
proveedor no lo manda, el campo no existe. Por eso el resumen dice, por
proveedor, si sus números son de verdad o solo caracteres.

DÓNDE SE ESCRIBE, Y POR QUÉ NO FRENA LA VOZ
-------------------------------------------
Una sola escritura por llamada al modelo, DESPUÉS de tener la respuesta, en
`DATA_DIR/presupuesto_llm.json`, con `comun/atomicos.escribir_json_atomico`
(nunca `write_text`) y fuera del bucle de eventos (`asyncio.to_thread`). Nunca
se escribe antes de llamar al modelo, así que el contador no puede retrasar el
primer token; y como el archivo es de unos pocos KB y la llamada al modelo que
lo precede cuesta cientos de milisegundos, el tiempo del volcado (milisegundos,
en otro hilo) queda dentro del ruido. El día es la CLAVE del documento: un
cambio de día no puede mezclar contadores. Se conservan hoy y ayer, y nada más:
un contador diario no necesita historia para hacer su trabajo.

DOS GEMELOS, UNA CUENTA (`anotar`/`exigir` y `anotar_sync`/`exigir_sync`)
-------------------------------------------------------------------------
El chat, el streaming, el destilado y las sondas viven en corrutinas: usan la
versión asíncrona. Los EMBEDDINGS no: `dominio/rag.py` habla con su proveedor
con `httpx.post` síncrono y ya corre dentro de un `asyncio.to_thread`, porque de
otra forma bloquearía el bucle. Desde ese hilo no se puede esperar una
corrutina, así que el gemelo síncrono hace la misma suma (`_sumar`) y el mismo
volcado atómico (`_volcar_sync`) ahí mismo, y publica el aviso con
`bus.emit_sync`. No hay dos contadores: hay una cuenta y dos formas de esperar
a que no haya un bucle en medio.

SI EL ARCHIVO FALLA, NO SE ROMPE EL CHAT
----------------------------------------
Un fallo al guardar (disco lleno, archivo bloqueado) NO puede tumbar una
respuesta ya generada: se anota el error, se sigue y se dice en
`resumen()["error_guardado"]`. La verdad en memoria es el documento completo y
cada volcado lo reescribe entero, así que lo que no entró en un volcado entra en
el siguiente — no se pierde nada por un fallo puntual.

EL TECHO, Y POR QUÉ LOS LOCALES NO ESTÁN DENTRO
-----------------------------------------------
`config/umbrales.json → llm.presupuesto_diario_llamadas` y
`llm.presupuesto_diario_caracteres`. Al llegar al techo, nexus RECHAZA más
llamadas a la nube con un mensaje que dice qué ha pasado, qué ha contado y cómo
subirlo — no hay recorte silencioso ni respuesta inventada. Hay DOS textos, uno
para conversar y otro para vectorizar, porque son dos cosas distintas (ver
`_mensaje_agotado`). Los proveedores LOCALES (`ollama`, `mock`) no están sujetos
al techo por defecto porque el riesgo del que habla la auditoría es el DINERO, y
un modelo local no cuesta dinero: frenarlo sería castigar justo la opción que la
propia auditoría recomienda. `llm.presupuesto_incluye_locales: true` los mete
también dentro, para quien comparta equipo y quiera un techo único. Un EMBEDDING
de nube sí pasa por el techo (es dinero y es texto que sale del equipo); uno de
Ollama no.

EL CANAL NO ES UNA DIMENSIÓN, Y ES A PROPÓSITO
----------------------------------------------
El canal (texto, voz, Telegram, n8n, móvil) habría multiplicado los cubos por
seis, pero el motivo para no meterlo no es el tamaño del archivo (sería unos
pocos KB): es que `llm.py` NO recibe el canal. Quien lo sabe es `brain.py`, y
añadir la dimensión obligaba a atravesar con un parámetro nuevo toda la cadena
de llamadas para, aun así, no poder contarlo en las llamadas directas a
`prov.chat()` que hacen `brain`, `pm`, las skills y `app`. Un cubo «canal»
medio relleno mentiría. Un flujo de n8n que reenvía el mismo texto se ve igual
de bien en lo que sí se cuenta: las llamadas del día se disparan en minutos y el
techo las corta.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
from pathlib import Path

from . import config
from .atomicos import escribir_json_atomico

# Las clases de llamada que se cuentan. `chat`, `stream` y `distill` los rellena
# `infraestructura/llm.py` (todas las llamadas a un proveedor pasan por ahí, ver
# `llm._instalar_contabilidad`). `embed` lo rellena `dominio/rag.py` en
# `_emb_ollama`, `_emb_openai` y `_emb_gemini`, que son síncronas y corren en un
# hilo de trabajo: por eso existe el gemelo `anotar_sync`/`exigir_sync`.
CLASES = ("chat", "stream", "distill", "embed")

ARCHIVO = "presupuesto_llm.json"

# Reserva si `config/umbrales.json` falta o está roto. NO son cifras medidas: son
# un techo de seguridad elegido para UN usuario en un escritorio (una persona, no
# un servidor) y se explican en el propio archivo de umbrales. Ver `limites()`.
UMBRALES_RESERVA = {
    "presupuesto_diario_llamadas": 400,
    "presupuesto_diario_caracteres": 5_000_000,
    "presupuesto_incluye_locales": False,
}


class PresupuestoAgotado(RuntimeError):
    """El techo diario está alcanzado: NO se hace la llamada.

    Lleva el mensaje público (lo que ve el operador, en español y con lo que ha
    contado) y un detalle técnico para el registro. Quien lo captura NO debe
    convertir esto en una respuesta del modelo: se dice lo que pasa."""

    def __init__(self, publico: str, tecnico: str = ""):
        super().__init__(tecnico or publico)
        self.publico = publico
        self.tecnico = tecnico


# ─────────────────────────── el documento en memoria ───────────────────────────
#
# `_DOC` es la VERDAD mientras el proceso vive: se carga una vez del archivo y
# cada volcado escribe el documento ENTERO. Así un volcado que falle no pierde
# incrementos (el siguiente los incluye) y no hacen falta candados: nexus es un
# proceso asyncio y estas funciones se ejecutan en el bucle, una detrás de otra.
_DOC: dict | None = None
_ultimo_error = ""
_aviso_80_dia = ""


def _hoy() -> str:
    """El día de calendario del contador. Se lee por aquí para que una prueba
    pueda mover el reloj sin dormir una hora: patch de esta función."""
    return _dt.date.today().isoformat()


def _ayer() -> str:
    return (_dt.date.fromisoformat(_hoy()) - _dt.timedelta(days=1)).isoformat()


def ruta_archivo() -> Path:
    """El archivo del contador, resuelto en CADA uso (NEXUS_DATA_DIR cambia entre
    pruebas y el ejecutable empaquetado apunta a otra carpeta)."""
    return Path(config.DATA_DIR) / ARCHIVO


def _vacio() -> dict:
    return {"version": 1, "localidad": {}, "dias": {}}


def _leer() -> dict:
    """El documento del disco, o uno vacío. Un archivo roto NO rompe nada: se
    pierde el contador del día (nadie se queda sin poder hablar por esto) y el
    siguiente volcado lo deja válido otra vez."""
    try:
        f = ruta_archivo()
        if f.is_file():
            datos = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(datos, dict) and isinstance(datos.get("dias"), dict):
                datos.setdefault("version", 1)
                if not isinstance(datos.get("localidad"), dict):
                    datos["localidad"] = {}
                return datos
    except Exception:                                          # noqa: BLE001
        pass
    return _vacio()


def _poda(doc: dict) -> None:
    """Hoy y ayer. Nada más: el contador es diario y no necesita historia."""
    dias = doc.get("dias") or {}
    if not isinstance(dias, dict):
        doc["dias"] = {}
        return
    permitidos = (_hoy(), _ayer())
    for clave in list(dias):
        if clave not in permitidos:
            dias.pop(clave, None)


def _documento() -> dict:
    global _DOC
    if _DOC is None:
        _DOC = _leer()
    _poda(_DOC)
    return _DOC


def _cubo(doc: dict, proveedor: str, clase: str) -> dict:
    dia = doc["dias"].setdefault(_hoy(), {})
    prov = dia.setdefault(proveedor, {})
    clases = prov.setdefault("clases", {})
    return clases.setdefault(clase, {"llamadas": 0, "caracteres_entrada": 0,
                                     "caracteres_salida": 0})


def _es_local(doc: dict, proveedor: str) -> bool:
    return bool((doc.get("localidad") or {}).get(proveedor, False))


# ─────────────────────────────── los umbrales ───────────────────────────────
def limites() -> dict:
    """Los tres números del techo, leídos de config/umbrales.json en CADA uso.

    Un valor que no vale (0, negativo, texto, booleano) NO se acepta: se queda la
    reserva. Un techo de 0 cortaría TODAS las llamadas a la nube y convertiría un
    archivo mal editado en «nexus no habla», que es peor que gastar un poco."""
    vals = dict(UMBRALES_RESERVA)
    try:
        f = Path(config.CONFIG_DIR) / "umbrales.json"
        if f.is_file():
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("llm") or {}
            for clave in ("presupuesto_diario_llamadas", "presupuesto_diario_caracteres"):
                valor = leido.get(clave)
                if isinstance(valor, int) and not isinstance(valor, bool) and valor > 0:
                    vals[clave] = valor
            if isinstance(leido.get("presupuesto_incluye_locales"), bool):
                vals["presupuesto_incluye_locales"] = leido["presupuesto_incluye_locales"]
    except Exception:                                          # noqa: BLE001
        pass
    return vals


def _totales(doc: dict, *, incluir_locales: bool) -> dict:
    """Llamadas y caracteres de HOY, contando o no los proveedores locales."""
    dia = doc["dias"].get(_hoy(), {})
    total = {"llamadas": 0, "caracteres": 0}
    for proveedor, datos in dia.items():
        if not incluir_locales and _es_local(doc, proveedor):
            continue
        for contadores in ((datos or {}).get("clases") or {}).values():
            total["llamadas"] += int(contadores.get("llamadas") or 0)
            total["caracteres"] += (int(contadores.get("caracteres_entrada") or 0)
                                    + int(contadores.get("caracteres_salida") or 0))
    return total


# ─────────────────────────────── el bus ───────────────────────────────
async def _avisar(msg: str, *, level: str = "warning") -> None:
    """Un aviso de verdad en el bus que ya existe (`log`): lo pinta el HUD y queda
    en data/nexus.log. Es lo que hace OBSERVABLE el techo; callarlo dejaría al
    operador con un «no tengo cerebro» sin saber que era el presupuesto."""
    try:
        from . import events
        await events.log(msg, level=level)
    except Exception:                                          # noqa: BLE001
        pass


def _avisar_sync(msg: str, *, level: str = "warning") -> None:
    """El mismo aviso desde el gemelo síncrono (hilo de trabajo, sin bucle).

    `bus.emit_sync` existe justo para esto: lo usa medio programa desde hilos sin
    bucle propio, y el aviso llega al HUD y a data/nexus.log igual que el
    asíncrono. Callar el aviso del techo dejaría al operador viendo «el RAG no
    encuentra nada» cuando lo que pasa es que no hay presupuesto."""
    try:
        from . import events
        events.bus.emit_sync("log", {"level": level, "msg": msg})
    except Exception:                                          # noqa: BLE001
        pass


def _miles(n) -> str:
    """Un número para leerlo en español: 5000 → «5.000».

    El mensaje del techo habla de millones de caracteres; en crudo
    («5000000») el operador tiene que contarlos con el dedo."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def _mensaje_agotado(proveedor: str, total: dict, lim: dict,
                     caracteres_que_faltan: int, *, clase: str = "chat") -> str:
    """Lo que lee el operador cuando el techo corta la llamada.

    DOS TEXTOS, porque son dos cosas distintas: quedarse sin poder conversar y
    quedarse sin poder vectorizar. El de `embed` lo dice con esas palabras para
    que nadie confunda «no hay vector nuevo» con «nexus está roto». Los dos dicen
    qué ha pasado, qué ha contado y cómo subirlo, y ninguno finge una respuesta.
    """
    cuenta = (
        f"Llevo {_miles(total['llamadas'])} llamadas y {_miles(total['caracteres'])} "
        f"caracteres contados hoy, y el tope del día es "
        f"{_miles(lim['presupuesto_diario_llamadas'])} llamadas y "
        f"{_miles(lim['presupuesto_diario_caracteres'])} caracteres: esta llamada, "
        f"con {_miles(max(0, int(caracteres_que_faltan)))} caracteres de prompt, ya no "
        "cabe.")
    como_subirlo = (
        "Si quieres seguir hoy, súbelo en ⚙ o en config/umbrales.json "
        "(«llm.presupuesto_diario_llamadas» y «llm.presupuesto_diario_caracteres»).")
    if clase == "embed":
        return (
            "He parado la vectorización: hoy ya he gastado el presupuesto de modelo que "
            f"hay puesto y no voy a mandar más texto a {proveedor} para embeddings hasta "
            f"mañana. {cuenta} Esto NO es un fallo del modelo: es el aviso de que se ha "
            "acabado el presupuesto, y sin presupuesto no hay vector nuevo. La memoria "
            "sigue respondiendo por palabra (el RAG degrada, no miente). "
            f"{como_subirlo} Los embeddings locales de Ollama no están limitados por "
            "este techo.")
    return (
        f"Me he parado: hoy ya he gastado el presupuesto de modelo que hay puesto y no "
        f"voy a llamar más a {proveedor} hasta mañana. {cuenta} Esto NO es una respuesta "
        "del modelo: es el aviso de que se ha acabado el presupuesto, y prefiero decírtelo "
        f"a inventarme una contestación. {como_subirlo} Los modelos locales de Ollama no "
        "están limitados por este techo, así que el chat sigue funcionando si lo tienes "
        "puesto.")


# ─────────────────────────── la puerta y el contador ───────────────────────────
def _motivo(proveedor: str, caracteres_prompt: int, local: bool,
            lim: dict) -> tuple[dict, dict] | None:
    """(total, límites) si la llamada NO cabe; None si cabe.

    La MISMA cuenta para las dos puertas (asíncrona y síncrona): dos copias de
    esta regla serían dos verdades sobre el mismo dinero."""
    if local and not lim["presupuesto_incluye_locales"]:
        return None
    total = _totales(_documento(), incluir_locales=lim["presupuesto_incluye_locales"])
    pasado_llamadas = total["llamadas"] >= lim["presupuesto_diario_llamadas"]
    pasado_caracteres = (total["caracteres"] + max(0, int(caracteres_prompt or 0))
                         > lim["presupuesto_diario_caracteres"])
    return (total, lim) if (pasado_llamadas or pasado_caracteres) else None


def _techo(proveedor: str, motivo: tuple[dict, dict], caracteres_prompt: int,
           clase: str) -> PresupuestoAgotado:
    total, lim = motivo
    publico = _mensaje_agotado(proveedor, total, lim, caracteres_prompt, clase=clase)
    return PresupuestoAgotado(
        publico,
        f"techo diario alcanzado para {proveedor} ({clase}): {total['llamadas']}/"
        f"{lim['presupuesto_diario_llamadas']} llamadas, {total['caracteres']}/"
        f"{lim['presupuesto_diario_caracteres']} caracteres")


async def exigir(proveedor: str, caracteres_prompt: int, *, local: bool,
                 clase: str = "chat") -> None:
    """¿Se puede hacer esta llamada AHORA? Si no, lanza `PresupuestoAgotado`.

    Se llama ANTES del transporte: cuando el techo está alcanzado no sale ni una
    petición. `local` lo decide quien conoce la clase del proveedor
    (`llm.localidad_proveedor`); aquí no se duplica esa tabla."""
    motivo = _motivo(proveedor, caracteres_prompt, local, limites())
    if motivo is None:
        return
    fallo = _techo(proveedor, motivo, caracteres_prompt, clase)
    await _avisar(fallo.publico)
    raise fallo


def exigir_sync(proveedor: str, caracteres_prompt: int, *, local: bool,
                clase: str = "chat") -> None:
    """La misma puerta, desde un hilo de trabajo (el de los embeddings).

    `rag._emb_ollama/_emb_openai/_emb_gemini` son funciones SÍNCRONAS con
    `httpx.post` y ya corren dentro de un `asyncio.to_thread` (de otra forma
    bloquearían el bucle). Desde ese hilo no se puede esperar una corrutina, así
    que el aviso sale por `bus.emit_sync` y el volcado se hace ahí mismo: el
    resultado es el mismo que el de la puerta asíncrona — ni una petición cuando
    el techo está alcanzado — sin inventar un segundo contador."""
    motivo = _motivo(proveedor, caracteres_prompt, local, limites())
    if motivo is None:
        return
    fallo = _techo(proveedor, motivo, caracteres_prompt, clase)
    _avisar_sync(fallo.publico)
    raise fallo


def _n(valor) -> int | None:
    if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0:
        return valor
    return None


def _sumar(proveedor: str, clase: str, *, caracteres_entrada: int,
           caracteres_salida: int, tokens_entrada, tokens_salida,
           local: bool | None, llamadas: int) -> None:
    """La cuenta, en memoria y sin tocar disco. La comparten los dos contadores."""
    doc = _documento()
    if local is not None:
        doc.setdefault("localidad", {})[proveedor] = bool(local)
    cubo = _cubo(doc, proveedor, clase)
    cubo["llamadas"] = int(cubo.get("llamadas") or 0) + max(0, int(llamadas or 0))
    cubo["caracteres_entrada"] = (int(cubo.get("caracteres_entrada") or 0)
                                  + max(0, int(caracteres_entrada or 0)))
    cubo["caracteres_salida"] = (int(cubo.get("caracteres_salida") or 0)
                                 + max(0, int(caracteres_salida or 0)))
    # Los tokens SOLO si el proveedor los ha dado: nada de estimarlos.
    ent, sal = _n(tokens_entrada), _n(tokens_salida)
    if ent is not None:
        cubo["tokens_entrada"] = int(cubo.get("tokens_entrada") or 0) + ent
    if sal is not None:
        cubo["tokens_salida"] = int(cubo.get("tokens_salida") or 0) + sal


async def anotar(proveedor: str, clase: str, *, caracteres_entrada: int = 0,
                 caracteres_salida: int = 0, tokens_entrada=None,
                 tokens_salida=None, local: bool | None = None,
                 llamadas: int = 1) -> bool:
    """Suma una llamada al contador de hoy y lo vuelca al disco.

    NO lanza nunca: un contador que rompe la conversación es peor que un
    contador incompleto. Devuelve si el volcado salió bien."""
    global _ultimo_error
    clase = clase if clase in CLASES else "chat"
    try:
        _sumar(proveedor, clase, caracteres_entrada=caracteres_entrada,
               caracteres_salida=caracteres_salida, tokens_entrada=tokens_entrada,
               tokens_salida=tokens_salida, local=local, llamadas=llamadas)
    except Exception as exc:                                   # noqa: BLE001
        _ultimo_error = f"{type(exc).__name__}: {exc}"
        return False
    aviso = _toca_aviso_80()
    if aviso:
        await _avisar(aviso, level="warn")
    return await volcar()


def anotar_sync(proveedor: str, clase: str, *, caracteres_entrada: int = 0,
                caracteres_salida: int = 0, tokens_entrada=None,
                tokens_salida=None, local: bool | None = None,
                llamadas: int = 1) -> bool:
    """El contador de los embeddings: la misma suma y el volcado ATÓMICO en el
    mismo hilo de trabajo. No lanza nunca; devuelve si el volcado salió bien.

    No se llama nunca desde el bucle: `rag._emb_*` ya corre en un hilo
    (`asyncio.to_thread`) junto a un `httpx.post` síncrono que bloquea ese hilo.
    El volcado de unos KB no cambia lo que ve el operador ni añade un camino
    nuevo de bloqueo: sin `to_thread` aquí no hay bucle que proteger."""
    global _ultimo_error
    clase = clase if clase in CLASES else "chat"
    try:
        _sumar(proveedor, clase, caracteres_entrada=caracteres_entrada,
               caracteres_salida=caracteres_salida, tokens_entrada=tokens_entrada,
               tokens_salida=tokens_salida, local=local, llamadas=llamadas)
    except Exception as exc:                                   # noqa: BLE001
        _ultimo_error = f"{type(exc).__name__}: {exc}"
        return False
    aviso = _toca_aviso_80()
    if aviso:
        _avisar_sync(aviso, level="warn")
    return _volcar_sync()


def _volcar_sync() -> bool:
    """El volcado, tal cual: lo llama el contador síncrono (ya está en un hilo) y
    el asíncrono a través de `asyncio.to_thread`."""
    global _ultimo_error
    doc = _DOC
    if doc is None:
        return True
    try:
        copia = json.loads(json.dumps(doc, ensure_ascii=False))
        escribir_json_atomico(ruta_archivo(), copia)
        _ultimo_error = ""
        return True
    except Exception as exc:                                   # noqa: BLE001
        _ultimo_error = f"{type(exc).__name__}: {exc}"
        return False


async def volcar() -> bool:
    """Escribe el documento entero, FUERA del bucle de eventos.

    `asyncio.to_thread` porque la escritura es de disco: en el bucle dejaría
    esperando al audio, al WebSocket y a la voz. El archivo se publica con
    `os.replace` (indivisible), así que un corte deja el contador ANTERIOR
    entero, nunca medio archivo."""
    return await asyncio.to_thread(_volcar_sync)


def _toca_aviso_80() -> str | None:
    """El aviso al 80 %, UNA vez al día (lo pedía `07` §5: «un aviso al 80 %»).

    Es una recomendación de la auditoría, no un adorno: enterarse de que queda un
    20 % sirve para decidir; enterarse cuando ya no hay nada, no. Devuelve el
    texto si toca avisar (y marca el día) o None. Los dos contadores comparten la
    decisión, para no avisar dos veces por la misma llamada."""
    global _aviso_80_dia
    try:
        if _aviso_80_dia == _hoy():
            return None
        lim = limites()
        total = _totales(_documento(), incluir_locales=lim["presupuesto_incluye_locales"])
        tope_llamadas = lim["presupuesto_diario_llamadas"]
        tope_caracteres = lim["presupuesto_diario_caracteres"]
        cerca = (total["llamadas"] >= 0.8 * tope_llamadas
                 or total["caracteres"] >= 0.8 * tope_caracteres)
        if not cerca:
            return None
        _aviso_80_dia = _hoy()
        return (f"Voy por el 80 % del presupuesto de modelo de hoy: "
                f"{_miles(total['llamadas'])} de {_miles(tope_llamadas)} llamadas y "
                f"{_miles(total['caracteres'])} de {_miles(tope_caracteres)} caracteres. "
                "Cuando llegue al tope dejaré de llamar a la nube hasta mañana "
                "(los modelos locales no están limitados). Se cambia en ⚙ o en "
                "config/umbrales.json, sección «llm».")
    except Exception:                                          # noqa: BLE001
        return None


def resumen() -> dict:
    """El estado de hoy para `GET /api/status`. Números, nombres de proveedor y
    de clase: NUNCA una clave, un modelo ni un fragmento de prompt."""
    try:
        lim = limites()
        doc = _documento()
        dia = doc["dias"].get(_hoy(), {})
        por_proveedor: dict = {}
        tokens_reales: list[str] = []
        for proveedor, datos in sorted(dia.items()):
            clases = {clase: dict(contadores) for clase, contadores
                      in ((datos or {}).get("clases") or {}).items()}
            usa_tokens = any(("tokens_entrada" in c or "tokens_salida" in c)
                             for c in clases.values())
            if usa_tokens:
                tokens_reales.append(proveedor)
            por_proveedor[proveedor] = {
                "local": _es_local(doc, proveedor),
                "llamadas": sum(int(c.get("llamadas") or 0) for c in clases.values()),
                "caracteres_entrada": sum(int(c.get("caracteres_entrada") or 0)
                                          for c in clases.values()),
                "caracteres_salida": sum(int(c.get("caracteres_salida") or 0)
                                         for c in clases.values()),
                "tokens_reales": usa_tokens,
                "clases": clases,
            }
        total = _totales(doc, incluir_locales=lim["presupuesto_incluye_locales"])
        return {
            "dia": _hoy(),
            "llamadas": total["llamadas"],
            "caracteres": total["caracteres"],
            "limites": {
                "llamadas": lim["presupuesto_diario_llamadas"],
                "caracteres": lim["presupuesto_diario_caracteres"],
                "incluye_locales": bool(lim["presupuesto_incluye_locales"]),
            },
            "agotado": bool(total["llamadas"] >= lim["presupuesto_diario_llamadas"]
                            or total["caracteres"] >= lim["presupuesto_diario_caracteres"]),
            "por_proveedor": por_proveedor,
            "tokens_reales": sorted(tokens_reales),
            "error_guardado": _ultimo_error,
        }
    except Exception as exc:                                   # noqa: BLE001
        return {"dia": _hoy(), "por_proveedor": {}, "tokens_reales": [],
                "error_guardado": f"{type(exc).__name__}: {exc}"}
