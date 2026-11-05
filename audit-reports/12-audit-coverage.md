# 12 — Cobertura, método y limitaciones

## 1. Alcance

- **Repositorio**: `D:/Adrian/22. Proyectos/nexus/nexus`.
- **Rama**: `fix/youtube-verification` @ `908924b`. Se hicieron búsquedas en el historial de todas las ramas locales y remotas.
- **Incluido**:
  - `backend/` (56 archivos, unas 21.000 líneas);
  - `skills/` (30 skills);
  - `frontend/`, `movil/`, `config/` (ejemplos), `installer/` y `scripts/`;
  - `.github/`, `requirements*` y `.gitignore`;
  - `tests/`, a nivel de inventario.
- **Excluido**:
  - `knowledge/` (390 archivos de terceros, no ejecutables);
  - `openspec/` y `odd/` (artefactos de proceso);
  - `data/`, `.env`, `config/secrets.json` y tokens: no se leyeron, por privacidad;
  - servicios externos (n8n, Telegram, Google, GitHub) y la aplicación en ejecución.

## 2. Método

| Fase | Quién | Qué |
|------|-------|-----|
| Inventario | Orquestador | `git ls-files`, recuentos, README, CLAUDE.md, auditoría previa `AUDIT_2026-09-30.md` |
| Mapeo de superficie HTTP/WS/auth/móvil | Subagente explorador 1 (solo lectura) | `app.py`, `desktop.py`, `remote.py`, `telegram_bridge.py`, `net.py`, `permissions.py`, `confirm.py`, `publicvoice.py`, frontend JS y `movil/` |
| Mapeo de skills | Subagente explorador 2 (el primer intento falló por *rate limit*; se relanzó una vez) | `skills/*`, `skills_loader`, `files_io`, `app_index`, `websearch`, `hardware` |
| Mapeo de IA/LLM/RAG | Subagente explorador 3 | `llm*.py`, `brain.py`, `rag.py`, `memory.py`, `opmem`, `reglas`, `aprendizaje`, `selflearn`, `purga`, `engram_bridge` y skills de IA |
| Secretos, datos, DevSecOps, tests | Subagente explorador 4 | `secretos`, `config`, `audit`, `events`, `jobs`, `scheduler`, `board`, `backup`, CI, instalador y tests |
| Verificación directa | Orquestador | Lecturas puntuales de `app.py:110-310, 1088-1094, 1581-1592`, `telegram_bridge.py:85-95`, `llm.py:640-690, 510-520, 740-748`, `google_workspace/skill.py:2651-2667`, `permissions.py:25-50`, `config.py:134`, `dom.js:10-20`, `llm_runtime.py` y el JSON de n8n |
| Contraste independiente | Subagente verificador (`gentle-ai-verify`) | 10 candidatos Alta/Media. Confirmó 10 de 10 con ajustes de severidad y refutó la travesía de `/api/note` |

## 3. Herramientas ejecutadas (todas locales y sin efectos)

| Herramienta | Resultado |
|-------------|-----------|
| `git ls-files`, `git log --all --diff-filter=A --name-only` | Sin archivos sensibles rastreados ni añadidos en el historial |
| `git log --all -p` con patrones de secretos (solo recuentos y prefijos redactados) | 16 coincidencias, todas en fixtures de test, en el escáner, en documentación de terceros o en marcadores |
| `git log -S` del literal de la contraseña histórica | Solo en `revisar_antes_de_subir.py` |
| Prueba en memoria con FastAPI `TestClient` (aplicación mínima, **sin importar el backend**) | FastAPI 0.139.2: un POST sin `Content-Type` o con `text/plain` a un cuerpo Pydantic → 422. El CSRF simple queda descartado |
| Versiones del `.venv` | fastapi 0.139.2, starlette 1.3.1, uvicorn 0.51.0 |
| `git check-ignore` | `.pi/` ignorado; `audit-reports/` no ignorado |

**No se ejecutaron**:

- `pip-audit` / Trivy (requieren red; existen en CI);
- la suite de tests (unos 11 min, puede tocar `data/`);
- SAST (Bandit/Semgrep, no instalados);
- pruebas dinámicas contra la aplicación;
- pruebas en navegador o en dispositivo Android.

## 4. Limitaciones

- La mayor parte del detalle de skills, IA y DevSecOps procede de **subagentes de solo lectura**. Los hallazgos Alta y Media se contrastaron de forma independiente. Los Baja e Informativos, en su mayoría, **no**, y llevan su estado en `03`.
- Los números de línea son aproximados (`~`) cuando proceden de subagentes y el archivo es grande. Hay que verificarlos antes de editar.
- No se verificó la explotabilidad en navegadores reales (SEC-03) ni en la red (SEC-08).
- No se revisaron los servicios externos (configuración de n8n, Hermes, cuenta de Google, GitHub).
- Este informe **no es una certificación de seguridad**.

## 5. Archivos revisados (directamente o por subagentes)

`backend/app.py`, `backend/desktop.py`, `backend/core/aplicacion/{brain,aprendizaje,background,jobs,scheduler,skills_loader,voice_cycle(parcial),hotkey(inventario),wake(inventario)}.py`, `backend/core/comun/{audit,config,confirm,events,net,permissions,procedencia,publicvoice,secretos}.py`, `backend/core/dominio/{board,contentos,correcciones,ingesta,memory,opmem,purga,rag,reglas,selflearn,profile,review,briefing}.py`, `backend/core/infraestructura/{app_index,engram_bridge,files_io,hardware,llm,llm_runtime,remote,spotify,stt,telegram_bridge,tts,websearch,youtube}.py`, `skills/*/skill.py` (30), `frontend/js/**`, `frontend/{index,mobile,setup}.html`, `frontend/sw.js`, `movil/{AndroidManifest.xml,MainActivity.java,assets/scan.html}`, `config/{settings.example,mcp_servers.example,n8n_flujo_ejemplo,n8n_informe_diario,umbrales}.json`, `.github/workflows/security-ci.yml`, `requirements*.txt`, `installer/*`, `run.bat`, `SUBIR_A_GITHUB.bat`, `scripts/revisar_antes_de_subir.py`, `.claude/settings.json`, `.gitignore`, `.env.example` (solo patrones), `tests/` (inventario), `README.md`, `CLAUDE.md`, `AUDIT_2026-09-30.md`.

## 6. Integridad de la auditoría

- No se modificó ningún archivo del proyecto. Lo único creado es la carpeta `audit-reports/`.
- No se mostraron secretos: los prefijos de los patrones están truncados y las contraseñas, redactadas.
- No se hizo ninguna llamada de red a servicios del sistema auditado.
