# ◈ Núcleo IA (qué cerebro tiene nexus puesto)

Contesta qué proveedor y qué modelo de IA está usando nexus **ahora mismo**.
Es un dato de configuración: se LEE de `settings`, no se razona ni se le
pregunta al modelo. Por eso la respuesta es determinista y no pasa por el LLM.

«Núcleo IA» es la sección del propio HUD donde se elige el cerebro, no una
plataforma externa.

## Se dispara con

- «qué modelo de IA usas» / «pero qué modelo de IA» / «qué modelo estás usando»
- «qué núcleo de IA tienes» / «cuál es el núcleo» / «qué núcleo tienes puesto»
- «cuál es tu modelo de lenguaje» / «qué cerebro tienes» / «qué llm usas»
- «qué motor de ia usas» / «qué proveedor de ia tienes» / «con qué modelo funcionas»
- «qué IA eres» / «quién te mueve»

No se dispara con «el núcleo del problema», «el modelo de negocio», «el modelo
de datos» ni «el modelo del coche»: los patrones llevan lookaheads para eso.

## Qué contesta

- **Proveedor**: Ollama, OpenAI, Anthropic, Google Gemini, OpenRouter o
  Simulado, con una línea de dónde corre (local o nube, con qué clave).
- **Modelo**: el del ajuste que corresponde al proveedor (`ollama_model`,
  `openai_model`, `anthropic_model`, `gemini_model`, `cloud_model`).
- **Probado**: si `llm_runtime` ha conseguido que ese modelo conteste de verdad,
  con la latencia. Si no lo ha probado, lo dice; no lo da por bueno.
- Si el modelo que contestó no es el que pone la configuración, lo avisa.
- Si el proveedor es «Simulado», avisa de que no piensa nada.

## Necesita configurado

Nada para responder. Si no hay proveedor puesto, dice que el ajuste está vacío
y manda a ⚙ Configuración → Núcleo IA.

## Qué NO hace

- No cambia el modelo ni el proveedor: solo informa (se cambia en ⚙).
- No sale a internet ni consulta al modelo para responder.
- No lista los modelos disponibles ni los descarga.
