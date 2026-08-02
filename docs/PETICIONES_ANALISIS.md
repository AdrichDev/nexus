# Lo que he entendido que necesitas — análisis de cuentas de Instagram

Inventario de todo lo que has pedido en esta sesión, con su estado real.
Está pensado para que lo corrijas: si algo no es lo que querías, o falta algo,
táchalo o añádelo y seguimos por ahí.

Fecha: 30/07/2026

---

## 1. Tu propia cuenta — análisis de reels

### ✅ Hecho y en tu disco

| Lo que pediste | Dónde está |
|---|---|
| Métricas duras: alcance, impresiones, interacciones, me gusta, comentarios, guardados, compartidos, comentaristas únicos | Reels → Los números |
| Comentarios desglosados: los de la audiencia vs. tus propias respuestas | Reels → De dónde sale cada comentario |
| Ratios de cada métrica sobre el alcance | En cada cifra |
| Una **lectura interpretada** de cada número, no el número a secas | Junto a cada métrica |
| Que cada cifra diga **de dónde sale y cómo se calcula** | Debajo de cada métrica |
| Que la aritmética cuadre y lo no clasificable se reporte | Cuatro cestas que suman el total |
| Detectar la palabra-gancho sola, sea la que sea, tolerando erratas | Automático, sin configurar nada |
| Leads: personas únicas, comentarios con el gancho, y el hueco entre captados y atendidos | Reels → Leads |
| Leads calientes con cita textual y motivo de negocio | Reels → Leads |
| CSV de leads para tu CRM | Junto al informe |
| Embudo de conversión (DM → abierto → clic → venta) sobre lo que registres | Reels → Conversión |
| Sentimiento con tamaño de muestra y banda de confianza | Reels → Sentimiento |
| Odio contado aparte, no mezclado con las críticas | Reels → cabecera |
| Objeciones agrupadas por tipo, tratadas como señal | Reels → Objeciones |
| Dudas recurrentes agrupadas y ordenadas por frecuencia | Reels → Lo que más preguntan |
| Cola de ideas priorizada, con gancho, motivo y quién lo pidió | Reels → Qué grabar, por orden |
| Retención de vídeo y distribución del alcance | Reels → dos bloques |
| Comparación con tus reels anteriores | Reels → Comparado con anteriores |
| Informe en `.md` | `data/instagram/informes/` |
| Umbrales configurables, fuera del código | `config/umbrales.json` |
| Perfil propio: nicho, negocio, público, tono, tu situación | 42 campos, vacío de fábrica |

### ⏳ Pendiente (fases acordadas)

- **Histórico mensual y anual** de tus publicaciones y de tus seguidores.
- **Analíticas de historias**, además de reels y publicaciones.
- **Transcripción del audio de tus reels** (Whisper) y análisis de portadas,
  para estudiar tus propios ganchos y tu estructura de venta.
- **Informes en PDF y PPT**, además del `.md`.

---

## 2. Competidores

### ✅ Hecho y en tu disco

| Lo que pediste | Estado |
|---|---|
| Analizar cuentas que no son tuyas | Reels → pestaña Competencia |
| Sus seguidores, reproducciones, me gusta y nº de comentarios | Por publicación y en mediana |
| Cara a cara contigo, con quién va por delante en cada métrica | Tabla comparativa |
| En qué estás por debajo, sin adjetivos | Bloque de brechas |
| Qué formato le funciona a cada uno y sus 5 publicaciones más vistas | Ficha por cuenta |
| Que se diga claramente lo que NO se puede ver | Bloque propio |
| Que tú puedas darle competidores a mano | Sí |

### ⏳ Pendiente (fases acordadas)

- **Buscar competidores por internet**: que salga a buscar cuentas de tu nicho y
  de tu producto, y te proponga la lista.
