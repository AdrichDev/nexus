# -*- coding: utf-8 -*-
"""Rangos «del X al Y»: el día en que se habla no puede cambiar lo entendido.

Fallo real medido el 05/08/2026, que era MIÉRCOLES. El operador pidió:

  «créame una tarea que dure del miércoles de esta semana hasta el domingo
   que sea Festival Sonorama Aranda de Duero»

y nexus guardó del 2026-08-12 al 2026-08-16: una semana entera de más, y encima
el rango salía del revés antes de que un parche lo empujase. Tres motivos, todos
en `skills/tasks_board/skill.py`:

  1) el ARRANQUE de un rango nunca podía ser hoy: dicho un miércoles,
     «miércoles» saltaba ocho días.
  2) «de esta semana» / «de la semana que viene» se reconocían y se TIRABAN al
     suelo, así que decirlas no cambiaba absolutamente nada.
  3) cada extremo se resolvía por su cuenta y NADA comprobaba que el fin fuera
     posterior al inicio: salían rangos invertidos sin una sola queja.

Esta suite CLAVA el día de la semana y comprueba los SIETE. El defecto llevaba
escondido desde que se escribió porque las suites viejas dependían del
`date.today()` de verdad: solo se veía de miércoles a sábado, y el resto de la
semana pasaban en verde tapando el fallo.

El oráculo son fechas ABSOLUTAS escritas a mano, no una reimplementación de la
lógica de producción: si el test calculase lo mismo que la skill, ambos podrían
equivocarse a la vez y nadie se enteraría.

Semana de referencia: lunes 2026-08-03 … domingo 2026-08-09.

Ejecutar:  .venv\\Scripts\\python.exe tests\\test_rangos_semana.py
"""
from __future__ import annotations

import contextlib
import datetime as dt
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
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
        print("  ✖ " + msg)
    return bool(cond)


from backend.core.aplicacion import skills_loader as sl      # noqa: E402

REG = sl.load_skills()
TSK = REG.get("tasks_board")
TB = TSK.module if TSK else None
if not check(TB is not None, "la skill tasks_board no carga"):
    sys.exit(1)

NOMBRES = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
LUNES_REF = dt.date(2026, 8, 3)
SEMANA_REF = [LUNES_REF + dt.timedelta(days=i) for i in range(7)]
# La semana siguiente a la de referencia, para las coletillas «que viene».
LUNES_SIG = LUNES_REF + dt.timedelta(days=7)


@contextlib.contextmanager
def hoy_es(fecha: dt.date):
    """Clava `date.today()` DENTRO de la skill mientras dure el bloque.

    Se sustituye el módulo `datetime` que ve la skill por un clon cuyo `date`
    responde siempre la misma fecha. Sin esto el test volvería a depender del
    calendario real, que es justo lo que dejó el fallo escondido."""
    class _Fecha(dt.date):
        @classmethod
        def today(cls):                                      # noqa: D102
            return dt.date(fecha.year, fecha.month, fecha.day)

    original = TB.dt
    TB.dt = types.SimpleNamespace(date=_Fecha, timedelta=dt.timedelta,
                                  datetime=dt.datetime, time=dt.time)
    try:
        yield
    finally:
        TB.dt = original


def rango(frase: str, hoy: dt.date) -> tuple[str | None, str | None]:
    """El rango que entiende la skill si HOY fuese `hoy`."""
    with hoy_es(hoy):
        _limpio, ini, fin = TB._extract_range(frase)
    return ini, fin


def dicho_el(hoy: dt.date) -> str:
    return f"dicho el {NOMBRES[hoy.weekday()]} {hoy.isoformat()}"


# ═══════════ 1) la frase del operador, dicha CUALQUIER día de esa semana ═══════════
print("== 1) «del miércoles de esta semana hasta el domingo» los siete días ==")

# «de esta semana» es una fecha ANCLADA: el operador ha dicho con todas las
# letras de qué semana habla, así que la respuesta es la misma tanto si lo pide
# el lunes como el domingo. Es el caso que llegó roto desde producción.
FRASE_OPERADOR = ("que dure del miercoles de esta semana hasta el domingo "
                  "que sea Festival Sonorama Aranda de Duero")
for hoy in SEMANA_REF:
    ini, fin = rango(FRASE_OPERADOR, hoy)
    check((ini, fin) == ("2026-08-05", "2026-08-09"),
          f"{dicho_el(hoy)}, la frase del operador debe dar "
          f"2026-08-05 → 2026-08-09 y ha dado {ini} → {fin}")

# La misma frase con tilde y con «al» en vez de «hasta el».
for hoy in SEMANA_REF:
    ini, fin = rango("del miércoles de esta semana al domingo", hoy)
    check((ini, fin) == ("2026-08-05", "2026-08-09"),
          f"{dicho_el(hoy)}, «del miércoles de esta semana al domingo» debe dar "
          f"2026-08-05 → 2026-08-09 y ha dado {ini} → {fin}")


# ═══════════ 2) el arranque de un rango SÍ puede ser hoy ═══════════
print("== 2) «del <hoy> al domingo» arranca HOY, no dentro de ocho días ==")

