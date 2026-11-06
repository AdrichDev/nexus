"""
nexus — escritura ATÓMICA de los almacenes JSON de runtime.

Un JSON de estado (el tablero, el panel de multitarea, Content OS, la
proactividad, la configuración) se escribe a un `.tmp` en la MISMA carpeta y se
publica con `os.replace`, que es indivisible. Si nexus muere a mitad —o el disco
se llena, o el archivo crece— el archivo bueno sigue entero: o está el de antes,
o está el nuevo, nunca medio.

Por qué esto es un módulo y no una función en cada sitio. `config.py` ya lo
hacía así desde el incidente de `settings.json`, pero los demás almacenes
escribían con `write_text()` a pelo (hallazgo ARQ-05 de la auditoría del
30/07/2026, roadmap P2-9): un corte entre el `open()` y el último byte dejaba
`data/board.json` o `data/jobs.json` truncados, la carga siguiente devolvía su
valor vacío y el guardado siguiente sobrescribía lo poco que quedaba. Copiar el
`_write_json_atomic` en cada módulo habría dejado cinco versiones del mismo bug
latente, así que vive aquí —en la capa común, la única que todos pueden
importar— y todos escriben por aquí. `config._write_json_atomic` sigue existiendo
porque `dominio/reglas.py` lo llama, pero solo delega en esta función.

El `.bak` NO es para todos: se pide con `respaldo=True` y solo lo usa quien
después sabe leerlo (`config._read_json_safe` recurre a él cuando el principal
está truncado). En los demás almacenes un `.bak` sería un archivo muerto que
nadie lee y que además conserva en disco, una escritura más, lo que el operador
acaba de borrar.

Sin candados a propósito: nexus es UN proceso asyncio y esto es una escritura
síncrona, así que dos corrutinas no pueden solaparse entre el `.tmp` y el
`os.replace`. El candado haría falta el día que dos hilos (o dos procesos)
escriban el mismo almacén, y ese día hay que traerlo con su prueba.

`tests/unit/core/test_escrituras_atomicas.py` comprueba, almacén por almacén,
que una escritura interrumpida deja intacto el archivo anterior, que el formato
en disco no cambia y que nadie vuelve a escribir un JSON de runtime con
`write_text()`.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path


def _respalda(path: Path) -> None:
    """Copia la versión actual a `.bak` SOLO si es JSON válido.

    Respaldar un archivo truncado no arregla nada y además destruye el último
    `.bak` bueno que hubiera, que es justo el que hace falta para recuperarse.
    Un fallo aquí nunca impide guardar: el `.bak` es una red, no un requisito.
    """
    try:
        if path.exists():
            json.loads(path.read_text(encoding="utf-8"))      # valida la versión previa
            shutil.copy2(path, path.with_name(path.name + ".bak"))
    except Exception:                                          # noqa: BLE001
        pass                                                   # no respaldar basura


def escribir_json_atomico(path, data, *, indent: int | None = None,
                          respaldo: bool = False) -> None:
    """Guarda `data` como JSON en `path`, de forma indivisible.

    `indent` es el mismo que usaba cada almacén cuando escribía con
    `write_text(json.dumps(..., indent=N))`, así que el archivo que queda en
    disco es idéntico byte a byte y no hay nada que migrar: `board*` y `jobs` a
    1, `contentos` y `settings` a 2, `board_seq` y `proactive` sin indentar.
    `ensure_ascii=False` siempre, como todos ellos: los acentos del operador se
    leen tal cual en el archivo.

    Si la escritura falla, el `.tmp` se borra donde se creó y la excepción sube
    tal cual: el archivo anterior queda intacto y quien llama decide (algunos
    almacenes ya se tragaban el error antes y lo siguen haciendo).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if respaldo:
        _respalda(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)                                  # indivisible
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)                        # ni basura ni JSON a medias
        except OSError:
            pass
        raise
