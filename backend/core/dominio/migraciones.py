# -*- coding: utf-8 -*-
"""Migraciones VERSIONADAS del esquema Postgres de nexus (P3-9 / ARQ-08).

El problema que cierra
----------------------
El esquema se creaba con DDL `... IF NOT EXISTS` ejecutado en CADA arranque
(`memory.PgMemory._ensure_schema`). Eso añade tablas y columnas nuevas, pero no
deja constancia de lo aplicado: no hay forma de saber en qué versión está una
instalación, así que un cambio que no sea `IF NOT EXISTS` (un índice, un tipo,
un backfill) no llega NUNCA a las instalaciones ya existentes, y cada arranque
reemite las mismas sentencias sin saber si hacen falta.

Qué hace
--------
- Tabla marcador `schema_version (version, aplicada_en)`. La versión es el
  ÚNICO registro de lo aplicado: no se adivina mirando el catálogo, porque el
  catálogo dice lo que hay, no lo que ya se intentó.
- Las migraciones viven en `MIGRACIONES`, numeradas y en orden creciente.
- El BASELINE de una instalación nueva NO se copia aquí: lo inyecta el llamante
  (`memory.PgMemory._DDL`) para que exista UNA sola copia de la verdad. Duplicar
  las nueve sentencias en dos ficheros es exactamente la deriva que este módulo
  viene a evitar.
- Sólo se aplican las versiones que no están registradas. Si la tabla trae una
  versión MÁS ALTA que la que conoce este código, no se toca nada: un esquema no
  se baja (sería destructivo) y además puede que un nexus más nuevo lo esté
  usando.
- Una migración se registra SOLO cuando todos sus pasos no tolerados han ido
  bien. Si algo falla, la versión NO se apunta: el arranque siguiente lo
  reintenta en vez de mentir. Una migración a medias queda a medias y se ve.
- Transacciones: una por sentencia (`ejecutar` → `commit`; `rollback` si falla),
  que es lo que permite tolerar el fallo de `CREATE EXTENSION vector` sin
  envenenar el resto de la migración — con `autocommit=True`, que es como
  conecta `PgMemory`, cada sentencia ya es su propia transacción. El número de
  versión se apunta en su propia transacción, y por eso una migración a medias
  nunca queda marcada como aplicada.
- `aplicar()` NUNCA lanza: el arranque de nexus no puede caerse por el esquema.
  Devuelve `{"ok", "version", "aplicadas", "avisos"}`.

Lo que este módulo NO hace, a propósito
---------------------------------------
- No crea a fuego los índices GATEADOS: el ivfflat de `memories` espera a
  `memoria.embedding.filas_minimas_indice` (`_maybe_crear_indice_vector`) y el
  único de `huella` espera a que la limpieza de duplicados esté confirmada
  (`crear_indice_huella`). Versionarlos los convertiría en incondicionales, que
  es justo el diseño que se descartó. Esos dos siguen donde estaban.
- No partió `memory.py` en dos: el llamante conserva su DDL y su tolerancia como
  red de seguridad si este runner no puede ni preparar su tabla de versiones.
"""
from __future__ import annotations

TABLA_VERSIONES = "schema_version"

#: Número de la migración que representa el esquema de una instalación nueva:
#: el `_DDL` que `memory.PgMemory` aplicaba en cada arranque. NO se copia aquí.
BASELINE = 1

_SQL_MARCADOR = (
    f"CREATE TABLE IF NOT EXISTS {TABLA_VERSIONES} ("
    "version INT PRIMARY KEY, "
    "aplicada_en TIMESTAMPTZ NOT NULL DEFAULT now())")


class Paso:
    """Una sentencia DDL con sus dos condiciones.

    `tolerado`: si falla, se avisa y se sigue (la migración todavía puede
    registrarse). Solo lo son las sentencias que el diseño ya trata como
    opcionales — hoy, la extensión pgvector.

    `solo_si_fallo`: solo se ejecuta si falló el paso con ESE índice. Es el
    respaldo de `memories` sin columna `embedding` cuando no hay pgvector; se
    calcula solo en `_plan()` mirando el contenido, no por número fijo.
    """

    __slots__ = ("sql", "tolerado", "solo_si_fallo")

    def __init__(self, sql: str, tolerado: bool = False, solo_si_fallo: int | None = None):
        self.sql = sql
        self.tolerado = bool(tolerado)
        self.solo_si_fallo = solo_si_fallo


