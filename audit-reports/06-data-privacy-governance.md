# 06 — Datos, privacidad y gobernanza

> Las referencias al RGPD, la LOPDGDD y el Reglamento Europeo de IA (AI Act) son **orientativas desde el punto de vista técnico**. Su aplicabilidad y su interpretación deben validarlas profesionales jurídicos.

## 1. Datos personales tratados

| Categoría | Origen | Almacén | Sale del equipo |
|-----------|--------|---------|-----------------|
| Conversaciones (texto y voz transcrita) | Usuario | `data/interactions.jsonl`, `audit.jsonl`, `nexus.log`, historial, `jobs.json` | Sí, al LLM en la nube si está configurado o por el fallback (AI-01) |
| Correos de **terceros** (remitentes, asunto, cuerpo) | Gmail | Memoria, caché, prompts | Sí, al LLM en la nube |
| Calendario, tareas y Drive | Google | Google, tablero local | Sí, al LLM |
| Contactos y teléfono (agenda) | Móvil vinculado | `telefono` | — |
| Perfil del operador destilado | LLM | Archivo de perfil | Se inyecta en cada prompt |
| Documentos ingeridos (facturas, gastos) | Usuario | `data/memory/documentos`, pgvector, `knowledge.jsonl` | Embeddings locales por defecto; contenido al LLM al recuperarlo |
| Datos de audiencias de Instagram | Graph API | Análisis | — (política explícita de no hacer scraping, `CLAUDE.md`) |
| Credenciales de terceros | Usuario | `secrets.json` y tokens OAuth **en claro** (SEC-09) | — |
| Audio | Micrófono | Temporal (STT local) | No (faster-whisper local) |
| Texto de las respuestas | Sistema | — | Sí, si el TTS es edge-tts o ElevenLabs |

**Tratamiento de terceros**: nexus procesa datos de personas que no son el usuario: remitentes de correo, contactos, cuentas de Instagram analizadas. En un uso doméstico puede aplicar la exención de actividad personal del RGPD (art. 2.2.c). En un uso **profesional** (las facturas a clientes y los correos de proveedores del README lo sugieren), el usuario sería responsable del tratamiento, y los proveedores LLM en la nube, **encargados** que requieren un contrato (art. 28) y garantías para las transferencias internacionales (OpenAI, Anthropic y Google tienen sede en EE. UU.). **Pendiente de valoración jurídica.**

## 2. Hallazgos técnicos de privacidad

| ID | Severidad | Hallazgo | Evidencia |
|----|-----------|----------|-----------|
| PRIV-01 | Media | **Minimización**: los registros de interacciones y de auditoría guardan texto crudo sin redactar (AI-02) | `selflearn.py:61-66`, `audit.py:46-84` |
| PRIV-02 | Media | **Transferencia no prevista** a un LLM en la nube por el fallback silencioso (AI-01) | `llm.py:655-676` |
| PRIV-03 | Media | **Supresión incompleta**: la purga no cubre `data/rag/knowledge.jsonl`, los espejos de `data/memory/documentos/**`, Engram, `interactions.jsonl`, `audit.jsonl`, `webcache.json` ni los **backups zip** (7 días). Un «olvida X» no garantiza el olvido | `purga.py`, `skills/backup` |
| PRIV-04 | Baja-Media | **Backups sin cifrar** en `data/backups/` (zip diario, 7 copias) que contienen todo `data/`. Los secretos están en `config/` y no se incluyen (no verificado por completo) | `skills/backup/skill.py:30-73` |
| PRIV-05 | Baja | **Retención**: los logs rotan por tamaño (1-2 MB, una sola generación anterior), pero `interactions.jsonl`, `jobs.json` y la memoria no tienen una política de retención temporal | `audit.py:22-25`, `events.py:131-145` |
| PRIV-06 | Info | OpenRouter con `zdr:false` por defecto: el proveedor puede retener prompts aunque `data_collection: deny` impide entrenar con ellos | `config/umbrales.json` |
| PRIV-07 | Info | No hay un registro de actividades de tratamiento ni avisos en la UI de que los correos o documentos se enviarán a un proveedor externo cuando el cerebro está en la nube | — |

## 3. Controles de privacidad verificados

- Redacción de secretos antes de persistir en memoria, RAG, opmem, Engram y la ingesta (`secretos.py:18-95`, con test).
- Embeddings locales por defecto (`permitir_nube:false`).
- OpenRouter `data_collection: deny` estricto ante fallos (con test).
- Política de no hacer scraping de terceros (Instagram solo vía Graph API).
- STT local.
- `as_dict()` no expone secretos por la API.
- Purga en dos pasos con papelera, restauración y exportación antes de mover las categorías personales.
- Escáner de secretos y datos personales (MAC, IP, email, rutas) antes de subir a GitHub (`scripts/revisar_antes_de_subir.py`, 15 casos de autotest).

## 4. Reglamento Europeo de IA (orientativo)

Es un asistente personal de propósito general que usa modelos de terceros. No se identifican usos de alto riesgo del anexo III: no hay decisiones sobre empleo, crédito ni otros ámbitos regulados. Si se distribuye a terceros, aplican obligaciones de **transparencia** (art. 50): informar de que se interactúa con una IA y marcar el contenido sintético, por ejemplo la voz TTS. **Pendiente de valoración jurídica.**

## 5. Recomendaciones (en orden)

1. Corregir AI-01 (pedir consentimiento antes de usar la nube como reserva) y AI-02/PRIV-01 (aplicar `redactar` a `interactions.jsonl`, `audit.jsonl` y `distill`). Esfuerzo S. Es la mayor reducción de exposición.
2. Una «supresión completa» (`borrar_definitivo`) que recorra todos los almacenes: `knowledge.jsonl`, documentos, Engram, logs y caché. Documentar que los backups expiran a los 7 días.
3. Cifrar los backups (zip con AES y clave en DPAPI) o excluir `interactions.jsonl` y los logs.
4. Retención temporal configurable (por ejemplo, 90 días) para `interactions.jsonl`, `audit.jsonl` y `jobs.json`.
5. Mostrar en ⚙ un aviso «este cerebro envía tu contexto a <proveedor>» y una opción «solo local estricto».
