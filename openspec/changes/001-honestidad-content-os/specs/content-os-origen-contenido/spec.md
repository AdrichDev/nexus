# Content OS — Origen del Contenido Specification

## Purpose

De dónde puede venir el material de inspiración de Content OS: Graph API oficial
y aportación propia del usuario, nunca descarga de terceros.

## Requirements

### Requirement: `inspire` no descarga contenido ajeno

El intent `inspire` (`skills/content_os/skill.py`) MUST NOT invocar yt-dlp ni
transcribir contenido de terceros bajo ningún camino.

#### Scenario: Petición de inspiración de un reel ajeno

- GIVEN el usuario pide «inspiración de @creador <url>»
- WHEN se ejecuta el intent `inspire`
- THEN no se llama a descarga ni transcripción de contenido ajeno
- AND no se crea ningún fichero nuevo en `data/inspiration/`

### Requirement: `inspire` explica la política y reencamina

`inspire` MUST responder explicando que la política del proyecto prohíbe el
scraping de terceros y MUST señalar `business_discovery`
(`skills/instagram/scripts/ig.py:336`) como vía legítima.

#### Scenario: Respuesta del intent

- GIVEN el usuario pide inspiración de un reel ajeno
- WHEN se ejecuta `inspire`
- THEN la respuesta cita la Graph API / `business_discovery` como alternativa oficial

### Requirement: El material heredado se conserva y se puede seguir leyendo con aviso

Los ficheros ya existentes en `data/inspiration/` MUST NOT borrarse por este
cambio. Los intents `patterns` y `script` MAY seguir leyéndolos, pero MUST
avisar de que el origen es una transcripción heredada anterior a este cambio.

#### Scenario: Patrones sobre inspiración heredada

- GIVEN hay ficheros previos en `data/inspiration/`
- WHEN el usuario pide «analiza los patrones» o «genera un guion»
- THEN el sistema los usa igualmente
- AND la respuesta incluye un aviso de que el origen es material heredado, no descarga nueva

### Requirement: Borrado de material heredado exige confirmación explícita

Ningún endpoint o intent de este cambio MUST purgar `data/inspiration/`
automáticamente. Una purga futura requiere confirmación explícita del usuario y
queda fuera de este cambio.

#### Scenario: Intento de limpieza implícita

- GIVEN el sistema procesa cualquier intent de Content OS
- WHEN no hay una orden explícita de borrado del usuario
- THEN ningún fichero de `data/inspiration/` se elimina como efecto secundario
