# Skill: Datos / Analítica (BDs externas + dashboards)

Conecta nexus a bases de datos externas y saca analítica estilo GA4 con
dashboards oscuros tipo Power BI (HTML + Chart.js, se abren en el navegador).

## Conectar

- «conéctate a la base de datos postgresql://user:pass@host:5432/db»
- «conéctame a la bd sqlite://C:/ruta/archivo.db»
- Soporta: `postgresql://` (psycopg2), `mysql://` (pip install pymysql),
  `sqlite://C:/ruta/archivo.db`, `mongodb://` (pip install pymongo)
- «desconecta la base de datos» · «qué base de datos está conectada»

La conexión vive en memoria del proceso: al reiniciar nexus hay que rehacerla.

## Analizar

- «qué tablas hay» · «lístame las tablas» · «dame las tablas» → tablas/colecciones
- «consulta: SELECT …» → ejecuta la SQL y muestra hasta 50 filas (12 en el chat)
- «informe analítico de la tabla <nombre>» → perfil: volumen, columnas, valores
  top y evolución temporal si hay fechas
- «dashboard de la tabla <nombre>» · «panel de <tabla>» → dashboard HTML oscuro
  con gráficos, guardado en `data/reports/` y abierto en el navegador
- «gráfico de: SELECT etiqueta, valor …» → gráfico de esa consulta

## De dónde salen las cifras

- **Filas totales**: `SELECT COUNT(*)` real sobre la tabla.
- **Top / evolución / sumas por columna**: de las **primeras 200 filas**. Si la
  tabla tiene más, la etiqueta del gráfico lo dice («muestra de 200»).
- El comentario del final lo escribe el LLM **solo** con esos KPIs medidos;
  tiene prohibido añadir porcentajes o tendencias que no estén ahí.

## Qué NO hace

- **No escribe en la base de datos.** Rechaza INSERT/UPDATE/DELETE/DROP/
  TRUNCATE/ALTER/CREATE/GRANT y no hay ningún modo de escritura que activar.
- No consulta la memoria interna de nexus (pgvector): esa va por su lado.
- Los dashboards cargan Chart.js desde un CDN, así que necesitan internet para
  dibujarse; el HTML se genera igual sin conexión.
