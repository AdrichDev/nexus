# Nexus — Experiencia Web 3D

Rediseño 3D scroll-driven de nexus.com. Tema runner/deportivo (sin estética futurista), WebGL real, 100% herramientas gratuitas, sin build.

---

## 1) Reporte de auditoría / Brand Core

Fuente: https://www.nexus.com/ (Shopify).

**Colorimetría (HEX / HSL)**

| Rol | HEX | HSL |
|---|---|---|
| Base oscura (theme-color) | `#171717` | hsl(0 0% 9%) |
| Panel | `#1f1f1f` | hsl(0 0% 12%) |
| Amarillo fluor (acento 1) | `#f5d000` | hsl(51 100% 48%) |
| Fucsia | `#e5289e` | hsl(322 78% 53%) |
| Turquesa | `#12b5a9` | hsl(176 82% 39%) |
| Coral | `#ff6a5c` | hsl(5 100% 68%) |
| Verde | `#7ac143` | hsl(94 51% 51%) |
| Pista de atletismo | `#c84b31` | hsl(10 61% 49%) |

Los acentos salen de los colorways reales de producto (Do Epic Shit, Fade, Essentials, S-miles).

**Tipografía**: Shopify genérica en origen. Equivalentes Google Fonts: **Archivo** 800/900 (display atlético, mayúsculas) + **Inter** (cuerpo). Variables y gratuitas.

**Mapeo de assets → 3D** (todo procedural, 0 descargas):

- Calcetín protagonista → TubeGeometry sobre curva Catmull-Rom (pierna→talón→puntera) + puntera esférica + remate de caña torus. Textura de punto generada en CanvasTexture (caña canalé, rayas, talón/puntera reforzados, trama de ruido).
- 5 colorways reales → mismos calcetines "corriendo" por las calles de una pista de atletismo circular (RingGeometry terracota + líneas de calle).
- Tecnología transpirable → partículas suaves de flujo de aire ascendente (turquesa claro).
- Kilómetros/comunidad → sendero de trail sinuoso (tubo terracota) con 4 banderas-hito, una por estadística real.

**Conversión**: UVP = "Cero ampollas. Cero rozaduras. Solo kilómetros." (reescritura del claim original "Sin ampollas ni rozaduras"). CTA primario "Encuentra tu Nexus →" / final "Ver todos los calcetines" (enlaza a la tienda real). Prueba social: 4.739 reseñas, 400.569 pares, 53.800 clientes, 89M km (datos publicados en la web).

**Tono y mood**: deportivo, enérgico, cercano, colorido, made-in-Spain.

## 2) Visión del rediseño

Un estudio deportivo cálido (luz key cálida + relleno frío, sin bloom ni neón): el calcetín gira despacio como producto de estudio sobre una pista de atletismo. Cada sección responde una pregunta y empuja al CTA:

1. **Hero** — *¿por qué estos calcetines?* Producto flotante con parallax de ratón; claim y CTA en overlay HTML semántico.
2. **Colecciones** — *¿cuál es el mío?* La cámara se eleva a vista aérea: 5 colorways reales corren por las calles de la pista, con "zancada" animada. Tarjetas con precios reales.
3. **Tecnología** — *¿por qué no salen ampollas?* Plano macro del tejido mientras el flujo de aire lo atraviesa.
4. **Kilómetros** — *¿puedo fiarme?* Vuelo rasante por un sendero de trail con 4 banderas = 4 estadísticas reales + reseña textual.
5. **CTA final** — *¿qué hago ahora?* Retorno al producto en plano de venta y botón a la tienda real.

Respeta `prefers-reduced-motion` (escena estática, contenido visible) y tiene fallback CSS sin WebGL.

## 3) Stack técnico

| Librería | Versión | Por qué |
|---|---|---|
| three | 0.160.0 (importmap CDN) | WebGL real; materiales PBR estándar |
| gsap + ScrollTrigger | 3.12.5 | Scrub de cámara por scroll |
| lenis | 1.1.14 | Scroll suave MIT |
| Google Fonts | Archivo + Inter | Display atlético + cuerpo legible |

Assets externos: **0 bytes** (geometría y texturas procedurales). Sin bloom (dirección de arte limpia y menor coste GPU). DPR limitado, partículas reducidas en móvil, sombras falsas por textura (sin shadow maps), dispose al descargar.

## 4) Archivos

- `index.html` — DOM semántico + importmap + guardia de arranque con diagnóstico en pantalla
- `style.css` — sistema visual Nexus (marquesina amarilla, tarjetas, stats)
- `main.js` — calcetín procedural, pista, sendero y coreografía de cámara

## 5) Cómo ejecutarlo en local

1. `cd "D:\Adrian\22. Proyectos\3A_Estudio\nexus-3d"`
2. `npx serve -l 5501 .`
3. Abrir **http://localhost:5501** (no abrir con doble clic/file://; requiere conexión para los CDN).

[A DEFINIR]: enlaces de las tarjetas a las colecciones concretas si se quiere navegación directa por producto.
