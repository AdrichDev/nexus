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

- **No restaura nada por su cuenta.** Restaurar sobrescribiría tu memoria, tu
  tablero y tu agenda con nexus corriendo encima, y no tiene vuelta atrás. La
  skill da las instrucciones (cerrar nexus, renombrar `data/` a `data_viejo/`,
  descomprimir el zip) y se queda ahí.
- **No borra .bak sin confirmación.** Ni sin haber verificado antes el zip.
- No borra copias diarias fuera de la rotación de 7, y nunca toca los
  `baks-*.zip` (esos no rotan).
- No mete en el zip: `data/backups` (no se anida), el perfil de Chrome
  (`data/chrome_nexus`) ni archivos de más de 50 MB.
- No sube nada a la nube: todo se queda en tu disco.
