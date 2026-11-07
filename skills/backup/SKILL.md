# Skill: Backup 🛟 (copias de seguridad de tus datos)

Lo importante de nexus vive en `data/`: memoria en grafo, tablero de tareas,
contactos, vigilancias, facturas e informes. Este minion lo protege.

## Qué hace y con qué frases se dispara

- **Copia diaria automática** (la dispara el scheduler, no hace falta pedirla):
  `data/backups/nexus-data-AAAAMMDD.zip`, rotando — se guardan las últimas 7.
- «haz una copia de seguridad» · «hazme un backup» · «backup ahora» ·
  «genera una copia de seguridad» → copia inmediata; responde con el número
  real de archivos y los MB reales del zip.
- «qué copias de seguridad hay» · «mis backups» · «muéstrame los backups» ·
  «lista las copias de seguridad» → los zips que hay, con tamaño y fecha.
- «archiva los bak» · «limpia los bak» · «recoge los backups manuales» →
  mete los `*.bak_vXX` sueltos del proyecto en un zip y borra los originales.
  **Enseña primero la lista y pide un «sí» explícito**; solo borra si el zip se
  verifica (integridad + tamaño de cada archivo).
- «restaura la copia de seguridad» · «recupera el backup» → te explica los
  pasos para volver atrás y lista las copias disponibles.

## Qué necesita configurado

- Nada. Solo espacio en disco en `data/backups/`.

## Qué NO hace

- **Restaura, pero nunca encima de tus datos.** «restaura la copia de seguridad»
  te enseña ANTES qué lleva el zip (contenido, fecha, si está truncado o si el
  manifiesto no cuadra), te pide un «sí» y extrae en una carpeta NUEVA
  (`restaurado-…` de usar y tirar). Tu `data/` actual, tu `config/` y los zips no
  se tocan: sobrescribir la memoria, el tablero y la agenda con nexus corriendo
  encima no tiene vuelta atrás, así que para usar la restauración hay que cerrar
  nexus y renombrar carpetas a mano. Un zip con entradas `..` o absolutas, o con un
  archivo que no es backup de nexus, se rechaza entero sin extraer nada.
- **No borra .bak sin confirmación.** Ni sin haber verificado antes el zip.
- No borra copias diarias fuera de la rotación de 7, y nunca toca los
  `baks-*.zip` (esos no rotan).
- No mete en el zip: `data/backups` (no se anida), el perfil de Chrome
  (`data/chrome_nexus`) ni archivos de más de 50 MB.
- No sube nada a la nube: todo se queda en tu disco.
