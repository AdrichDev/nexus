# 08 — DevSecOps, cadena de suministro y testing

## 1. CI/CD

**Archivo**: `.github/workflows/security-ci.yml` (único workflow).

| Aspecto | Estado | Evidencia |
|---------|--------|-----------|
| Permisos | `contents: read`, `security-events: write` (mínimos) ✅ | `security-ci.yml:21-22` |
| Fijación de actions | `trivy-action` fijado por SHA ✅. `actions/checkout@v4` y `actions/setup-python@v5` **por etiqueta** ⚠️ | `:30-31, 44-45` |
| Escáneres | `pip-audit` (OSV) y Trivy (vulnerabilidades, secretos y misconfig), que fallan con HIGH/CRITICAL ✅ | `:34-49` |
| **Tests** | **No se ejecutan en CI** ❌ | Único workflow |
| Lint o typecheck | No ❌ | — |
| SAST | No hay Bandit ni Semgrep | — |
| SBOM | No se genera | — |
| Despliegue | No hay CD. El `.exe` y la APK se construyen en local | `installer/`, `movil/` |
| Protección de ramas | **No verificable** desde el repositorio local (requiere consultar GitHub) | — |

## 2. Dependencias

- `requirements.txt` usa solo `>=`. No hay lockfile ni hashes (el job de CI tiene comentada una referencia a `requirements.lock`). Cada instalación puede traer versiones distintas, y el `run.bat` «repara» el venv reinstalando paquetes. **Riesgo de deriva y de supply chain.**
- `playsound==1.2.2` está fijado a un paquete sin mantenimiento desde 2021 (no está deprecado formalmente). Bajo riesgo.
- `yt-dlp` cambia con mucha frecuencia; con `>=` es razonable por la funcionalidad, pero conviene fijarlo en el lock.
- La instalación automática de Engram verifica el SHA-256 ✅.
- **`pip-audit` no se ha ejecutado en esta auditoría** (requiere consultar OSV por red; se ejecuta en CI). No se dispone del resultado más reciente de CI.

**Recomendación**: `pip-compile --generate-hashes` → `requirements.lock`, instalar con `--require-hashes` en `run.bat` y en CI, y activar Dependabot o Renovate. Esfuerzo S.

## 3. Empaquetado y distribución

- PyInstaller con instalador NSIS, **sin firma de código** (`installer/nexus.spec`, `build_installer.bat`). Los usuarios verán avisos de SmartScreen y no podrán verificar la integridad. Es aceptable para uso personal; para distribuir, conviene firmar.
- La APK se firma con un keystore local, y la contraseña llega por variable de entorno (`movil/COMPILAR_APK.bat`). No hay contraseñas en el código ✅.
- `SUBIR_A_GITHUB.bat`:
  - ejecuta `git rm -r --cached . && git add -A` (consciente y documentado);
  - pasa por el escáner de secretos **con autotest previo** y aborta si detecta algo ✅;
  - no hace force-push ✅.

## 4. Secretos en el repositorio y su historial (comprobado)

- Archivos rastreados: no hay `.env`, `secrets*.json`, tokens, keystores ni `.pem` (`git ls-files`).
- Nombres sensibles añadidos alguna vez en el historial (`git log --all --diff-filter=A`): solo `secretos.py`, sus tests y documentación ✅.
- Patrones de secretos en todos los diffs añadidos de todas las ramas (`sk-`, `AKIA`, `ghp_`, `AIza`, `xox[bp]-`, `BEGIN PRIVATE KEY`, tokens de bot de Telegram y URLs `postgres://usuario:pass@`): 16 coincidencias. **Todas** están en fixtures de test (`tests/unit/core/test_secretos.py`, `test_ingesta_documentos.py`), en el escáner, en la documentación de `knowledge/` o en el **marcador** de `.env.example`. Ninguna parece una credencial real ✅. Limitación: la búsqueda es por patrones conocidos y no detecta secretos con formatos arbitrarios.
- `.claude/settings.json`: allowlist estrecha (`run.bat`, tests, pytest, uvicorn y git de solo lectura) y deniega la lectura de `secrets.json` y `.env` ✅.
- `.gitignore` es amplio ✅. `.pi/` **ya está ignorado** (corregido desde la auditoría anterior). `audit-reports/` **no** está ignorado: decidir si estos informes se versionan.

## 5. Testing

**Inventario**:

- 124 archivos en `tests/`, con unos 100 de tests unitarios por área: routing, conversación, skills, memoria, especificaciones y runtime.
- Integración HTTP: `test_acceso_remoto.py` y `test_entrega_real.py`.
- E2E con Playwright.
- Sondas herméticas en Docker sin red (arranque, persistencia y recorridos de usuario).
- `tests/run_all.py` agrega las suites y protege `settings.json`.

**No se ha ejecutado la suite en esta auditoría**: dura unos 11 minutos, puede tocar `data/` y la auditoría era de solo lectura. La auditoría anterior (2026-09-30) registró una ejecución completa en verde salvo un test que dependía del entorno (`test_purga`).

**Lo valioso**:

- Frases reales del usuario (`test_frases_reales.py`), un corpus de regresión de routing y tests de honestidad por skill.
- Test de capas.
- Tests de privacidad de OpenRouter y de redacción de secretos.
- Tests de Origin y Host en el WS (NEX-1).

**Huecos críticos** (funcionalidades sin pruebas encontradas):

| Área | Por qué importa | Prueba propuesta |
|------|-----------------|------------------|
| Middleware HTTP `remote_auth` con un Host ajeno (SEC-03) | Frontera de confianza principal | Loopback con `Host: evil:8177` → 401 |
| `/api/n8n` y política por canal (SEC-01) | Entrada no confiable | n8n con `send_email` → rechazado |
| Propietario de Telegram (SEC-02) | Toma de control | Sin código → no se registra |
| `confirm.py` | Base de todas las acciones destructivas | TTL, desarme y aislamiento por canal |
| `permissions.path_allowed` aislado | `..`, symlinks, UNC y denylist | Tabla de casos |
| `send_email` con confirmación | Envío externo | Fake de Gmail sin «sí» → no se envía |
| Fallback de proveedor LLM (AI-01) | Privacidad | Ollama caído y key presente → no hay llamada a la nube |
| `voice_cycle`, `hotkey` | Concurrencia de voz | Ya señalado por la auditoría anterior |
| Restauración del backup | Recuperación | Zip → directorio temporal → arranque hermético |
| Escritura atómica de `board.json` | Integridad | Simular un fallo a mitad de escritura |
| Inyección de prompts (ver `05` §6) | IA | Corpus adversario con un LLM fake |

**Calidad de los tests**: la auditoría anterior señaló tests basados en buscar texto en el código fuente (`"auto_backup" in open(...).read()`) y tests sensibles a la fecha. Siguen pendientes de revisar.

## 6. Recomendaciones (en orden)

1. Job de CI que ejecute `tests/run_all.py`, separando las suites lentas (purga) en un job nocturno. Esfuerzo S.
2. Lockfile con hashes. S.
3. Fijar `checkout` y `setup-python` por SHA. XS.
4. Bandit (o Semgrep con reglas de Python) en CI, en modo informativo al principio. S.
5. Los tests de frontera de la tabla anterior, junto con cada corrección de `09`.
