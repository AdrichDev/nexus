# 🧠 Engram (memoria de proyecto)

Puente con [Engram](https://github.com/Gentleman-Programming/engram): memoria
de **PROYECTO/código** de nexus, guardada en `~/.engram/engram.db` y
**compartida con tus otras herramientas de IA** (Claude Code, Cursor, Codex,
Windsurf...) si también las conectaste a Engram — una decisión que tomas
hablando con Claude Code sobre el propio NEXUS, nexus también la conoce, y
viceversa.

**Hermes también queda enganchado.** nexus usa Engram por HTTP (esta skill), y
además engancha al subagente **Hermes** a la MISMA memoria por su vía nativa:
le añade un servidor MCP `engram` a `~/.hermes/config.yaml` (arranca
`engram mcp --project nexus` por stdio) la próxima vez que arranca su gateway.
Así los dos —nexus y Hermes— leen y escriben la misma memoria de proyecto. Lo
gestiona la skill de Hermes; compruébalo con «diagnostica hermes».

**Esto NO es tu memoria personal.** Tus contactos, tareas, hábitos y el
perfil que nexus aprende de ti siguen en la skill de **Memoria**
(Postgres + RAG + grafo). Engram es solo para decisiones de arquitectura,
bugs y features del código — deliberadamente separado para no mezclar tu
vida con el proyecto.

## Es opcional

Si no tienes el binario `engram` instalado, esta skill responde con
normalidad explicando que falta, y el resto de nexus sigue funcionando
exactamente igual. Nada se rompe por no tenerlo.

## Órdenes

- «recuerda en el proyecto que decidimos usar SQLite en vez de Postgres» →
  guarda una nota general (tipo `note`).
- «apunta un bug en el proyecto: el WhatsApp fallaba si n8n estaba caído» →
  tipo `bugfix`.
- «apunta una decisión de arquitectura en el proyecto: contexto reciente en
  el enrutador LLM» → tipo `architecture`.
- «qué se decidió sobre el WhatsApp» / «busca en el proyecto engram» →
  búsqueda por palabra clave.
- «contexto del proyecto» / «qué sabe engram» → resumen narrativo de lo
  guardado recientemente.
- «está engram conectado» / «diagnostica engram» → estado de la conexión
  (instalado, servidor arriba, cuántos recuerdos hay).

## Cómo se gestiona el servidor

nexus arranca `engram serve` él solo la primera vez que hace falta (como ya
hace con el gateway de Hermes): sin ventana de consola en Windows, log en
`data/engram_serve.log`, sin relanzar en ráfaga. Si `engram_autostart` está
desactivado en ⚙, o el binario no está instalado, esta skill simplemente
avisa y no hace nada más.

## Configuración (⚙, opcional)

- `engram_exe`: ruta al binario si no está en el PATH (vacío = autodetectar).
- `engram_port`: puerto de `engram serve` (por defecto 7437, el de la
  herramienta).
- `engram_autostart`: si nexus puede arrancar el servidor solo (por defecto
  sí).
- `engram_autoinstall`: si nexus puede INSTALAR el binario solo cuando falta
  (por defecto sí). Ponlo en `false` si prefieres instalarlo a mano.

## Instalación de Engram (nexus la hace por ti)

Engram es **un paquete más del instalador de nexus**: `run.bat` lo deja listo
al arrancar (como edge-tts o pypdf), y el `nexus.exe` empaquetado lo instala en
segundo plano la primera vez que arranca (ahí no pasa por `run.bat`). En ambos
casos nexus:

1. prueba `go install github.com/Gentleman-Programming/engram/cmd/engram@latest`
   si tienes Go (compila en tu máquina y evita el falso positivo de antivirus);
2. si no hay Go, descarga el binario oficial del release de GitHub, **verifica
   su SHA-256 contra el `checksums.txt`** del mismo release (no ejecuta nada sin
   verificar) y lo deja en `~/.engram/bin`.

Todo es best-effort: si no se puede instalar, nexus sigue funcionando igual y te
lo dice. Si tu antivirus marca el binario prebuilt como falso positivo, instala
con `go install` (compila en local) o añade una exclusión. Puedes desactivar la
instalación automática con `engram_autoinstall=false` en ⚙.

## Límites

- No hay borrado ni edición desde nexus (solo guardar/buscar/consultar) —
  para gestión avanzada (conflictos, export, TUI) usa el propio `engram` en
  una terminal.
- El proyecto es siempre `nexus`: esta skill no gestiona memoria de otros
  proyectos tuyos.
