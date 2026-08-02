# nexus — guía para el agente

Asistente de escritorio (estilo JARVIS): FastAPI + uvicorn detrás de una ventana
nativa pywebview. Todo corre en local, en el equipo de Adrian.

- **Entrada real**: `backend/desktop.py` → levanta uvicorn y abre la ventana.
- **App ASGI**: `backend.app:app` (por si la quieres sin ventana).
- **Puerto**: 127.0.0.1:8177, fijo.
- **Entorno**: `.venv` en la raíz. **Python 3.12** (3.13+ rompe faster-whisper y pythonnet).

## Arrancar

```bat
run.bat
```

Es lo normal y lo que hay que usar por defecto. Además de arrancar, `run.bat`:
repara el venv si está con Python 3.13+, reinstala pydantic/cffi si se han roto,
copia `.env` y `config/settings.json` desde los `.example` si faltan, y **mata el
proceso que esté escuchando en 8177**. Ese último paso importa: si queda una
instancia colgada, la nueva revienta con `[Errno 10048]` o —peor— arranca con el
código viejo y parece que tus cambios no han hecho nada.

Desde una sesión del agente, en segundo plano y sin bloquear:

```bat
cmd /c start "" run.bat
```

Sin ventana de escritorio (solo la API, útil para probar endpoints):

```bat
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8177
```

Si el puerto se queda pillado sin pasar por `run.bat`:

```bat
for /f "tokens=5" %p in ('netstat -ano ^| findstr ":8177 " ^| findstr LISTENING') do taskkill /F /PID %p
```

**Tras tocar una skill hay que reiniciar**: `skills_loader` lee las carpetas al
arrancar. Editar un `skill.py` con nexus abierto no cambia nada.

## Probar

```bat
.venv\Scripts\python.exe tests\run_all.py      REM suite completa, tiene que salir TODO VERDE
.venv\Scripts\python.exe tests\test_nucleo.py  REM una suelta
.venv\Scripts\python.exe tests\e2e\run_e2e.py  REM interfaz real (necesita Playwright)
```

Toda suite nueva se registra en la lista de `tests/run_all.py` o no la ejecuta nadie.

**Siempre con `.venv\Scripts\python.exe`, nunca con `python` a secas.** El Python
del sistema es 3.14 y deja caché `__pycache__` compilada con un intérprete que
este proyecto no soporta (3.13+ rompe faster-whisper y pythonnet).

Playwright, si hace falta para la e2e (una sola vez, ~130 MB):

```bat
.venv\Scripts\python.exe -m pip install playwright
.venv\Scripts\python.exe -m playwright install chromium
```

## Subir a GitHub

```bat
SUBIR_A_GITHUB.bat
```

Llama a `scripts/revisar_antes_de_subir.py`, que audita el índice de git en busca
de secretos y **aborta** si encuentra uno. No hagas `git push` saltándotelo.

## Dónde vive cada cosa en la raíz

En la raíz solo se queda lo que exige el sistema (`.gitignore`), la convención
(`README.md`, `requirements*.txt`), la herramienta (`CLAUDE.md`) o el doble clic
del usuario (`run.bat`, `INSTALAR_nexus.bat`, `SUBIR_A_GITHUB.bat`). El resto:

- `installer/` — empaquetado y arte del instalador: `build_exe.bat`,
  `build_installer.bat`, `nexus.spec`, `nexus_installer.nsi`, `.ico` y `.bmp`.
  Los dos `.bat` hacen `cd /d "%~dp0.."`: **trabajan desde la raíz**, porque de
  ahí cuelgan `.venv`, `frontend`, `skills` y ahí tiene que salir `dist\`.
- `scripts/` — utilidades que no se tocan a diario: arranque por palmadas
  (`nexus_wake.*`, `instalar_arranque_voz.bat`, `quitar_arranque_voz.bat`),
  `ABRIR_PUERTO_MOVIL.bat` y `revisar_antes_de_subir.py`. Mismo criterio: su
  raíz de trabajo es la del proyecto, un nivel por encima.
- `assets/` — imágenes del producto (`logo.png`). **No confundir con
  `frontend/logo.png`**, que es otro archivo distinto y es el que sirve el HUD
  en `/static/logo.png`.
- `docs/` — documentación (`SPECS*.md`, `MOBILE.md`, `PETICIONES_ANALISIS.md`).

## Cómo se enrutan las órdenes

`backend/core/skills_loader.py`: recorre las skills **por orden alfabético de
carpeta** y, dentro de cada una, los intents **en el orden en que están escritos
en el dict**. Gana la PRIMERA regex que case. Consecuencias:

- Un patrón amplio puesto arriba se traga a los de abajo. Los amplios van al final.
- Añadir una skill cuya carpeta empiece por «a» la pone por delante de casi todo.
- Si no casa ninguna regex, la frase cae al planificador del cerebro
  (`backend/core/brain.py`), que elige skill+intent con el LLM. **Ahí es donde se
  inventa cosas.** Cada vez que una frase normal acaba en el planificador, es un bug.

## Reglas que han costado dinero

- **No se inventan cifras ni descripciones.** La regla está al final del prompt
  en `backend/core/llm.py` (`REGLA INVIOLABLE` + `TAMPOCO TE INVENTAS LO QUE ERES`).
  Núcleo IA, Content OS, Reels, Tablero, Engram y Hermes son secciones de ESTA
  aplicación, no productos de terceros.
- **Preguntas sobre la propia configuración se leen, no se razonan.** Ver
  `skills/nucleo/skill.py`: qué modelo hay puesto sale de `settings`, no del LLM.
- **Prueba con las frases del usuario, no con las tuyas.** El patrón de fallo que
  más se repite: escribir un regex, probarlo con la frase que se te ocurrió a ti,
  y que el usuario diga la misma cosa de otra manera. `tests/test_frases_reales.py`
  guarda frases literales suyas; añade las nuevas ahí.
- **UTF-8 en todo.** El código y los mensajes van en español con tildes. Los `.bat`
  van en ASCII sin tildes (problemas de codepage en cmd).
- **Umbrales y palabras clave, en `config/umbrales.json`**, nunca a fuego en el código.
- **Nada de scraping** de terceros ni de datos de sus audiencias. Instagram se
  consulta por la Graph API (`business_discovery`) y con lo que aporte el usuario.
- **Solo lectura por defecto.** Borrar cualquier cosa exige confirmación explícita
  del usuario (ver el incidente del tablero en `skills/tasks_board/skill.py`).

## Configuración y secretos

`config/settings.json` (ajustes) y `config/secrets.json` (claves, cifradas) están
en `.gitignore` y **no se tocan sin permiso**. Sus plantillas son los `.example`.
`config/docker-compose.yml` lo genera el propio nexus para Postgres+pgvector en
127.0.0.1:5433; el compose se busca desde `skills/autoprovision/skill.py`.
