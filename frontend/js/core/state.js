/* ==========================================================
   nexus — estado compartido del HUD.
   Un solo objeto, importado por referencia: quien lo muta lo muta
   para todos. No se reasigna nunca (por eso es const).
   ========================================================== */

/**
 * Lo que el HUD sabe del backend en cada momento.
 *  status  — /api/status (motores, memoria, métricas)
 *  skills  — catálogo cargado por skills_loader
 *  config  — /api/config (ajustes del usuario)
 *  board   — tablero kanban
 *  logs    — últimas 200 líneas del monitor
 *  chat    — conversación de la sesión
 *  llm     — estado REAL del cerebro (probado, no solo configurado)
 */
export const state = {
  status: null,
  skills: [],
  config: {},
  board: null,
  logs: [],
  chat: [],
  graph: null,
  metrics: {},
  llm: {},
  llmCatalog: null,
};
