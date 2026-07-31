---
name: arranca
description: Reinicia nexus limpiamente (libera el puerto 8177, arranca run.bat en segundo plano y comprueba que responde)
allowed-tools:
  - Bash
---

# Arrancar nexus

Reinicio limpio. Hazlo en este orden y no te saltes pasos.

1. **Libera el puerto.** Si quedó una instancia colgada, la nueva o revienta con
   `[Errno 10048]` o arranca con el código viejo y parece que los cambios no han
   surtido efecto:

   ```bat
   for /f "tokens=5" %p in ('netstat -ano ^| findstr ":8177 " ^| findstr LISTENING') do taskkill /F /PID %p
   ```

2. **Arranca**, en segundo plano, en su propia ventana:

   ```bat
   cmd /c start "" run.bat
   ```

   `run.bat` se auto-repara (venv, pydantic, cffi) y puede tardar la primera vez.

3. **Comprueba que responde** antes de dar nada por bueno:

   ```bat
   curl -s http://127.0.0.1:8177/api/status
   ```

   Si no contesta a los ~20 s, mira la consola que abrió `run.bat` y di qué error sale.

Recuerda: si has tocado cualquier `skills/*/skill.py`, este reinicio es
obligatorio — `skills_loader` lee las carpetas solo al arrancar.