- **Validar cada candidato** contra la API antes de meterlo en ningún informe.
- **Análisis profundo de su contenido**: captions, estructura de ganchos,
  ángulos que repiten, ritmo de publicación y qué se les ha disparado frente a
  su propia mediana.
- **Entrada manual** para competidores con cuenta no profesional, marcada como
  «aportado por ti» frente a «verificado por la API».

---

## 3. Al conectar una cuenta (el onboarding)

Todo pendiente. Es la fase 2.

- Conectas Instagram o Facebook y **arranca solo**.
- Analiza tu cuenta y **deduce tu nicho** de lo que publicas.
- Sale a **buscar competidores** de ese nicho y ese producto.
- Los **valida** uno a uno y te presenta la lista para corregirla o ampliarla.
- Termina con una foto de dónde estás.

---

## 4. Planificación de contenido

Todo pendiente. Es la fase 5.

- **Plan mensual** para Instagram: reels, publicaciones e historias.
- Construido cruzando **tus dudas reales**, las objeciones de tu audiencia y lo
  que funciona en tu nicho.
- Cada idea **ya desarrollada**: gancho, guion y CTA. Para retocar, no para
  escribir de cero.

---

## 5. Lo que descartamos, y por qué

| Qué | Por qué |
|---|---|
| **Metricool** | Su API está en el plan de 43 €/mes, y no te da nada que no tengas ya gratis por la vía oficial. Además te quitaría la trazabilidad: cada cifra pasaría a ser «me lo dice Metricool» en vez de «Graph API · insights.reach». |
| **DMs / análisis de conversaciones** | Aparcado por ti. No hay fuente hoy; cuando la haya, se hace con un importador genérico. |
| **Auditoría launch-readiness** (módulo D) | Descartado por ti. |
| **Inteligencia sobre dataset externo** (módulo E) | Descartado por ti. |
| **Scraping de Instagram** | Para lo que quieres no añade ni un dato: la API oficial ya da likes, reproducciones, comentarios y captions de cualquier cuenta profesional. Y lo que se raspa de la interfaz va redondeado («12,4 mil») cuando la API da el entero exacto. |

---

## 6. Límites que no son decisiones mías, son hechos

Conviene tenerlos presentes para no esperar algo que no va a llegar:

- **El texto de los comentarios de otras cuentas: no se puede.** Por eso de un
  competidor no hay sentimiento posible. La API da cuántos comentarios tiene,
  nunca qué dicen.
- **Sus compartidos, guardados y alcance: tampoco.** Son métricas privadas de esa
  cuenta.
- **Cuentas no profesionales: la API no las ve.** Se resuelve con entrada manual.
- **La serie diaria de seguidores hacia atrás no existe.** Solo se construye
  hacia delante, guardando fotos desde que lo montemos. Las métricas de tus
  publicaciones ya publicadas sí se recuperan.
- **Quién te ha dejado de seguir no lo da Instagram a nadie**, ni por API ni
  mirando el perfil. Sabrás cuántos y cuándo, no quiénes.
- **Las impresiones** ya no las expone la API para reels en versiones recientes;
  cuando falten, el informe lo dice en vez de estimarlas.

---

## 7. Lo que necesito de ti para seguir

1. **El OK para la fase 2** (el onboarding con búsqueda y validación de
   competidores).
2. Cuando lleguemos a la fase 2: **los competidores que ya tengas en la cabeza**,
   para contrastar que la búsqueda automática los encuentra.
3. Si algún competidor tuyo tiene **cuenta personal**, dime cuál — es el único
   caso que necesita entrada manual.

---

## Orden de trabajo acordado

1. ~~Umbrales fuera del código~~ ✅ **hecha**
2. Onboarding: conectar cuenta, deducir nicho, buscar y validar competidores
3. Inteligencia de competencia: captions, formatos, ganchos, ritmo, outliers
4. Histórico mensual y anual
5. Plan mensual con las ideas ya desarrolladas
6. Informes en PDF y PPT