# Quien un miércoles dice «del miércoles al domingo» está hablando de hoy. La
# regla vieja («nunca hoy») convertía un festival de cinco días en otro que
# empezaba la semana siguiente.
for hoy in SEMANA_REF:
    nombre = NOMBRES[hoy.weekday()]
    ini, fin = rango(f"del {nombre} al domingo", hoy)
    check(ini == hoy.isoformat(),
          f"{dicho_el(hoy)}, «del {nombre} al domingo» tiene que empezar hoy "
          f"({hoy.isoformat()}) y empieza el {ini}")
    check(fin is not None and fin >= (ini or ""),
          f"{dicho_el(hoy)}, «del {nombre} al domingo» acaba antes de empezar: "
          f"{ini} → {fin}")


# ═══════════ 3) JAMÁS un rango del revés, ningún día, con ningún par ═══════════
print("== 3) los 49 pares de días, los siete días de la semana ==")

# 7 días × 49 pares = 343 rangos. Es la red que impide que el fallo se vuelva a
# esconder en los días de la semana que nadie probaba.
_invertidos = 0
_sin_rango = 0
for hoy in SEMANA_REF:
    for a in NOMBRES:
        for b in NOMBRES:
            frase = f"del {a} al {b}"
            ini, fin = rango(frase, hoy)
            if not (ini and fin):
                _sin_rango += 1
                _fail.append(f"{dicho_el(hoy)}, «{frase}» no saca ningún rango")
                continue
            d_ini = dt.date.fromisoformat(ini)
            d_fin = dt.date.fromisoformat(fin)
            if d_fin < d_ini:
                _invertidos += 1
                _fail.append(f"{dicho_el(hoy)}, «{frase}» sale del revés: {ini} → {fin}")
                continue
            _pass += 1
            check(d_ini >= hoy,
                  f"{dicho_el(hoy)}, «{frase}» arranca en el pasado: {ini}")
            check((d_fin - d_ini).days <= 6,
                  f"{dicho_el(hoy)}, «{frase}» dura {(d_fin - d_ini).days} días; sin "
                  f"coletilla dos días de la semana caben de sobra en una: {ini} → {fin}")
            check(NOMBRES[d_ini.weekday()] == a,
                  f"{dicho_el(hoy)}, «{frase}» no arranca en {a}: {ini}")
            check(NOMBRES[d_fin.weekday()] == b,
                  f"{dicho_el(hoy)}, «{frase}» no acaba en {b}: {fin}")
print(f"   343 rangos: {_invertidos} invertidos, {_sin_rango} sin entender")


# ═══════════ 4) las coletillas MANDAN, no se tiran ═══════════
print("== 4) «de esta semana» / «que viene» / «próximo» cambian la respuesta ==")

# Un grupo no capturador se tragaba estas palabras sin usarlas. Decirlas o
# callárselas daba el mismo resultado, que es la definición de no entender.
COLETILLAS_SIGUIENTE = ("de la semana que viene", "que viene", "próximo", "proximo")
for coletilla in COLETILLAS_SIGUIENTE:
    for hoy in SEMANA_REF:
        ini, fin = rango(f"del miercoles {coletilla} al domingo", hoy)
        check((ini, fin) == ("2026-08-12", "2026-08-16"),
              f"{dicho_el(hoy)}, «del miércoles {coletilla} al domingo» debe dar "
              f"2026-08-12 → 2026-08-16 y ha dado {ini} → {fin}")

# Decir «de esta semana» y no decir nada NO pueden dar siempre lo mismo: el
# lunes «del miércoles al domingo» y «del miércoles de esta semana al domingo»
# coinciden, pero el jueves ya no, y ahí es donde se veía que la coletilla se
# estaba tirando.
JUEVES = SEMANA_REF[3]
check(rango("del miercoles de esta semana al domingo", JUEVES) == ("2026-08-05", "2026-08-09"),
      "el jueves, «de esta semana» tiene que mirar hacia atrás dentro de la semana")
check(rango("del miercoles al domingo", JUEVES) == ("2026-08-12", "2026-08-16"),
      "el jueves, «del miércoles al domingo» a secas es el próximo miércoles")

# La coletilla del FIN se ancla a HOY, no al arranque: «del miércoles al domingo
# de la semana que viene» dicho un jueves es el miércoles 12 y el domingo 16,
# que son la misma semana; anclarla al arranque la mandaría al 23.
for hoy in SEMANA_REF:
    ini, fin = rango("del miercoles al domingo de la semana que viene", hoy)
    check(fin == "2026-08-16",
          f"{dicho_el(hoy)}, «hasta el domingo de la semana que viene» es el "
          f"2026-08-16 y ha dado {fin}")
    check(ini is not None and fin >= ini,
          f"{dicho_el(hoy)}, la coletilla del fin ha invertido el rango: {ini} → {fin}")