class Migracion:
    """Un número de versión y los pasos que lo llevan del esquema anterior a él."""

    __slots__ = ("version", "titulo", "pasos")

    def __init__(self, version: int, titulo: str, pasos):
        self.version = int(version)
        self.titulo = titulo
        self.pasos = tuple(pasos)


#: Migraciones posteriores al baseline. La lista va ORDENADA por versión y los
#: números son correlativos: una versión nueva se añade al final, nunca se
#: renumera una que ya esté registrada en alguna instalación.
MIGRACIONES = (
    Migracion(2, "índices de consulta del esquema", (
        # `recall()` (recuperación por texto) y `recent()` piden
        # `kind <> 'conversation' AND retirado_en IS NULL ORDER BY created_at
        # DESC`; la purga y `/api/memoria/estado` filtran la MISMA columna
        # `retirado_en`. Índice PARCIAL: las filas retiradas no ocupan espacio,
        # así que crece con lo vivo, no con lo purgado.
        #
        # No es una promesa de velocidad medida (con las ~700 filas del dueño
        # un recorrido secuencial ya es instantáneo): es la declaración de un
        # índice que, si algún día no está, una instalación vieja recibe por la
        # puerta de las migraciones. Reversible con `DROP INDEX
        # memories_vivas_idx`.
        Paso("CREATE INDEX IF NOT EXISTS memories_vivas_idx "
             "ON memories (created_at DESC) WHERE retirado_en IS NULL"),
    )),
)

#: Versión que conoce ESTE código. Si la base trae una mayor, no se toca.
VERSION_ESQUEMA = max([BASELINE] + [m.version for m in MIGRACIONES])


# ----------------------------------------------------------------------
#  API pública
# ----------------------------------------------------------------------
def aplicar(conn, baseline=(), avisar=None) -> dict:
    """Aplica, en orden, las migraciones cuya versión no esté registrada.

    `baseline` son las sentencias DDL del esquema completo de una instalación
    nueva (en nexus, `memory.PgMemory._DDL`) y se registran como `BASELINE`.

    Nunca lanza: cualquier fallo vuelve como `ok=False` con el motivo en
    `avisos`, y el llamante conserva su propio camino tolerante.
    """
    try:
        return _aplicar(conn, baseline, avisar)
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "version": None, "aplicadas": [],
                "avisos": [f"fallo inesperado del runner "
                           f"({type(exc).__name__}: {exc})"]}


def version_actual(conn) -> int:
    """Versión registrada del esquema, o 0 si no hay ninguna. Solo lectura."""
    versiones = _versiones(conn)
    return max(versiones) if versiones else 0


# ----------------------------------------------------------------------
#  Interior
# ----------------------------------------------------------------------
def _aplicar(conn, baseline, avisar) -> dict:
    resultado: dict = {"ok": False, "version": None, "aplicadas": [], "avisos": []}
    avisar = avisar or _avisar_por_bus

    def anotar(msg: str) -> None:
        resultado["avisos"].append(msg)
        avisar(msg)

    if conn is None:
        anotar("sin conexión a Postgres: no hay nada que migrar")
        return resultado

    ok, error = _intentar(conn, _SQL_MARCADOR)
    if not ok:
        anotar(f"no se pudo preparar {TABLA_VERSIONES} ({error}): el arranque "
               f"conserva su DDL tolerante")
        return resultado

    registradas = _versiones(conn)
    if registradas is None:
        anotar(f"no se pudo leer {TABLA_VERSIONES}: no se aplica nada")
        return resultado

    if registradas and max(registradas) > VERSION_ESQUEMA:
        resultado["version"] = max(registradas)
        resultado["ok"] = True
        anotar(f"el esquema está en la versión {max(registradas)} y este código "
               f"solo conoce la {VERSION_ESQUEMA}: no se toca nada (un esquema "
               f"no se baja)")
        return resultado

    for migracion in _plan(baseline):
        if migracion.version in registradas:
            continue
        if not _aplicar_migracion(conn, migracion, anotar):
            return resultado
        resultado["aplicadas"].append(migracion.version)

    if resultado["aplicadas"]:
        _log("ok", f"🧠 Esquema migrado a la versión "
                   f"{max(resultado['aplicadas'])} "
                   f"(aplicadas: {resultado['aplicadas']})")
    resultado["version"] = max(resultado["aplicadas"]) if resultado["aplicadas"] \
        else max(registradas or [0])
    resultado["ok"] = True
    return resultado


