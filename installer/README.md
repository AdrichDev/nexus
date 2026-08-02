# installer/

Todo lo que hace falta para convertir el repositorio en un `.exe` y en un
instalador de Windows: `build_exe.bat` (PyInstaller, usa `nexus.spec`),
`build_installer.bat` (NSIS, usa `nexus_installer.nsi`) y el arte del asistente
(`nexus.ico`, `nexus_header.bmp`, `nexus_side.bmp`).

Vive aparte porque solo se toca al publicar una versión, no al desarrollar; en
la raíz solo estorbaba. **Ojo**: aunque los scripts estén aquí, trabajan desde la
raíz del proyecto (`cd /d "%~dp0.."`), porque de ahí cuelgan `.venv`, `frontend`,
`skills` y ahí es donde tiene que aparecer `dist\`.
