# Skill: Archivos

Minion de gestión de archivos. Capacidades:

- **Explorar**: "explora la carpeta <ruta>" / "qué hay en <ruta>"
- **Buscar**: "busca archivos <patrón> en <ruta>"
- **Leer**: "lee el archivo <ruta>" (muestra las primeras líneas)
- **Resumir**: "resume el documento <ruta>" (usa el LLM configurado)
- **Analizar código**: "analiza el código <ruta>" (métricas + resumen IA)
- **Papelera**: "manda a la papelera <ruta>" → pide confirmación
  ("confirmo papelera") y usa send2trash (recuperable, nunca borra directo)