# Coletilla que TIRA HACIA ATRÁS: «del domingo al lunes de esta semana». El
# lunes anclado cae antes del domingo, así que el rango quedaría del revés. No
# se emite invertido: se avanza en semanas enteras, que respeta el día dicho.
for hoy in SEMANA_REF:
    ini, fin = rango("del domingo al lunes de esta semana", hoy)
    check(bool(ini) and bool(fin) and fin >= ini,
          f"{dicho_el(hoy)}, «del domingo al lunes de esta semana» sale del revés: "
          f"{ini} → {fin}")


# ═══════════ 5) los números siguen mirando hacia adelante ═══════════
print("== 5) «del 5 al 9» y «del 5 al 9 de agosto» ==")

# Un rango de números no depende del día de la semana, pero sí de si esos días
# ya han pasado: el 6 de agosto, «del 5 al 9» es el 5 de septiembre.
for hoy in SEMANA_REF:
    ini, fin = rango("del 5 al 9", hoy)
    if check(bool(ini) and bool(fin), f"{dicho_el(hoy)}, «del 5 al 9» no saca rango"):
        d_ini, d_fin = dt.date.fromisoformat(ini), dt.date.fromisoformat(fin)
        check((d_ini.day, d_fin.day) == (5, 9),
              f"{dicho_el(hoy)}, «del 5 al 9» no son los días 5 y 9: {ini} → {fin}")
        check((d_fin - d_ini).days == 4,
              f"{dicho_el(hoy)}, del 5 al 9 son cinco días: {ini} → {fin}")
        check(d_ini >= hoy, f"{dicho_el(hoy)}, «del 5 al 9» arranca en el pasado: {ini}")

# Con el mes dicho a mano NO se comprueba el AÑO a propósito: qué significa
# «del 5 al 9 de agosto» dicho el 6 de agosto (¿este agosto, que ya empezó, o el
# del año que viene?) es una decisión aparte, sin evidencia de qué quiso decir el
# operador, y este arreglo no entra ahí. Lo que sí se exige es coherencia.
for hoy in SEMANA_REF:
    ini, fin = rango("del 5 al 9 de agosto", hoy)
    if check(bool(ini) and bool(fin),
             f"{dicho_el(hoy)}, «del 5 al 9 de agosto» no saca rango"):
        d_ini, d_fin = dt.date.fromisoformat(ini), dt.date.fromisoformat(fin)
        check((d_ini.month, d_ini.day, d_fin.month, d_fin.day) == (8, 5, 8, 9),
              f"{dicho_el(hoy)}, «del 5 al 9 de agosto» no son el 5 y el 9 de "
              f"agosto: {ini} → {fin}")
        check((d_fin - d_ini).days == 4,
              f"{dicho_el(hoy)}, del 5 al 9 son cinco días: {ini} → {fin}")

# «hoy» y «mañana» como extremos siguen siendo hoy y mañana.
for hoy in SEMANA_REF:
    ini, fin = rango("del hoy al domingo", hoy)
    check(ini == hoy.isoformat(),
          f"{dicho_el(hoy)}, «hoy» como arranque de rango ha dado {ini}")
    ini, fin = rango("desde mañana hasta el domingo", hoy)
    check(ini == (hoy + dt.timedelta(days=1)).isoformat(),
          f"{dicho_el(hoy)}, «mañana» como arranque de rango ha dado {ini}")
    check(fin is not None and fin >= (ini or ""),
          f"{dicho_el(hoy)}, «desde mañana hasta el domingo» sale del revés: {ini} → {fin}")


# ═══════════ 6) la FECHA SUELTA no se toca ═══════════
print("== 6) una fecha suelta conserva su significado de siempre ==")

# «para el miércoles» dicho un miércoles es genuinamente ambiguo (¿hoy o dentro
# de una semana?). Ahí no hay evidencia de qué quiso decir el operador, así que
# el arreglo NO entra: se queda la regla de siempre, la próxima vez que caiga.
# Este bloque existe para que el arreglo del rango no se cuele en el camino de
# la fecha suelta sin que nadie se dé cuenta.
for hoy in SEMANA_REF:
    nombre = NOMBRES[hoy.weekday()]
    with hoy_es(hoy):
        _t, due = TB._extract_due(f"terminar el informe para el {nombre}")
    check(due == (hoy + dt.timedelta(days=7)).isoformat(),
          f"{dicho_el(hoy)}, «para el {nombre}» sigue siendo dentro de una semana "
          f"({(hoy + dt.timedelta(days=7)).isoformat()}) y ha dado {due}")

for hoy in SEMANA_REF:
    with hoy_es(hoy):
        _t, due = TB._extract_due("mentoría el jueves a las 18")
    esperado = (hoy + dt.timedelta(days=(3 - hoy.weekday()) % 7 or 7)).isoformat()
    check(due == esperado,
          f"{dicho_el(hoy)}, «la mentoría el jueves» debería ser {esperado} y ha "
          f"dado {due}")


print(f"\n{'#' * 54}\ntest_rangos_semana: {_pass} OK, {len(_fail)} fallos")
if _fail:
    for f in _fail[:25]:
        print("  - " + f)
    if len(_fail) > 25:
        print(f"  … y {len(_fail) - 25} más")
sys.exit(1 if _fail else 0)
