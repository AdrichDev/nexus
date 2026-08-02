# 🧾 Facturación (minion facturador)

«hazle una factura a <cliente> por el servicio tal de 300 euros» → nexus
delega en este minion, que genera un HTML imprimible con numeración automática,
lo guarda en `data/invoices/` y lo registra en la base (tabla `invoices`) y en
la memoria diaria.

## Órdenes de ejemplo

- «hazle una factura a <cliente> por el servicio de diseño de 350 euros»
- «genérame una factura para <cliente> por la web de 1200 euros»
- «factúrale a <cliente> por la mentoría de 90 euros»
- «emite una factura a la empresa <cliente> por consultoría de 500 euros»
- «haz una factura al cliente <cliente> por el mantenimiento de 80 euros»
- «ver facturas» / «muéstrame las últimas facturas» / «qué facturas tengo»

Formato que entiende: cliente tras «a/al/para», concepto tras «por», importe con
«de <número> euros» (o €/eur).

## Qué NO hace

- **No inventa el importe**: sin cifra no emite nada, la pregunta.
- **No pone datos fiscales**: la factura sale sin NIF, sin dirección, sin IVA y
  sin retención. Es un borrador imprimible, no un documento válido para Hacienda.
- No la envía por email (el SMTP no está conectado) ni la cobra.
- No borra ni rectifica facturas ya emitidas.
- Solo reacciona a frases con la palabra «factura(s)».

## Notas técnicas

- **Numeración**: la asigna Postgres (`invoices`); si la base está offline,
  cae a una serie local `WBK-<año>-LOCAL-<hora>` y te lo dice.
- **Salida**: HTML autocontenido en `data/invoices/<número>.html`, listo para
  imprimir a PDF o adjuntar.
- **Email**: no hay envío. Cuando se configure SMTP en ⚙ podrá mandarla; hoy el
  HTML queda en disco para que lo adjuntes tú.
- Crear tareas desde correos, eventos o documentos es de otras skills
  (google_workspace, tablero, files).
