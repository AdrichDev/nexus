/* nexus — service worker mínimo (habilita instalación como app PWA).
   No cachea el contenido dinámico (necesita el PC vivo), solo permite que
   Android/iOS ofrezcan "Añadir a pantalla de inicio" y abrir en pantalla completa. */
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => self.clients.claim());
self.addEventListener('fetch', (e) => { /* red directa; sin caché offline */ });
