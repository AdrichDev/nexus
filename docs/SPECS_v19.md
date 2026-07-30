# SPECS v19 — asistente personal proactivo: buscador, briefing, vigilancias, informes y backup
_2026-07-24 · Cada spec incluye su criterio de aceptación y el RESULTADO de la validación
(suite completa: `python tests/run_all.py` → TODO VERDE, 563 checks; QA adversaria
independiente con modelo sonnet: 58/58; revisión de código con modelo opus: 5 hallazgos,
todos corregidos y re-validados)._

## SPEC M1 — Motor de búsqueda web serio (cimiento)
**Qué:** un solo motor central (backend/core/websearch.py) para TODO nexus: multi-fuente
(Google News RSS → DDG Lite → DDG HTML), CACHÉ con TTL (búsquedas 30 min, noticias 5 min,
páginas 1 h; RAM + data/webcache.json con escritura atómica y poda a 300 entradas) y
extracción de contenido real (article/main, titulares, párrafos y listas con sustancia).
La skill research ya NO lleva su scraping duplicado: delega en el motor.
**Criterio de aceptación:** repetir una búsqueda dentro del TTL no toca la red; el TTL
caduca; extract_text descarta script/nav/footer y capta article/h/p/li; research usa el motor.
**✔ VALIDADO:** 12 checks en test_mejoras_v19 (caché put/get/TTL/poda, extracción con
fixture, unificación) + QA sonnet: HTML adversario de 609 KB con 3000 `<p>` sin cerrar
→ 0,04 s (la revisión opus detectó backtracking cuadrático — hasta 12 s — y se
reescribió la extracción a algoritmo LINEAL con topes de 1,5 MB).

## SPEC M2 — Briefing matinal proactivo («buenos días»)
**Qué:** backend/core/briefing.py. A la hora configurada (⚙/settings: briefing_enabled,
briefing_hour "08:30", briefing_city, briefing_topics "tema1, tema2"), nexus canta el
parte ÉL SOLO por el HUD (chat + voz) y Telegram: saludo con fecha, clima (wttr.in),
tablero (vencidas/a punto/en marcha), encargos Hermes por número y titulares de tus
temas. Cada sección es a prueba de fallos (si una fuente cae, el parte sale igual).
«qué me toca hoy» (coach) ahora devuelve este parte completo + objetivos y checklists.
**Criterio:** briefing_due puro y correcto (hora, una vez/día, desactivado, hora inválida);
anti-reenvío aunque el disco no persista; scheduler lo comprueba cada ~1 min.
**✔ VALIDADO:** 9 checks (briefing_due 5 casos borde + secciones hermes con números +
integración scheduler/coach) + QA sonnet 7 casos de briefing_due incluyendo bordes exactos.

## SPEC M3 — Vigilancias: nexus trabaja mientras no miras
**Qué:** skill nueva skills/vigilancias/. «vigila la web https://…» (cambios de contenido:
huella sha256 + diff de líneas nuevas), «avísame si baja el precio de https://…» (extracción
de precio con separador de miles: 1.234,56 € / 12 345,67 EUR / $45.50), «avísame cuando haya
noticias de X» (titulares nuevos; la 1ª pasada siembra sin avisar). Numeradas (#1, #2…),
registro en data/watchers.json, barrido del scheduler cada ~5 min (respetando 10 min por
vigilancia), aviso por HUD (notificación + chat con voz) y Telegram. «mis vigilancias»,
«borra la vigilancia N».
**Criterio:** detectores puros correctos; ciclo completo con motor web simulado: siembra
sin avisar → cambio web/bajada de precio/titular nuevo avisan con su número; sin robos
de enrutado.
**✔ VALIDADO:** 17 checks (precios con miles — bug real cazado por el test y corregido —,
digest, diff, ciclo completo, borrado por número) + QA sonnet: ciclo + 3ª pasada sin
cambios no repite avisos.

## SPEC M5 — Informes con formato de verdad + histórico
**Qué:** los informes de research se exportan también a WORD (.docx: encabezados,
viñetas, cursivas — python-docx, ya en el instalador) junto al .md; e histórico
consultable: «mis informes» (lista con fecha y si tienen Word), «abre el informe de X»
(reapertura por nombre parcial, prefiere el .docx).
**Criterio:** md→docx real verificable reabriendo el archivo; histórico lista y reabre;
informe inexistente avisa claro.
**✔ VALIDADO:** 8 checks + QA sonnet (estilos Heading/List Bullet verificados reabriendo
el .docx; negritas limpiadas; cursiva).

## SPEC M10 — Copias de seguridad automáticas
**Qué:** skill nueva skills/backup/. Copia DIARIA automática de data/ (memoria, tablero,
contactos, vigilancias…) en data/backups/nexus-data-AAAAMMDD.zip con rotación de 7,
disparada por el scheduler (en hilo: no congela el HUD). Bajo orden: «haz una copia de
seguridad», «qué copias de seguridad hay». Y «archiva los bak»: recoge los *.bak_vXX
sueltos del proyecto en un zip y borra los originales SOLO tras verificar integridad y
tamaños (regex anclada: no toca archivos que solo contengan «.bak» en medio del nombre).
**Criterio:** zip correcto excluyendo data/backups y el perfil de Chrome; rotación exacta
a 7; archivado verificado que no toca archivos trampa.
**✔ VALIDADO:** 9 checks + QA sonnet (archivo trampa «receta.baking.md» intacto en dos
ubicaciones; solo 2 entradas en el zip; borrado únicamente tras verificar).

## Revisión y endurecimiento (opus)
Hallazgos corregidos: (1) backtracking cuadrático en extract_text → algoritmo lineal +
topes; (2) zip del backup en el event loop → asyncio.to_thread; (3) descarga sin tope en
fetch_page → 1,5 MB + extracción en hilo; (4) caché releída del disco en cada acceso y
escritura no atómica → RAM + tmp+os.replace; (5) glob de .bak demasiado amplio → regex
anclada. Mitigaciones extra: anti-reenvío del briefing en RAM, «vistos» de noticias con
orden estable, tareas del scheduler desfasadas del arranque (%12==3, %60==24, %120==48).

---
### Pendientes (specs sin implementar aún — por diseño, no se escriben a medias)
- **M4 Orquestación multi-paso** (cadena investiga→informe→tareas→aviso): requiere tocar
  el planificador del cerebro (protegido por tests); hacer en sesión propia.
- **M6 Revisión semanal del tablero** (domingo: hecho/atascado/replan + sync Google Tasks).
- **M7 Perfil del operador + consolidación nocturna de memoria.**
- **M8 Contexto multi-turno** («llama al segundo») en brain.py.
- **M9 Panel «HOY» en el HUD** (frontend: convertir «▷ Informe del día» en dashboard vivo
  alimentado por /api — puede apoyarse en briefing.build_briefing).
