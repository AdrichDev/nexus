# 11 — Preguntas abiertas y aspectos pendientes de verificación

| # | Pregunta | Por qué importa | Cómo resolverla |
|---|----------|-----------------|-----------------|
| Q-01 | ¿Está importado y activo el flujo `n8n_flujo_ejemplo.json`? ¿Su webhook es accesible desde Internet? | Determina si SEC-01 es una exposición activa | Revisar la instancia de n8n (por el propietario) |
| Q-02 | ¿Existe `data/telegram_owner.txt` con el chat del propietario? ¿Hay un token de bot configurado? | Ventana de SEC-02 | Lo comprueba el propietario. No se leyó `data/` por privacidad |
| Q-03 | ¿Qué `Origin` y `Host` envía pywebview al cargar el HUD? | Condiciona la corrección de SEC-03 sin romper el HUD | Registrar las cabeceras en un entorno de pruebas |
| Q-04 | ¿Funciona el DNS rebinding contra `127.0.0.1:8177` en los navegadores que usa el propietario (Chrome con Local Network Access, Firefox, Edge)? | Explotabilidad real de SEC-03 | Prueba controlada con un servicio de rebinding propio y una instancia de nexus de prueba con un LLM `mock` |
| Q-05 | ¿Qué motor TTS está activo por defecto (edge-tts u otro)? | Flujo de datos a Microsoft (AI-11) | Leer `config.py` DEFAULTS `tts_engine` y la configuración real |
| Q-06 | ¿Incluye el backup zip `config/` (secretos y tokens)? | Exposición de credenciales en las copias | Revisar la lista de exclusiones de `skills/backup/skill.py` con más detalle |
| Q-07 | ¿El scheduler evita disparar dos veces los recordatorios tras un reinicio? | Duplicados o pérdidas | Leer `due_reminders()` en el dominio y hacer un test con reloj simulado |
| Q-08 | ¿Siguen presentes A2 («guardado» tras un fallo) y P8 (`get_index` bloqueante) de la auditoría anterior? | Fiabilidad | Reverificar `brain.py` y `app_index.py` |
| Q-09 | ¿Qué resultado da hoy `pip-audit` y Trivy en CI? | Dependencias vulnerables | Ver la última ejecución en GitHub Actions |
| Q-10 | ¿Hay protección de rama en `main` y revisión obligatoria? | Gobernanza | Configuración del repositorio en GitHub |
| Q-11 | ¿Se usa nexus para fines profesionales (facturas a clientes, correos de proveedores)? | Determina si aplica el RGPD como responsable o la exención doméstica | Decisión del propietario y valoración jurídica |
| Q-12 | ¿Hay acuerdos de tratamiento de datos (DPA) con OpenAI, Anthropic, Google y OpenRouter si se usan con datos de terceros? | Encargados del tratamiento y transferencias internacionales | Valoración jurídica |
| Q-13 | ¿Qué hace exactamente Hermes con lo que se le delega (navegador, código)? ¿Con qué permisos se ejecuta? | Autonomía de los agentes | Revisar la configuración de Hermes (`~/.hermes/config.yaml`), fuera del alcance de este repositorio |
| Q-14 | ¿Los servidores MCP están activados en la configuración real (`config/mcp_servers.json`)? | SEC-18 | Lo revisa el propietario |
| Q-15 | ¿Tiene `ingesta` un límite de tamaño o de número de páginas para PDF y XLSX? | DoS local o consumo | Leer `ingesta.py` y `rag.trocear*` en detalle |
| Q-16 | ¿Pasa hoy la suite completa? | Estado de calidad actual | Ejecutar `tests/run_all.py` (unos 11 min) en una copia o con autorización |
| Q-17 | ¿Deben versionarse los informes de `audit-reports/`? | Contienen rutas y detalles de ataque del sistema | Decidir: versionar, ignorar o mantener en privado |
