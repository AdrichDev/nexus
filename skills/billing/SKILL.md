# 🧾 Facturación (minion facturador)

Del diseño de Rubén: «hazle una factura a Ubix por el servicio tal» → nexus
delega en este minion, que genera un HTML imprimible con numeración automática,
lo guarda en `data/invoices/` y lo registra en la base (tabla `invoices`) y en
la memoria diaria.

## Órdenes de ejemplo

- «hazle una factura a Ubix por el servicio de diseño de 350 euros»
- «génerame una factura para Acme por la web de 1200 euros»
- «factúrale a Ubix por la mentoría de 90 euros»
- «emite una factura a la empresa Delta por consultoría»
- «ver facturas» / «muéstrame las últimas facturas» / «qué facturas tengo»

Formato que entiende: cliente tras «a/para», concepto tras «por», importe con
«de <número> euros» (o €/eur). Sin importe usa 100.00 € provisionales y te lo
avisa para que lo repitas con la cifra buena.

## Notas técnicas

- **Numeración**: la asigna Postgres (`invoices`); si la base está offline,
  cae a una serie local `WBK-<año>-LOCAL-<hora>` y te lo dice.
- **Salida**: HTML autocontenido en `data/invoices/<número>.html`, listo para
  imprimir a PDF o adjuntar.
- **Email**: el envío aún no está conectado — la arquitectura está lista para
  SMTP/API; cuando se configure en ⚙, nexus enviará la factura él mismo.
- Solo reacciona a frases con la palabra «factura(s)»: crear tareas desde
  correos, eventos o documentos es cosa de otras skills (google_workspace,
  tablero, files).
