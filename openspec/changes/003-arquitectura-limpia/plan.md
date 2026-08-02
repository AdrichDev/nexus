# Plan — arquitectura limpia y escalable

- **Cambio**: `003-arquitectura-limpia`
- **Fecha**: 2026-08-02
- **Estado**: en ejecución, fase 0

## El problema, medido

| Qué | Medida | Por qué duele |
| --- | --- | --- |
| `backend/core/` | 43 ficheros, **14.981 líneas**, plano | Cuatro capas distintas en la misma bolsa |
| `backend/` | Solo `core/` y `app.py` | No hay capas que separar responsabilidades |
| `frontend/js/command.js` | **3.624 líneas** | Todas las vistas, modales y gráficos en un fichero |
| Raíz del repo | **23 ficheros sueltos** | `.bat`, `.md`, `.png`, `.bmp`, `.nsi`, `.spec`, `.py` mezclados |
| Skills | 32 carpetas, 13.004 líneas | `google_workspace` 2.168, `domotica` 1.755 |

Lo que hoy vive junto en `core/`, y no debería:

- **Dominio** (reglas del negocio): `brain`, `board`, `purga`, `contentos`, `rag`, `memory`, `selflearn`
- **Infraestructura** (habla con el mundo): `remote`, `net`, `llm`, `tts`, `stt`, `files_io`, `engram_bridge`
- **Aplicación** (orquesta): `skills_loader`, `scheduler`, `background`, `jobs`, `events`
- **Transversal**: `config`, `audit`, `permissions`, `confirm`, `procedencia`

## La regla que gobierna todo esto

> **Nada de big-bang.** Hoy hay 251 pruebas y 9 flujos e2e en verde. Una
> reorganización masiva rompe todos los imports a la vez y, cuando algo falla,
> es imposible saber si es por el movimiento o por otra cosa.

Cada paso deja `run_all.py` en **TODO VERDE** antes de pasar al siguiente. Si un
paso pone algo en rojo, se revierte **ese paso**, no la fase entera.

## Fases, en orden

### Fase 0 — ordenar la raíz (en curso)

Mover no es gratis: cada fichero de la raíz está referenciado en otros sitios.
Medido antes de tocar nada:

| Fichero | Referencias | Decisión |
| --- | --- | --- |
| `run.bat` | 40 | **se queda**: es la puerta de entrada diaria |
| `requirements.txt` | 37 | **se queda**: convención y lo usa `run.bat` |
| `logo.png` | 11 | se mueve a `assets/` |
| `build_exe.bat` | 8 | se mueve a `installer/` |
| `requirements-voice.txt` | 7 | **se queda**: acompaña a `requirements.txt` |
| `SUBIR_A_GITHUB.bat` | 6 | **se queda**: doble clic del usuario |
| `build_installer.bat` | 5 | se mueve a `installer/` |
| el resto (2-4 refs) | | se mueven según naturaleza |

**Criterio**: en la raíz solo se queda lo que exige el sistema (`.gitignore`), la
convención (`README.md`, `requirements*.txt`), la herramienta (`CLAUDE.md`) o el
doble clic del usuario (`run.bat`, `INSTALAR_nexus.bat`, `SUBIR_A_GITHUB.bat`).

Destinos: `installer/` (empaquetado y arte del instalador), `scripts/` (utilidades
que no se tocan a diario), `assets/` (imágenes del producto), `docs/` (ya existe).

**Cada movimiento actualiza sus referencias.** Un fichero movido cuya referencia
no se actualiza es peor que uno desordenado: falla en tiempo de ejecución.

También en esta fase: retirar los clones `Gentleman-Skills/` y
`gentleman-guardian-angel/`. Comprobado que están impolutos (0 cambios locales,
0 commits propios) y que **sus herramientas ya están instaladas** —`gga v2.10.1`
en `~/bin/` y 33 skills en `~/.agents/skills/`—, así que dentro del repo solo son
código fuente duplicado en la carpeta equivocada.

### Fase 1 — auditar las 32 skills

La de más valor, y por eso va antes que mover código. Solo en la sesión del
01/08/2026, **sin buscarlos**, aparecieron cuatro defectos reales en esta capa:

1. `content_os` respondía en el chat con cifras falsas y una conclusión
   estadística inventada.
2. `files` borraba **del disco local** cuando le decías «borra la carpeta X de
   drive», porque gana por orden alfabético.
3. `inspire` descargaba reels ajenos con yt-dlp: scraping, contra la regla del
   propio proyecto.
4. Colisiones de regex que se tragaban intents buenos (`ig_estado`,
   `ig_competencia`).

Si eso salió de refilón, una auditoría sistemática saca más. Por cada skill:
¿se activa de verdad?, ¿hace lo que promete su `SKILL.md`?, ¿colisiona con otra?,
¿falla con mensaje honesto cuando le falta una credencial? Prueba unitaria y de
regresión por cada una.

### Fase 2 — componentizar el frontend

Partir `command.js` (3.624 líneas) por vistas y extraer lo que ya se repite:
modales, tarjetas, chips de procedencia, paneles plegables. Hay reutilización
real que ganar, no es cosmética.

Restricción dura: **vanilla, sin framework ni paso de compilación**. Y el
cache-busting es manual (`?v=NN` en `index.html`, líneas 9 y 126).

### Fase 3 — estratificar el backend

Abrir `core/` en capas, moviendo **un grupo cada vez** con la suite en verde
después de cada movimiento. El orden va de lo que menos depende a lo que más,
para que cada paso sea reversible solo.

## Lo que este plan NO es

- No es reescribir lo que funciona. La churn sin motivo es coste, no mejora.
- No es borrar pruebas. Al contrario: son la red que permite mover con confianza.
- No es cambiar de tecnología ni meter un framework.
