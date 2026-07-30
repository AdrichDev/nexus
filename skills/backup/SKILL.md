# Skill: Backup 🛟 (copias de seguridad de tus datos)

Lo importante de nexus vive en `data/`: memoria en grafo, tablero de tareas,
contactos, vigilancias, facturas e informes. Este minion lo protege:

- **Copia diaria automática** (la dispara el scheduler): `data/backups/`
  `nexus-data-AAAAMMDD.zip`, rotando — se guardan las últimas 7.
- «haz una copia de seguridad» / «backup ahora» → copia inmediata.
- «qué copias de seguridad hay» → lista con tamaño y fecha.
- «archiva los bak» → recoge los backups manuales `*.bak_vXX` desperdigados por
  el proyecto en un zip y borra los sueltos, SOLO tras verificar el zip
  (integridad + tamaños). Todo recuperable del archivo.

Notas: excluye `data/backups` (no se anida) y el perfil de Chrome
(`data/chrome_nexus`); archivos de más de 50 MB no entran en el zip diario.
