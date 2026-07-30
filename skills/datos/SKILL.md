# Skill: Datos / Analítica (BDs externas + dashboards)

Conecta nexus a bases de datos externas y saca analítica estilo GA4 con
dashboards oscuros tipo Power BI (HTML + Chart.js, se abren en el navegador).

## Conectar

- "conéctate a la base de datos postgresql://user:pass@host:5432/db"
- Soporta: `postgresql://` (psycopg2), `mysql://` (pip install pymysql),
  `sqlite://C:/ruta/archivo.db`, `mongodb://` (pip install pymongo)
- "desconecta la base de datos" / "qué base de datos está conectada"

## Analizar

- "qué tablas hay" → lista tablas/colecciones
- "consulta: SELECT ..." → ejecuta SQL y muestra resultados (máx 50 filas)
- "informe analítico de la tabla <nombre>" → perfil completo: volumen,
  columnas, valores top, evolución temporal si hay fechas (estilo GA4)
- "dashboard de la tabla <nombre>" → genera un dashboard HTML oscuro con
  gráficos (barras, líneas, donut) y lo abre en el navegador
- "gráfico de <consulta SQL>" → gráfico de los resultados de esa consulta

Seguridad: solo lectura por defecto (rechaza INSERT/UPDATE/DELETE/DROP
salvo que actives "modo escritura de datos").
