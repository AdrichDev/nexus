; ============================================================
;  nexus — Instalador de Windows (NSIS)
;  Un instalador DE VERDAD: bienvenida, elegir carpeta, barra de
;  progreso, accesos directos y desinstalador en Panel de Control.
;
;  Cómo generar el instalador (en el PC, una vez):
;    1. installer\build_exe.bat        → crea dist\ (nexus.exe + knowledge + config)
;    2. installer\build_installer.bat  → crea nexus-Setup.exe con este script
; ============================================================
!include "MUI2.nsh"

; Este script vive en installer\, pero dist\ y el nexus-Setup.exe resultante
; viven en la RAIZ. makensis resuelve las rutas relativas contra su directorio
; de trabajo, que depende de quien lo lance; con este !cd deja de depender de
; eso y "dist\*.*" y OutFile apuntan siempre a la raiz. El arte (.ico/.bmp) si
; vive aqui al lado, y se referencia con ${__FILEDIR__} para no jugarsela.
!cd "${__FILEDIR__}\.."

Name "nexus"
BrandingText "nexus — Wide-Band Intelligent Knowledge System"
OutFile "nexus-Setup.exe"
Unicode True
RequestExecutionLevel user

; Carpeta por defecto (el usuario la puede CAMBIAR en el asistente)
InstallDir "$LOCALAPPDATA\nexus"
InstallDirRegKey HKCU "Software\nexus" "InstallDir"

; ---------------- Aspecto (paleta CIAN de nexus: #22d3ee sobre #070e18) ----------------
!define MUI_ICON "${__FILEDIR__}\nexus.ico"
!define MUI_UNICON "${__FILEDIR__}\nexus.ico"
!define MUI_ABORTWARNING
!define MUI_BGCOLOR 070e18
!define MUI_TEXTCOLOR cfe4f5
!define MUI_WELCOMEFINISHPAGE_BITMAP "${__FILEDIR__}\nexus_side.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${__FILEDIR__}\nexus_side.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP "${__FILEDIR__}\nexus_header.bmp"
; ventana de progreso de instalación: texto cian claro sobre azul nexus
InstallColors 7FE9F7 070E18

; ---------------- Páginas del asistente ----------------
!define MUI_WELCOMEPAGE_TITLE "Bienvenido a la instalación de nexus"
!define MUI_WELCOMEPAGE_TEXT "Tu asistente personal estilo JARVIS.$\r$\n$\r$\nEste asistente te guiará durante la instalación: podrás elegir dónde instalarlo, y al abrirlo por primera vez nexus te preguntará los permisos, la base de datos, su personalidad y tus cuentas.$\r$\n$\r$\nLa instalación empieza LIMPIA: sin memoria, solo con los nodos de conocimiento predefinidos."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\nexus.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir nexus ahora (asistente de primera ejecución)"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Spanish"

; ---------------- Instalación (componentes elegibles) ----------------
Section "nexus (necesario)" SEC01
  SectionIn RO   ; obligatorio, no desmarcable
  SetOutPath "$INSTDIR"
  ; nexus.exe + knowledge (nodos predefinidos) + config de ejemplo.
  ; MEMORIA VIRGEN garantizada: se EXCLUYEN data\, settings.json, secrets.json
  ; y .env aunque estuvieran en dist\ por error → en el PC de destino
  ; nexus arranca DE CERO con su asistente de instalación.
  File /r /x "data" /x "settings.json" /x "secrets.json" /x ".env" "dist\*.*"

  ; registro: carpeta elegida + entrada en "Agregar o quitar programas" (con la W)
  WriteRegStr HKCU "Software\nexus" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\nexus" \
      "DisplayName" "nexus — asistente personal"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\nexus" \
      "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\nexus" \
      "DisplayIcon" "$INSTDIR\nexus.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\nexus" \
      "Publisher" "Nexus"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Acceso directo en el Escritorio" SEC02
  CreateShortcut "$DESKTOP\nexus.lnk" "$INSTDIR\nexus.exe" "" "$INSTDIR\nexus.ico" 0
SectionEnd

Section "Carpeta en el Menú Inicio" SEC03
  CreateDirectory "$SMPROGRAMS\nexus"
  CreateShortcut "$SMPROGRAMS\nexus\nexus.lnk" "$INSTDIR\nexus.exe" "" "$INSTDIR\nexus.ico" 0
  CreateShortcut "$SMPROGRAMS\nexus\Desinstalar nexus.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

; descripciones de cada componente (se ven al pasar el ratón)
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC01} "El programa nexus con sus nodos de conocimiento predefinidos. Arranca de cero, sin memoria."
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC02} "Crea el icono de la doble W en tu Escritorio."
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC03} "Añade nexus (y su desinstalador) al Menú Inicio."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ---------------- Desinstalación ----------------
Section "Uninstall"
  Delete "$SMPROGRAMS\nexus\nexus.lnk"
  RMDir "$SMPROGRAMS\nexus"
  Delete "$DESKTOP\nexus.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\nexus"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\nexus"
SectionEnd