def _plan(baseline) -> list[Migracion]:
    """Baseline (si lo hay) + las migraciones declaradas, en orden."""
    pasos = [p if isinstance(p, Paso) else Paso(p) for p in baseline]
    # El baseline trae DOS formas de crear `memories`: con `embedding
    # vector(n)` y sin él, para cuando no hay pgvector. Es un par
    # «una-u-otra», no dos pasos independientes: la que lleva `embedding` se
    # tolera (sin extensión falla SIEMPRE, y eso es normal) y la otra solo se
    # ejecuta si la principal falló. La segunda NO es tolerada, así que si
    # ambas fallan la versión no se registra.
    # Se reconoce por el CONTENIDO, no por la posición: reordenar `_DDL` no
    # puede romper la migración en silencio.
    indice_extension = next((i for i, p in enumerate(pasos)
                             if "CREATE EXTENSION" in p.sql.upper()), None)
    indice_embedding = next((i for i, p in enumerate(pasos)
                             if "CREATE TABLE IF NOT EXISTS memories" in p.sql
                             and "embedding" in p.sql), None)
    if indice_extension is not None:
        pasos[indice_extension].tolerado = True
    if indice_embedding is not None:
        pasos[indice_embedding].tolerado = True
        for paso in pasos:
            if ("CREATE TABLE IF NOT EXISTS memories" in paso.sql
                    and "embedding" not in paso.sql):
                paso.solo_si_fallo = indice_embedding
    plan: list[Migracion] = []
    if pasos:
        plan.append(Migracion(BASELINE, "baseline (el DDL del arranque)", pasos))
    plan.extend(sorted(MIGRACIONES, key=lambda m: m.version))
    return plan


def _aplicar_migracion(conn, migracion: Migracion, anotar) -> bool:
    fallos: dict[int, str] = {}
    for i, paso in enumerate(migracion.pasos):
        if paso.solo_si_fallo is not None and paso.solo_si_fallo not in fallos:
            continue
        ok, error = _intentar(conn, paso.sql)
        if ok:
            continue
        fallos[i] = error
        if not paso.tolerado:
            anotar(f"migración {migracion.version} «{migracion.titulo}»: el paso "
                   f"{i} no aplicó ({error}). La versión NO se registra y se "
                   f"reintentará en el próximo arranque")
            return False
        anotar(f"migración {migracion.version}: el paso {i} no aplicó ({error}), "
               f"es tolerado y se sigue")
    ok, error = _intentar(
        conn,
        f"INSERT INTO {TABLA_VERSIONES} (version) VALUES (%s) "
        f"ON CONFLICT (version) DO NOTHING",
        (migracion.version,))
    if not ok:
        anotar(f"migración {migracion.version}: no se pudo registrar la versión "
               f"({error}); se reintentará en el próximo arranque")
        return False
    return True


def _intentar(conn, sql: str, params=()) -> tuple[bool, str | None]:
    """Ejecuta una sentencia en su propia transacción. Nunca lanza."""
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        _confirmar(conn)
        return True, None
    except Exception as exc:                                   # noqa: BLE001
        _revertir(conn)
        return False, type(exc).__name__


def _versiones(conn) -> set[int] | None:
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT version FROM {TABLA_VERSIONES} ORDER BY version")
            return {int(fila[0]) for fila in cur.fetchall()}
    except Exception:                                          # noqa: BLE001
        _revertir(conn)
        return None


def _confirmar(conn) -> None:
    try:
        conn.commit()
    except Exception:                                          # noqa: BLE001
        pass


def _revertir(conn) -> None:
    try:
        conn.rollback()
    except Exception:                                          # noqa: BLE001
        pass


def _avisar_por_bus(msg: str) -> None:
    _log("warn", f"🧠 Esquema: {msg}")


def _log(nivel: str, msg: str) -> None:
    try:
        from ..comun.events import bus
        bus.emit_sync("log", {"level": nivel, "msg": msg})
    except Exception:                                          # noqa: BLE001
        pass
