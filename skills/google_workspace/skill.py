"""Minion Google Workspace — Gmail, Calendar, Tasks y Drive REALES vía OAuth2.

La cuenta se conecta con config/google_credentials.json (ver SKILL.md).
Si faltan librerías o credenciales, responde con las instrucciones exactas.
Todas las llamadas a Google son síncronas → se ejecutan en un hilo aparte.
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import re
from pathlib import Path

# Import A NIVEL DE MODULO, y por la misma razon que en skills/system_pc: el
# fragmento que sale de aqui se concatena dentro de SKILL["patterns"], que se
# construye AL IMPORTAR este fichero. Un import perezoso llegaria tarde. No
# cierra ningun ciclo: `reglas` es dominio y solo importa `comun/config` y
# `comun/audit`, nunca skills ni `skills_loader`.
from backend.core.dominio import reglas as _reglas

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
CREDS_FILE = CONFIG_DIR / "google_credentials.json"
TOKEN_FILE = CONFIG_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",     # LEER + marcar leído/no leído + papelera (antes readonly)
    "https://www.googleapis.com/auth/gmail.send",       # ENVIAR correos
    "https://www.googleapis.com/auth/calendar.events",  # CREAR/editar eventos (antes readonly)
    "https://www.googleapis.com/auth/tasks",            # CREAR/editar tareas (antes readonly)
    "https://www.googleapis.com/auth/drive",            # DRIVE COMPLETO — ver el bloque de abajo
]
# ─────────────────────────────────────────────────────────────────────────────
# SCOPE DE DRIVE: «auth/drive» COMPLETO. DECISIÓN DEL 02/08/2026, DEL DUEÑO DE LA
# CUENTA, TOMADA SABIENDO LO QUE CUESTA. No es un descuido ni un copy-paste.
#
# Hasta esa fecha aquí ponía «drive.file» (solo los ficheros que crea la propia
# app) y había un test puesto expresamente para que nadie lo ampliara. El dueño de la cuenta lo
# amplió a propósito y lo dijo con estas palabras: «tiene que tener la posibilidad
# de tener acceso a todo el drive si se le pide o a carpetas específicas y ha de
# poder hacer CRUD tanto de archivos como carpetas en ese drive. Ha de tener
# control total.» Con drive.file eso es IMPOSIBLE: una carpeta creada a mano por
# él no existe para nexus, así que ni la lista, ni la renombra, ni mueve nada
# dentro. El test no se borró: se le dio la vuelta y ahora exige el scope completo
# y deja escrita la fecha y el motivo (tests/test_drive.py).
#
# EL PRECIO, ESCRITO PARA QUE NADIE SE SORPRENDA DESPUÉS:
#   * Con «auth/drive» nexus puede LEER, MODIFICAR, MOVER, RENOMBRAR y BORRAR
#     CUALQUIER documento de la cuenta, no solo los suyos: nóminas, contratos,
#     fotos, escrituras, lo que haya. No hay carpeta protegida.
#   * Y nexus enruta por regex: una frase mal casada apunta a ficheros REALES.
#   Por eso, y no por burocracia, todo lo destructivo de Drive lleva cinturón:
#     - «borra X de drive» manda a la PAPELERA de Drive (trashed = true), que es
#       reversible desde drive.google.com/drive/trash. NUNCA files.delete.
#     - el borrado DEFINITIVO (files.delete) existe pero solo se ejecuta desde
#       dentro de confirm.request() — el mismo patrón que la papelera del tablero
#       y que backend/core/purga.py.
#     - borrar una carpeta con contenido DICE CUÁNTOS elementos se lleva y pide
#       confirmación aunque solo vaya a la papelera.
#   * Mover y renombrar no destruyen nada y van directos.
#
# API verificada contra el discovery doc oficial drive.v3 (rev. 20260428) que trae
# google-api-python-client, no de memoria: files.create/list/get/update/delete
# admiten «auth/drive»; el movimiento es files.update con addParents/removeParents
# (parámetros reales del método) y el borrado suave es un update de «trashed».
# OJO: al ampliar scopes (calendar/tasks de solo-lectura → escritura), el token viejo
# ya no cubre los permisos nuevos. _get_creds() detecta que el token no es superset de
# SCOPES, lo borra y relanza la autorización UNA vez (igual que al añadir «enviar»).

# Puerto FIJO para el redirect de OAuth. Con puerto aleatorio (port=0) el
# redirect_uri cambia cada vez (127.0.0.1:55599…) y es IMPOSIBLE registrarlo en
# Google → Error 400 redirect_uri_mismatch. Con un puerto fijo, el redirect es
# estable y registrable.
# OJO: usamos la IP de loopback 127.0.0.1, NO «localhost». Google DESACONSEJA
# «localhost» para el flujo de loopback y muchos clientes «Aplicación web» lo
# RECHAZAN aunque lo registres → por eso fallaba. 127.0.0.1 sí lo acepta (es lo
# que usa también el callback de Spotify que ya funciona).
OAUTH_PORT = 8765
REDIRECT_HOST = "127.0.0.1"
REDIRECT_URI = f"http://{REDIRECT_HOST}:{OAUTH_PORT}/"

# Los dias del mes dichos EN LETRA, para el ROUTER. La tabla que los traduce a
# numero vive mas abajo, con el parser de fechas; aqui solo hace falta
# reconocerlos, y el router mira el texto tal cual llega.
_DIA_EN_LETRA = (r"uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|"
                 r"trece|catorce|quince|diecis[eé]is|diecisiete|dieciocho|diecinueve|"
                 r"veinte|veintiuno|veintid[oó]s|veintitr[eé]s|veinticuatro|"
                 r"veinticinco|veintis[eé]is|veintisiete|veintiocho|veintinueve|"
                 r"treinta|primero")

# EL SUSTANTIVO QUE DICE EL OPERADOR MANDA SOBRE UNA PALABRA SUELTA DEL TITULO.
#
# 05/08/2026, medido: «borra la tarea CITA con el dentista de prueba» acababa en
# `delete_event` y contestaba «No encuentro ningun evento». La culpa era del
# hueco comodin de 25 caracteres que hay entre el verbo y el sustantivo de
# calendario: se tragaba « la tarea » y luego encontraba «cita» DENTRO DEL
# TITULO de una tarea del tablero.
#
# El arreglo NO es acortar el hueco (haria falta para «borra ese evento de
# mañana») sino TEMPERARLO: el hueco puede tener cualquier cosa MENOS un
# sustantivo del tablero. Si la frase dice «tarea» antes de «cita/evento/
# reunion», la orden es del tablero interno y esta skill no la toca.
#
# La lista de sustantivos sale de `reglas.valor()` —reserva en el codigo,
# `config/umbrales.json` la puede pisar— igual que `system_pc.no_es_programa`.
# Se lee al importar porque el patron se monta al importar.
#
# OJO, ESTO NO AFECTA A «elimina las dos tareas DEL CALENDARIO», que SI es de
# Google: esa frase la caza la SEGUNDA rama de `delete_event`, la anclada a la
# palabra «calendario», y esa rama no se tempera. Es deliberado: quien nombra el
# calendario esta diciendo de que agenda habla.
_MANDA_EL_TABLERO = _reglas.valor("google_workspace.manda_el_tablero")

# Hueco «cualquier cosa menos un sustantivo del tablero», carácter a carácter.
# Es un token temperado: en cada posicion comprueba que ahi no empieza una de
# esas palabras antes de consumir el caracter.
_HUECO_SIN_TABLERO = r"(?:(?!\b(?:" + _MANDA_EL_TABLERO + r")\b)[^.\n]){0,25}"

SKILL = {
    "name": "Google (Gmail/Calendar/Drive)",
    "description": "Gmail, Calendar, Tasks y Drive reales por OAuth2: lee, cuenta, resume, envía y borra correos; triaje con IA que crea tareas; eventos que se crean, mueven y cancelan; sube informes a Drive y devuelve el enlace",
    # ORDEN IMPORTA (el router prueba los patterns en orden de este dict):
    # lo más específico primero para que «de quién son», «cuántos sin leer»,
    # «resume» o «envía» NO caigan en el patrón genérico de listar correos.
    "patterns": {
        "open_email": r"(?:[aá]bre(?:me)?|l[eé]e(?:me)?|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?)\s+el\s+(?:correo|mail|e-?mail)\s+(?:n[úu]mero\s+)?(?P<n>\d+)",
        "send_email": r"(?:env[ií]a(?:le|me)?|m[aá]nda(?:le|me)?|escr[ií]be(?:le)?|redacta(?:\s+y\s+env[ií]a)?)\s+(?:un\s+|una\s+)?(?:correo|mail|e-?mail|email|mensaje\s+de\s+correo)\b",
        # CREAR evento en Google Calendar (necesita mención de evento/cita/reunión/agenda/
        # calendario para no chocar con el LISTADO de calendario 'gcal'). Va ANTES de gcal.
        "create_event": r"(?:cr[eé]a(?:me)?|a[ñn][aá]de(?:me)?|agr[eé]ga(?:me)?|ap[uú]nta(?:me)?|ag[eé]nda(?:me)?|pon(?:me)?|mete(?:me)?|\bprograma(?:me)?|\bres[eé]rva(?:me)?)\b[^.\n]{0,30}\b(?:evento|cita|reuni[oó]n|recordatorio)\b"
                        r"|(?:a[ñn][aá]de|ap[uú]nta|ag[eé]nda|mete|cr[eé]a)(?:me)?\b[^.\n]{0,40}\b(?:al|en\s+(?:el|mi|google))\s+calendario\b",
        # CREAR tarea en Google Tasks (To-Do). Exige mención de google/to-do/tasks para NO
        # secuestrar «crea la tarea X» del tablero interno. Va ANTES de gtasks.
        "create_task": r"(?:cr[eé]a(?:me)?|a[ñn][aá]de(?:me)?|agr[eé]ga(?:me)?|ap[uú]nta(?:me)?|pon(?:me)?|mete(?:me)?)\b[^.\n]{0,40}\b(?:to-?do|google\s+tasks?|tareas?\s+de\s+google|lista\s+de\s+google)\b",
        # TRIAGE: ¿algo URGENTE en los correos (sin leer)? → analiza por detrás y reporta.
        "email_urgent": r"(?:correos?|mails?|e-?mails?|emails?|bandeja|gmail)\b[^.\n]{0,20}\b(?:urgentes?|que\s+corran?\s+prisa)\b"
                        r"|\b(?:urgentes?|que\s+corra?\s+prisa|urgencias?)\b[^.\n]{0,20}\b(?:correos?|mails?|e-?mails?|emails?|bandeja|gmail)\b"
                        r"|\balgo\s+urgente\b[^.\n]{0,20}\b(?:correo|mail|email|bandeja|gmail)\b",
        # TRIAGE-ACCIÓN: ¿algo IMPORTANTE que TRATAR/gestionar? / crea tareas de los correos.
        "email_actions": r"(?:algo|hay\s+algo)\b[^.\n]{0,40}\b(?:que\s+(?:tratar|gestionar|atender|hacer|responder)|importante\s+que\s+(?:tratar|gestionar|atender|hacer))\b[^.\n]{0,20}\b(?:correos?|mails?|e-?mails?|emails?|bandeja)\b"
                         r"|(?:cr[eé]a(?:me)?|gen[eé]ra(?:me)?|s[aá]ca(?:me)?|convi[eé]rte(?:me)?|prepara(?:me)?)\b[^.\n]{0,30}\btareas?\b[^.\n]{0,25}\b(?:correos?|mails?|e-?mails?|emails?|bandeja)\b"
                         r"|(?:cr[eé]a(?:me)?|convi[eé]rte(?:me)?|p[aá]sa(?:me)?|transforma)\b[^.\n]{0,20}\b(?:correos?|mails?|bandeja)\b[^.\n]{0,20}\b(?:en\s+|a\s+)?tareas?\b"
                         r"|(?:de|con)\s+(?:los\s+|mis\s+)?correos?\b[^.\n]{0,25}\b(?:cr[eé]a(?:me)?|s[aá]ca(?:me)?)\b[^.\n]{0,15}\btareas?\b"
                         # 02/08/2026: aquí ponía «gestiona|procesa|despacha|organiza» A SECAS.
                         # En español el pronombre enclítico DESPLAZA LA TILDE: «gestióname
                         # la bandeja», «procésalos», «despáchamelos». Con el verbo sin tilde
                         # NINGUNA de esas frases casaba y caían al planificador del cerebro.
                         r"|(?:anal[ií]za(?:me)?|proc[eé]sa(?:me)?|gesti[oó]na(?:me)?|organ[ií]za(?:me)?|desp[aá]cha(?:me)?|haz\s+triaje\s+de)\b[^.\n]{0,25}\b(?:los\s+|mis\s+)?(?:correos?|mails?|e-?mails?|emails?|bandeja)\b"
                         # «crea tareas de lo urgente/importante» (nexus lo sugiere así,
                         # sin decir «correos» — antes NO casaba y el LLM decía «hecho» sin hacer NADA)
                         r"|(?:cr[eé]a(?:me)?|gen[eé]ra(?:me)?|s[aá]ca(?:me)?|prepara(?:me)?|haz(?:me)?)\b[^.\n]{0,25}\btareas?\b[^.\n]{0,30}\b(?:lo\s+)?(?:urgentes?|importantes?|prioritari[oa]s?|que\s+corran?\s+prisa)\b",
        # SEGUIMIENTO POR PRONOMBRE: «analízalos», «no los leas, analízalos».
        # 31/07/2026: nexus acababa de listar los correos y Adri dijo «No los leas
        # analizalos». NINGÚN patrón casaba (todos exigen la palabra «correos»), así
        # que la frase caía al planificador del cerebro — que se limitó a repetírsela.
        # Va ANCLADA a la frase entera (^…$) a propósito: «analízalos» suelto es de
        # cualquiera, y esta skill se lo robaría a las que van detrás por orden
        # alfabético (hermes, instagram, media…). Encima el handler exige que haya
        # una lista de correos reciente; si no la hay, pregunta en vez de adivinar.
        "email_actions_pron": r"^\W*(?:no\s+(?:me\s+)?l[oa]s\s+leas[,;.\s]*)?"
                              # Con enclítico la tilde se mueve: analiza→analízalos,
                              # procesa→procésalos, gestiona→gestiónalos, despacha→despáchalos.
                              r"(?:anal[ií]za|proc[eé]sa|gesti[oó]na|organ[ií]za|desp[aá]cha|haz\s+triaje\s+de)"
                              r"(?:me)?\s*l[oa]s\b"
                              r"(?:\s+(?:en\s+segundo\s+plano|por\s+detr[aá]s|de\s+fondo))?\W*$",
        "summarize_emails": r"(?:res[uú]me(?:me)?|haz(?:me)?\s+un\s+resumen)\b[^.\n]{0,40}\b(?:correos?|mails?|e-?mails?|bandeja|gmail)\b(?:[^.\n]{0,15}?(?P<n>\d+))?",
        # MARCAR COMO NO LEÍDO (deshacer). VA ANTES que mark_read: si no, «marca … como
        # NO leído» casaría «leído» de mark_read ignorando el «no».
        # OJO con «déjalos»: la tilde va en la E, no en la A («déjalos sin leer»).
        # Con `dej[aá]` la frase NO casaba y se iba al planificador.
        "mark_unread": r"(?:m[aá]rca(?:los|lo|me|r)?|pon(?:los|lo|me)?|d[eé]j[aá](?:los|melos)?|devu[eé]lve(?:los|me)?)\b[^.\n]{0,25}\b(?:como\s+)?(?:no\s+le[ií]d[oa]s?|sin\s+leer)\b",
        # MARCAR COMO LEÍDO (CRUD Gmail): «pon los correos como leídos», «marca todo
        # como leído». Va ANTES de 'emails' para NO caer en listar/leer en voz.
        "mark_read": r"(?:pon(?:me|los|lo|los\s+correos)?|m[aá]rca(?:me|los|lo|r)?|d[eé]j[aá](?:los|melos)?|"
                     r"impone|deja)\b[^.\n]{0,30}\b(?:como\s+)?le[ií]d[oa]s?\b"
                     r"|\ble[ií]d[oa]s?\b[^.\n]{0,20}\b(?:los\s+|todos?\s+los\s+)?(?:correos?|mails?|e-?mails?)\b"
                     r"|marcar?\s+(?:todo|todos?)\b[^.\n]{0,20}\ble[ií]d[oa]s?\b",
        # BORRAR / ARCHIVAR correos (CRUD Gmail): a la papelera (recuperable).
        "delete_email": r"(?:b[oó]rra(?:me)?|elimina(?:me)?|qu[ií]ta(?:me)?|suprime|archiva(?:me)?|tira|manda\s+a\s+la\s+papelera|echa\s+a\s+la\s+papelera)\b"
                        r"[^.\n]{0,20}\b(?:el\s+|los\s+|ese\s+|este\s+|mis\s+|todos?\s+los\s+)?"
                        r"(?:correos?|mails?|e-?mails?)\b(?:[^.\n]{0,20}?(?P<n>\d+))?(?P<rest>.+)?",
        # BORRAR / CANCELAR eventos del calendario (CRUD Calendar).
        # 03/08/2026, DOS AGUJEROS MEDIDOS:
        #  1) el sustantivo iba en SINGULAR con \b detrás, así que «borra los
        #     EVENTOS del día 5» o «cancela las CITAS del miércoles» no casaban
        #     con nada y acababan en el planificador del cerebro — que respondió
        #     listando la agenda entera.
        #  2) hablando se dice «quiero que ELIMINES», no «elimina»: el subjuntivo
        #     tampoco casaba. Y a los eventos se les llama «tareas del calendario».
        # Por eso hay una segunda alternativa anclada a la palabra «calendario»:
        # cubre «elimina las dos tareas del calendario» sin robarle nada al
        # tablero interno (que nunca dice «calendario»).
        # 05/08/2026, TERCER AGUJERO: el hueco de 25 caracteres de la PRIMERA
        # rama se tragaba « la tarea » y cazaba «cita» dentro del TITULO de una
        # tarea del tablero. Ahora ese hueco va temperado con
        # `_HUECO_SIN_TABLERO` (ver el bloque de arriba). Las otras dos ramas se
        # quedan como estaban: la de «calendario» porque quien nombra el
        # calendario ya ha dicho de que agenda habla, y la de la fecha porque
        # va anclada a un dia y sin el no casa.
        "delete_event": r"(?:b[oó]rra(?:me)?|borres|borrar|elimin(?:a(?:me)?|es|en|ar)|"
                        r"qu[ií]t(?:a(?:me)?|es|ar)|cancel(?:a(?:me)?|es|ar)|"
                        r"an[uú]l(?:a(?:me)?|es|ar)|desconvoca)\b"
                        + _HUECO_SIN_TABLERO +
                        r"\b(?:el\s+|la\s+|los\s+|las\s+|mi\s+|mis\s+|ese\s+|esa\s+|esos\s+|esas\s+)?"
                        r"(?:eventos?|citas?|reuni(?:[oó]n|ones)|recordatorios?|mentor[ií]as?)\b(?P<what>.+)?"
                        r"|(?:b[oó]rra(?:me)?|borres|borrar|elimin(?:a(?:me)?|es|en|ar)|"
                        r"qu[ií]t(?:a(?:me)?|es|ar)|cancel(?:a(?:me)?|es|ar)|an[uú]l(?:a(?:me)?|es|ar))\b"
                        r"[^.\n]{0,45}\b(?:del|de\s+mi|en\s+el|en\s+mi)\s+(?:google\s+)?calendario\b(?P<whatcal>.+)?"
                        # Sin repetir el sustantivo. Al insistir nadie dice «los
                        # EVENTOS del día 5» otra vez: dice «borra los del día 5».
                        # La fecha es el ancla, y sin ella esta rama no casa.
                        r"|(?:b[oó]rra(?:me)?|borres|borrar|elimin(?:a(?:me)?|es|en|ar)|"
                        r"qu[ií]t(?:a(?:me)?|es|ar)|cancel(?:a(?:me)?|es|ar))\b"
                        # Hueco para lo que se dice entre el verbo y la fecha:
                        # «borra LO QUE HAYA EL día 5», «borra TAMBIÉN LA del 9».
                        r"[^.\n]{0,28}?\s*"
                        # `_DIA_EN_LETRA` va aquí porque el router mira el texto
                        # CRUDO: la conversión de letra a número la hace después
                        # el parser de fechas, y para entonces ya sería tarde.
                        r"(?P<whatdia>(?:de[l]?\s+)?(?:d[ií]a\s+(?:\d{1,2}|" + _DIA_EN_LETRA + r")|"
                        r"\d{1,2}\s+de\s+[a-záéíóú]+|"
                        r"(?<=del\s)(?:\d{1,2}|" + _DIA_EN_LETRA + r")\b|"
                        r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
                        r"lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|ma[ñn]ana|hoy)\b.*)",
        # MOVER / REPROGRAMAR un evento (CRUD Calendar)
        "edit_event": r"(?:mu[eé]ve(?:me)?|cambia(?:me)?|reprograma(?:me)?|aplaza|adelanta|retrasa|atrasa|edita|posp[oó]n)\b"
                      r"[^.\n]{0,25}\b(?:el\s+|la\s+|mi\s+)?(?:evento|cita|reuni[oó]n|mentor[ií]a)\b(?P<what2>.+)?",
        # QUIÉN / DE QUIÉN son los correos (sin leer) → SOLO remitentes+asunto, NUNCA el
        # cuerpo. Va ANTES que unread_count/emails: «de quiénes son los correos que tengo
        # sin leer» antes se colaba a conversación (LLM) y soltaba TODO desde memoria.
        "unread_from": r"cu[aá]l(?:es)?\b[^.\n]{0,30}\b(?:correos?|mails?|e-?mails?|emails?)\b"
                       r"|(?:de\s+)?qui[eé]n(?:es)?\s+(?:son|me\s+(?:ha|han)\s+(?:escrito|mandado|enviado)|tengo)\b[^.\n]{0,35}\b(?:correos?|mails?|e-?mails?|emails?)\b"
                       r"|\b(?:correos?|mails?|e-?mails?|emails?)\b[^.\n]{0,25}\bde\s+qui[eé]n(?:es)?\b"
                       r"|(?:de\s+)?qui[eé]n(?:es)?\s+son\s+(?:los\s+|mis\s+)?(?:correos?|mails?|e-?mails?|emails?)\b"
                       r"|\bqui[eé]n(?:es)?\s+me\s+(?:ha|han)\s+(?:escrito|mandado|enviado)\b"
                       r"|\b(?:dime|dame|lista)\s+(?:los\s+)?remitentes\b",
        # CUÁNTOS (sin leer) → número exacto + total de la bandeja. Tolera «cuántos correos
        # tengo sin leer», «cuántos tengo sin leer», «número de correos».
        "unread_count": r"cu[aá]nt[oa]s?\b[^.\n]{0,20}\b(?:correos?|mails?|e-?mails?|emails?|sin\s+leer)\b"
                        r"|(?:dame|dime|dete)\s+el\s+n[uú]mero\s+de\s+(?:correos?|mails?|e-?mails?|emails?)"
                        r"|n[uú]mero\s+de\s+(?:correos?|mails?|e-?mails?|emails?)"
                        r"|\b(?:correos?|mails?|e-?mails?|emails?)\s+sin\s+leer\b",
        # LISTAR/LEER correos. OJO: NADA de casar la conjunción «que» (era el BUG del
        # bucle: «no te he dicho QUE me leas CORREOS» disparaba lectura). Verbos de
        # lectura reales, e interrogativos SOLO pegados al sustantivo (qué correos).
        "emails": r"(?:l[eé]e(?:me|r)?|ver|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|dime|dame|revisa|mira|comprueba|consulta|[eé]cha(?:le|me)?\s+un\s+(?:ojo|vistazo)(?:\s+a)?)\b[^.\n]{0,25}\b(?:correos?|mails?|e-?mails?|gmail|bandeja(?:\s+de\s+entrada)?)\b"
                  r"|\b(?:qu[eé]|cu[aá]les?)\s+(?:correos?|mails?|e-?mails?)\b"
                  r"|\bqu[eé]\s+tengo\s+en\s+(?:el\s+correo|la\s+bandeja|el\s+gmail|gmail)\b"
                  r"|\b(?:hay|tengo)\s+(?:\w+\s+){0,1}(?:correos?|mails?|e-?mails?)\b"
                  r"|\b(?:correos?|mails?|e-?mails?)\b[^.\n]{0,18}(?:pendientes?|nuevos?|importantes?|recientes?)\b"
                  # «bandeja» a secas = bandeja de CORREO. Va la última de este intent
                  # (los de triaje, resumen y marcar van antes en el dict y ganan ellos).
                  # 02/08/2026: «qué tengo en la bandeja» —ejemplo LITERAL del SKILL.md—
                  # se lo comía skills/comms, que va antes por orden alfabético y tiene
                  # datos de MENTIRA dentro. Ver el candado de skills/comms/skill.py.
                  r"|\bbandeja(?:\s+de\s+entrada)?\b",
        "gcal": r"(?:qu[eé]\s+tengo|mira|ver|mu[eé]stra(?:me)?|dime|dame|revisa|acceso\s+a|abre|consulta|tienes|hay|c[oó]mo\s+est[aá]|ense[ñn]a(?:me)?)\b[^.\n]{0,25}\b(agenda|calendario|eventos?|citas?)\b"
                r"|\b(mi|la|el)\s+(agenda|calendario)\b|\bagenda\s+de\s+google\b|\bpr[oó]ximos\s+eventos\b|\bqu[eé]\s+tengo\s+(hoy|ma[ñn]ana|esta\s+semana|el\s+\w+)\b"
                # El sustantivo ENTRE el interrogativo y el verbo («qué citas tengo»)
                # no lo cogía ninguna alternativa: la primera exige verbo→sustantivo.
                r"|\bqu[eé]\s+(?:citas?|eventos?|reuniones?)\s+(?:tengo|hay)\b"
                r"|\btengo\s+(?:alg[uú]n[a]?\s+)?(?:cita|evento|reuni[oó]n)\b",
        "gtasks": r"\btareas\s+de\s+google\b|\bgoogle\s+tasks?\b|\bto-?do\s+de\s+google\b"
                  r"|\bqu[eé]\s+(?:tengo|hay)\s+en\s+(?:el|mi)\s+to-?do\b",

        # ── DRIVE ────────────────────────────────────────────────────────────
        # Van LAS ÚLTIMAS del dict A PROPÓSITO: así no pueden robarle una frase a
        # ningún intent de Gmail/Calendar/Tasks que ya funcionaba. Y TODAS exigen
        # la palabra literal «drive», que hoy no aparece en el patrón de ninguna
        # otra skill — sin esa ancla, un «sube el informe» se lo comería
        # autoprovision (docker_up empieza por «sube»).
        # ORDEN INTERNO, y no es cosmético: drive_link antes que drive_list porque
        # drive_list acepta «dame»/«muéstrame» y se tragaría «dame el enlace de
        # drive»; y drive_upload antes que drive_link porque «sube esto a drive y
        # dame el enlace» es una SUBIDA, no una consulta.
        # INCIDENTE, que costó media hora: el resto de este fichero usa [^.\n] como
        # hueco para no saltar de frase. Aquí NO vale, porque el hueco tiene que
        # dejar pasar un NOMBRE DE FICHERO y los nombres de fichero llevan punto:
        # «sube informe-2026-08-02.md a drive» no casaba con [^.\n] y se iba al
        # planificador del cerebro. Aquí el hueco es [^\n] y quien acota es la
        # palabra «drive», que es obligatoria en TODAS.
        # 02/08/2026, CRUD COMPLETO: los intents de acción (crear carpeta, mover,
        # renombrar, borrar, descargar, buscar) van ANTES que upload/link/list
        # porque son más específicos. Y OJO CON skills/files: gestiona ficheros
        # LOCALES y va ANTES por orden alfabético («f» < «g»), así que «borra la
        # carpeta X de drive» se lo llevaba ÉL. La solución está en su propio
        # fichero: un candado que descarta sus patrones cuando la frase dice
        # «drive» (skills/files/skill.py, _SIN_DRIVE).
        "drive_folder_create": r"(?:cr[eé]a(?:me)?|cr[eé]ar|h[aá]z(?:me)?|gen[eé]ra(?:me)?|nueva)"
                               r"\b[^\n]{0,25}\b(?:carpeta|directorio|folder)\b[^\n]{0,80}"
                               r"\b(?:google\s+)?drive\b",
        # «llévate» es enclítico igual que «llévalo»: sin el «te» la frase moría.
        "drive_move": r"(?:mu[eé]ve(?:me|lo|la)?|mover|traslada|trasladar|ll[eé]va(?:me|te|lo|la)?"
                      r"|pasa)\b[^\n]{0,100}\b(?:google\s+)?drive\b",
        "drive_rename": r"(?:ren[oó]mbra(?:me|lo|la)?|renombrar|cambia(?:le)?\s+el\s+nombre"
                        r"|c[aá]mbia(?:le)?\s+el\s+nombre)\b[^\n]{0,100}\b(?:google\s+)?drive\b",
        "drive_delete": r"(?:b[oó]rra(?:me|lo|la)?|borrar|elimina(?:me|lo|la)?|eliminar"
                        r"|qu[ií]ta(?:me|lo|la)?|destruye|tira|manda\s+a\s+la\s+papelera)"
                        r"\b[^\n]{0,100}\b(?:google\s+)?drive\b",
        "drive_replace": r"(?:actual[ií]za(?:me|lo|la)?|actualizar|reemplaza(?:lo|la)?"
                         r"|reempl[aá]za(?:lo|la)?|sustituye|sobrescribe|machaca)"
                         r"\b[^\n]{0,100}\b(?:google\s+)?drive\b",
        "drive_download": r"(?:desc[aá]rga(?:me|lo|la)?|descargar|b[aá]ja(?:me|lo|la)?|bajar"
                          r"|exporta(?:me)?|tr[aá]e(?:me)?)\b[^\n]{0,100}\b(?:google\s+)?drive\b",
        "drive_search": r"(?:busca(?:me)?|b[uú]sca(?:me)?|buscar|encuentra|localiza)"
                        r"\b[^\n]{0,100}\b(?:google\s+)?drive\b",
        # INCIDENTE: había dos alternativas para «guardar» y entre las dos se dejaban
        # fuera «guárdame» (una pedía «guarda» sin tilde, la otra exigía «melo/mela»).
        # «guárdame el informe en drive» acababa en drive_list, o sea LISTANDO en vez
        # de SUBIR. Una sola alternativa con la tilde opcional y el enclítico anidado.
        "drive_upload": r"(?:s[uú]be(?:me|lo|la|los|las)?|sub[ií]r(?:lo|la)?|cuelga(?:me|lo|la)?"
                        r"|gu[aá]rda(?:me(?:lo|la)?|lo|la)?|copia|mete|pon)"
                        r"\b[^\n]{0,50}\b(?:google\s+)?drive\b",
        "drive_link": r"\b(?:enlace|link|url|direcci[oó]n)\b[^\n]{0,30}\b(?:google\s+)?drive\b"
                      r"|\bdrive\b[^\n]{0,20}\b(?:enlace|link|url)\b",
        "drive_list": r"(?:qu[eé]\s+(?:hay|tengo|has\s+subido)|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?"
                      r"|l[ií]sta(?:me)?|dame|dime|ver|revisa|mira|abre|consulta)"
                      r"\b[^\n]{0,30}\b(?:google\s+)?drive\b"
                      r"|\b(?:ficheros?|archivos?|documentos?|informes?)\b[^\n]{0,20}"
                      r"\b(?:de|en)\s+(?:mi\s+|el\s+)?(?:google\s+)?drive\b",
    },
}

_last_emails: list[dict] = []

SETUP_MSG = (
    "Google aún no está conectado. Pasos: 1) console.cloud.google.com → proyecto nuevo → "
    "habilita las APIs de Gmail, Calendar, Tasks y Drive. 2) Credenciales → ID de cliente OAuth "
    "→ tipo «App de escritorio» (IMPORTANTE: NO «Aplicación web» — la de escritorio acepta "
    "cualquier localhost SIN registrar nada). 3) Pantalla de consentimiento OAuth: en modo "
    "«Prueba» añade TU cuenta de Google como «Usuario de prueba» (si no, Google bloquea el "
    "acceso). 4) Pega el Client ID y el Client Secret en ⚙ (sección Google) y yo genero el "
    "archivo solo, o descarga el JSON como config/google_credentials.json. "
    "5) pip install google-api-python-client google-auth-oauthlib. "
    "Guía completa en skills/google_workspace/SKILL.md"
)

# Mensaje único y claro para el error «Acceso bloqueado: la solicitud de esta app
# no es válida» (Error 400: redirect_uri_mismatch / invalid_request). Es SIEMPRE
# configuración del cliente OAuth, nunca de nexus.
BLOCKED_MSG = (
    "Google dice «Acceso bloqueado: la solicitud de esta app no es válida» "
    "(Error 400: redirect_uri_mismatch). NO es un fallo de nexus, es el cliente "
    "OAuth. En console.cloud.google.com → APIs y servicios → Credenciales → tu "
    "cliente:\n"
    f"  • Si es «Aplicación web»: en «URIs de redirección autorizadas» (¡NO en "
    f"«Orígenes autorizados de JavaScript»!) añade EXACTAMENTE, con la barra final: "
    f"{REDIRECT_URI}  — usa 127.0.0.1, NO «localhost» (Google ya no lo acepta bien). "
    "Guarda y espera 1-2 min a que propague.\n"
    "  • LO MÁS FÁCIL: crea un cliente NUEVO de tipo «App de escritorio» (acepta "
    "cualquier 127.0.0.1 sin registrar nada) y pega su Client ID/Secret en ⚙.\n"
    "  • Y en «Pantalla de consentimiento OAuth», modo Prueba → añádete como "
    "«Usuario de prueba».\n"
    "Después borra config/google_token.json y vuelve a pedírmelo."
)


def _client_kind() -> str:
    """'installed' (App de escritorio), 'web' (App web) o '' si no se puede leer.
    Un cliente 'web' EXIGE registrar el redirect exacto → causa habitual del bloqueo."""
    try:
        import json
        data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
        if "installed" in data:
            return "installed"
        if "web" in data:
            return "web"
    except Exception:
        pass
    return ""


def _get_creds():
    """Devuelve credenciales OAuth válidas (refresca o lanza el flujo si hace falta).
    Usa un PUERTO FIJO y un TIMEOUT para no colgar el asistente si no autorizas."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_FILE.exists():
        # Los permisos CONCEDIDOS se leen del ARCHIVO del token (la librería pisa
        # creds.scopes con los pedidos, así que no sirve para comparar). Si el token
        # no tiene todos los permisos actuales (p.ej. se añadió ENVIAR correos), se
        # borra y se reautoriza — si no, Google da RefreshError: invalid_scope.
        granted: list = []
        try:
            import json as _json
            granted = _json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("scopes", [])
        except Exception:
            granted = []
        if granted and not set(SCOPES).issubset(set(granted)):
            try:
                TOKEN_FILE.unlink()
            except Exception:
                pass
        else:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    # refrescar token caducado; si Google lo rechaza (invalid_scope/invalid_grant),
    # el token no sirve → se borra y se pasa al flujo de autorización
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            creds = None
            try:
                TOKEN_FILE.unlink()
            except Exception:
                pass
    if not creds or not creds.valid:
        kind = _client_kind()
        try:
            from backend.core.comun.events import bus
            if kind == "web":
                bus.emit_sync("log", {"level": "warn",
                    "msg": "Google: tu cliente OAuth es de tipo «Aplicación web». Si sale "
                           f"«Acceso bloqueado: solicitud no válida», añade {REDIRECT_URI} "
                           "(con la barra final) a las URIs de redirección autorizadas, o "
                           "—mejor— crea uno de tipo «App de escritorio»."})
            else:
                bus.emit_sync("log", {"level": "info",
                    "msg": "Google: abriendo el navegador para autorizar (una sola vez). "
                           "Si sale «Acceso bloqueado», tu cliente debe ser «App de "
                           "escritorio» y tu cuenta debe estar como «Usuario de prueba»."})
        except Exception:
            pass
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDS_FILE), SCOPES, redirect_uri=REDIRECT_URI)
        # timeout: si no autorizas en 2 min, corta en vez de colgar el asistente
        try:
            creds = flow.run_local_server(port=OAUTH_PORT, open_browser=True,
                                          timeout_seconds=120, host=REDIRECT_HOST,
                                          success_message="Autorizado. Cierra esta pestaña "
                                          "y vuelve a nexus.")
        except TypeError:            # versiones antiguas sin timeout_seconds
            creds = flow.run_local_server(port=OAUTH_PORT, open_browser=True)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _fetch_emails(limit: int = 5, only_unread: bool = False) -> list[dict]:
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=_get_creds(), cache_discovery=False)
    kw = {"userId": "me", "labelIds": ["INBOX"], "maxResults": limit}
    if only_unread:                       # solo los NO leídos (para «de quién son los sin leer»)
        kw["q"] = "is:unread"
    res = svc.users().messages().list(**kw).execute()
    out = []
    for item in res.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=item["id"],
                                         format="metadata",
                                         metadataHeaders=["From", "Subject"]).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        out.append({"id": item["id"],
                    "from": re.sub(r"<.*?>", "", headers.get("From", "?")).strip(),
                    "subject": headers.get("Subject", "(sin asunto)"),
                    "snippet": msg.get("snippet", "")[:120],
                    "unread": "UNREAD" in msg.get("labelIds", [])})
    return out


def _read_email(msg_id: str) -> str:
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=_get_creds(), cache_discovery=False)
    msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()

    def _extract(part) -> str:
        if part.get("mimeType") == "text/plain" and part["body"].get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
        for sub in part.get("parts", []):
            text = _extract(sub)
            if text:
                return text
        return ""

    return _extract(msg["payload"]) or msg.get("snippet", "(sin contenido de texto)")


def _fetch_events(limit: int = 6, tmin: str | None = None, tmax: str | None = None) -> list[dict]:
    from googleapiclient.discovery import build
    svc = build("calendar", "v3", credentials=_get_creds(), cache_discovery=False)
    kw = {"calendarId": "primary", "maxResults": limit,
          "singleEvents": True, "orderBy": "startTime",
          "timeMin": tmin or dt.datetime.now(dt.timezone.utc).isoformat()}
    if tmax:
        kw["timeMax"] = tmax
    res = svc.events().list(**kw).execute()
    out = []
    for ev in res.get("items", []):
        start = ev["start"].get("dateTime", ev["start"].get("date", ""))
        fin = ev["end"].get("dateTime", ev["end"].get("date", "")) if ev.get("end") else ""
        # `dateTime` lleva hora; `date` a secas es un evento de DÍA COMPLETO.
        todo_el_dia = not ev["start"].get("dateTime")
        # `when`/`what` se quedan tal cual: los usan las respuestas habladas de la
        # skill. Lo demás es NUEVO y lo pide la vista de agenda, que necesita la
        # fecha y la hora por separado para poder pintar un calendario de verdad
        # —y la descripción, que antes se perdía por el camino—.
        out.append({"when": start[:16].replace("T", " "),
                    "what": ev.get("summary", "(sin título)"),
                    "fecha": start[:10],
                    "hora": "" if todo_el_dia else start[11:16],
                    "hora_fin": "" if todo_el_dia else fin[11:16],
                    "fecha_fin": fin[:10],
                    "todo_el_dia": todo_el_dia,
                    "desc": (ev.get("description") or "").strip(),
                    "lugar": (ev.get("location") or "").strip(),
                    "id": ev.get("id", "")})
    return out


_MES_NUM = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
            "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
            "noviembre": 11, "diciembre": 12}


def _month_range(text: str) -> tuple[str, str, str] | None:
    """Si la orden pide un MES («de julio», «este mes»), devuelve (inicio, fin,
    nombre) del mes COMPLETO en UTC; None si no pide mes."""
    t = text.lower()
    mm = re.search(r"\b(" + "|".join(_MES_NUM) + r")\b", t)
    if not mm and not re.search(r"\beste\s+mes\b|\bdel\s+mes\b|\bel\s+mes\b", t):
        return None
    now = dt.datetime.now(dt.timezone.utc)
    month = _MES_NUM[mm.group(1)] if mm else now.month
    name = mm.group(1) if mm else "este mes"
    year = now.year
    start = dt.datetime(year, month, 1, tzinfo=dt.timezone.utc)
    end = dt.datetime(year + (1 if month == 12 else 0),
                      1 if month == 12 else month + 1, 1, tzinfo=dt.timezone.utc)
    return start.isoformat(), end.isoformat(), name


def _fetch_tasks(limit: int = 10) -> list[str]:
    from googleapiclient.discovery import build
    svc = build("tasks", "v1", credentials=_get_creds(), cache_discovery=False)
    lists_ = svc.tasklists().list(maxResults=3).execute().get("items", [])
    out = []
    for tl in lists_:
        for t in svc.tasks().list(tasklist=tl["id"], showCompleted=False,
                                  maxResults=limit).execute().get("items", []):
            out.append(t.get("title", ""))
    return [t for t in out if t][:limit]


def _count_unread() -> tuple[int, int | None]:
    """(sin leer, total) de la BANDEJA DE ENTRADA — el MISMO número que ve Adri.
    OJO: la app de Gmail cuenta CONVERSACIONES (threads), no mensajes; antes
    usábamos messagesUnread (33) y su app marcaba 31 → «nunca lee el valor
    exacto». threadsUnread/threadsTotal, con messages* de respaldo."""
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=_get_creds(), cache_discovery=False)
    inbox = svc.users().labels().get(userId="me", id="INBOX").execute()
    unread = inbox.get("threadsUnread")
    total = inbox.get("threadsTotal")
    if unread is None:
        unread = inbox.get("messagesUnread", 0)
    if total is None:
        total = inbox.get("messagesTotal")
    return unread or 0, total


# ---------------------- CRUD Gmail: marcar leído/no leído, borrar ----------------------
def _mark_read(ids: list[str] | None = None) -> int:
    """Marca como LEÍDOS (quita la etiqueta UNREAD). Si ids es None, TODOS los no
    leídos de la bandeja. Devuelve cuántos hilos marcó."""
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=_get_creds(), cache_discovery=False)
    if ids is None:
        res = svc.users().messages().list(userId="me", labelIds=["INBOX"],
                                          q="is:unread", maxResults=500).execute()
        ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        return 0
    for i in range(0, len(ids), 900):          # batchModify admite 1000/llamada
        svc.users().messages().batchModify(
            userId="me", body={"ids": ids[i:i + 900],
                               "removeLabelIds": ["UNREAD"]}).execute()
    return len(ids)


def _mark_unread(ids: list[str]) -> int:
    """Vuelve a marcar como NO leídos (añade UNREAD)."""
    from googleapiclient.discovery import build
    if not ids:
        return 0
    svc = build("gmail", "v1", credentials=_get_creds(), cache_discovery=False)
    svc.users().messages().batchModify(
        userId="me", body={"ids": ids, "addLabelIds": ["UNREAD"]}).execute()
    return len(ids)


def _trash_emails(ids: list[str]) -> int:
    """Manda correos a la PAPELERA (recuperable 30 días — no borrado permanente)."""
    from googleapiclient.discovery import build
    if not ids:
        return 0
    svc = build("gmail", "v1", credentials=_get_creds(), cache_discovery=False)
    n = 0
    for mid in ids:
        try:
            svc.users().messages().trash(userId="me", id=mid).execute()
            n += 1
        except Exception:
            pass
    return n


def _search_email_ids(query: str, limit: int = 25) -> list[str]:
    """IDs de correos que casan una búsqueda Gmail («from:banco», «older_than:30d»…)."""
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=_get_creds(), cache_discovery=False)
    res = svc.users().messages().list(userId="me", q=query, maxResults=limit).execute()
    return [m["id"] for m in res.get("messages", [])]


# ---------------------- CRUD Calendar: buscar, borrar, editar ----------------------
def _find_events(query: str = "", limit: int = 10) -> list[dict]:
    """Próximos eventos (opcionalmente filtrados por texto). Devuelve
    [{id, summary, start, when}] para localizar cuál borrar/editar."""
    import datetime as _dt
    from googleapiclient.discovery import build
    svc = build("calendar", "v3", credentials=_get_creds(), cache_discovery=False)
    now = _dt.datetime.utcnow().isoformat() + "Z"
    kw = {"calendarId": "primary", "timeMin": now, "maxResults": limit,
          "singleEvents": True, "orderBy": "startTime"}
    if query.strip():
        kw["q"] = query.strip()
    items = svc.events().list(**kw).execute().get("items", [])
    out = []
    for ev in items:
        st = ev.get("start", {})
        start = st.get("dateTime") or st.get("date") or ""
        out.append({"id": ev.get("id", ""), "summary": ev.get("summary", "(sin título)"),
                    "start": start, "when": start[:16].replace("T", " ")})
    return out


_DIAS_SEMANA = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
                "viernes": 4, "sabado": 5, "domingo": 6}
# Números de evento («cancela el evento 2») — NO son fechas. Se quitan del texto
# antes de buscar días sueltos o «el 2» se leería como el día 2 del mes.
_ORDINAL_EVENTO_RX = re.compile(
    r"\b(?:eventos?|citas?|reuni(?:on|ones)|recordatorios?)\s+(?:numero\s+)?\d{1,2}\b")
# Verbos de BORRAR. Sirven de candado en el listado del calendario: una orden de
# borrar no puede acabar leyendo la agenda (ver la rama `gcal` de handle()).
_PIDE_BORRAR_RX = re.compile(
    r"\b(?:b[oó]rra\w*|borres|borrar|elimin\w+|qu[ií]t(?:a\w*|es|ar)|"
    r"cancel(?:a\w*|es|ar)|an[uú]l(?:a\w*|es|ar)|desconvoca)\b", re.IGNORECASE)


def _sin_tildes(texto: str) -> str:
    """Minúsculas sin tildes: «miércoles»/«miercoles» y «día»/«dia» son lo mismo."""
    t = (texto or "").lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u")):
        t = t.replace(a, b)
    return t


def _fmt_cuando(iso: str) -> str:
    """Fecha ISO (YYYY-MM-DD, con o sin hora) → dd/mm/aaaa [hh:mm].

    SOLO para MOSTRAR. Los datos que viajan al frontend y todo lo que se le manda
    a Google siguen en ISO: aquí se cambia el escaparate, no el almacén."""
    s = (iso or "").strip().replace("T", " ")
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}:\d{2}))?", s)
    if not m:
        return (iso or "").strip()
    fecha = f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return f"{fecha} {m.group(4)}" if m.group(4) else fecha


def _proximo_dia_mes(dia: int, hoy: dt.date) -> dt.date | None:
    """«el día 5» a secas = el 5 más cercano que NO haya pasado (este mes o el
    siguiente). Se prueban tres meses porque el 31 no existe en todos."""
    for salto in (0, 1, 2, 3):
        mes = hoy.month + salto
        anio = hoy.year + (mes - 1) // 12
        try:
            cand = dt.date(anio, (mes - 1) % 12 + 1, dia)
        except ValueError:
            continue
        if cand >= hoy:
            return cand
    return None


# Los días del mes dichos EN LETRA. Hablando se dice «el día nueve» tanto como
# «el día 9», y por voz el dictado los escribe así casi siempre.
_EN_LETRA = {
    "uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5", "seis": "6",
    "siete": "7", "ocho": "8", "nueve": "9", "diez": "10", "once": "11",
    "doce": "12", "trece": "13", "catorce": "14", "quince": "15",
    "dieciseis": "16", "diecisiete": "17", "dieciocho": "18", "diecinueve": "19",
    "veinte": "20", "veintiuno": "21", "veintidos": "22", "veintitres": "23",
    "veinticuatro": "24", "veinticinco": "25", "veintiseis": "26",
    "veintisiete": "27", "veintiocho": "28", "veintinueve": "29", "treinta": "30",
    "primero": "1",
}
_NUMEROS_EN_LETRA = re.compile(r"\b(?:" + "|".join(
    sorted(_EN_LETRA, key=len, reverse=True)) + r")\b")


def _fechas_pedidas(text: str) -> list[dt.date]:
    """Las fechas que la orden usa como SELECTOR de eventos.

    Entiende «del día 5», «el 5 y el 9», «del 5 de agosto», «05/08», «el
    miércoles», «de mañana», «hoy». Devuelve la lista ordenada y sin repetidos, o
    vacía si la orden no nombra ninguna fecha.

    Si hay algún número de día, los nombres de día de la semana se IGNORAN: en
    «el miércoles día 5 y el domingo día 9» el número manda, y mezclarlos con el
    próximo miércoles borraría eventos que nadie ha pedido borrar."""
    low = _NUMEROS_EN_LETRA.sub(lambda m: _EN_LETRA[m.group(0)],
                                _ORDINAL_EVENTO_RX.sub(" ", _sin_tildes(text)))
    hoy = dt.date.today()
    fechas: list[dt.date] = []

    def _anota(f: dt.date | None) -> None:
        if f and f not in fechas:
            fechas.append(f)

    # 1) dd/mm[/aaaa]
    for m in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", low):
        d, mo = int(m.group(1)), int(m.group(2))
        anio = int(m.group(3)) if m.group(3) else hoy.year
        anio = anio + 2000 if anio < 100 else anio
        try:
            _anota(dt.date(anio, mo, d))
        except ValueError:
            pass
    resto = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " ", low)

    # 2) «5 de agosto» (con año explícito o el próximo que llegue)
    meses = "|".join(_MES_NUM)
    for m in re.finditer(rf"\b(\d{{1,2}})\s+de\s+({meses})\b(?:\s+de\s+(\d{{4}}))?", resto):
        d, mo = int(m.group(1)), _MES_NUM[m.group(2)]
        if m.group(3):
            anio = int(m.group(3))
        else:
            anio = hoy.year if (mo, d) >= (hoy.month, hoy.day) else hoy.year + 1
        try:
            _anota(dt.date(anio, mo, d))
        except ValueError:
            pass
    resto = re.sub(rf"\b\d{{1,2}}\s+de\s+(?:{meses})\b(?:\s+de\s+\d{{4}})?", " ", resto)

    # 3) día suelto del mes: «día 5», «el 5», «del 9»
    for m in re.finditer(r"\b(?:dia\s+|del\s+|el\s+)(\d{1,2})\b", resto):
        d = int(m.group(1))
        if 1 <= d <= 31:
            _anota(_proximo_dia_mes(d, hoy))

    hay_numero = bool(fechas)

    # 4) hoy / mañana / pasado mañana. «de la mañana» y «por la mañana» son la
    #    HORA del día, no el día siguiente: se descartan con el lookbehind.
    if re.search(r"\bpasado\s+manana\b", low):
        _anota(hoy + dt.timedelta(days=2))
    elif re.search(r"(?<!de la )(?<!por la )\bmanana\b", low):
        _anota(hoy + dt.timedelta(days=1))
    if re.search(r"\bhoy\b", low):
        _anota(hoy)

    # 5) día de la semana → la próxima vez que caiga (solo si no había números)
    if not hay_numero:
        for nombre, wd in _DIAS_SEMANA.items():
            if re.search(rf"\b{nombre}\b", low):
                _anota(hoy + dt.timedelta(days=((wd - hoy.weekday()) % 7) or 7))

    return sorted(fechas)


# Cuando el operador dice que ya lo ha comprobado él, preguntar otra vez no es
# prudencia: es hacerle repetir. Todo lo que se borra va a la papelera, así que
# saltarse la confirmación no destruye nada de forma irreversible.
_SIN_PREGUNTAR_RX = re.compile(
    r"\b(?:directamente|sin\s+preguntar(?:me)?|no\s+(?:me\s+)?preguntes(?:\s+m[aá]s)?|"
    r"ya\s+lo\s+(?:he\s+)?(?:comprobado|mirado|revisado|visto)|"
    r"sin\s+confirmar|sin\s+m[aá]s|de\s+una\s+vez|hazlo\s+ya|"
    r"no\s+preguntes|a\s+la\s+primera)\b", re.IGNORECASE)


def _tareas_en(fechas: list[dt.date]) -> list[dict]:
    """Las tareas del TABLERO cuya fecha cae en esos días.

    La agenda del HUD junta el calendario de Google y las tareas con fecha, así
    que para quien mira la pantalla son la misma cosa. Se cuentan las que están
    vivas: las que ya están en la papelera no se vuelven a borrar."""
    if not fechas:
        return []
    dias = {f.isoformat() for f in fechas}
    try:
        from backend.core.dominio import board
        return [t for t in board._load()
                if (t.get("due") or "")[:10] in dias
                or (t.get("dueEnd") or "")[:10] in dias]
    except Exception:                                      # noqa: BLE001
        return []


def _eventos_en(fechas: list[dt.date], limit: int = 100) -> list[dict]:
    """Los eventos del calendario que caen en esas fechas.

    A Google se le pide el rango que las cubre, ensanchado un día por cada lado:
    sin tzdata en el sistema no se puede construir un instante exacto de
    Europe/Madrid, y el filtro fino se hace después comparando la fecha LOCAL que
    devuelve la propia API (`start.date`/`start.dateTime`, ya con su desfase)."""
    if not fechas:
        return []
    tmin = (min(fechas) - dt.timedelta(days=1)).isoformat() + "T00:00:00Z"
    tmax = (max(fechas) + dt.timedelta(days=2)).isoformat() + "T00:00:00Z"
    objetivo = {f.isoformat() for f in fechas}
    out = []
    for e in _fetch_events(limit, tmin, tmax):
        ini = (e.get("fecha") or "")[:10]
        if not ini:
            continue
        if not e.get("todo_el_dia"):
            if ini in objetivo:
                out.append(e)
            continue
        # De día completo: Google da el final EXCLUSIVO, así que el evento ocupa
        # [inicio, fin) y hay que mirar todos los días que abarca.
        try:
            d0 = dt.date.fromisoformat(ini)
            d1 = dt.date.fromisoformat((e.get("fecha_fin") or "")[:10] or ini)
        except ValueError:
            continue
        if d1 <= d0:
            d1 = d0 + dt.timedelta(days=1)
        d = d0
        while d < d1:
            if d.isoformat() in objetivo:
                out.append(e)
                break
            d += dt.timedelta(days=1)
    return out


def _delete_event(event_id: str) -> bool:
    from googleapiclient.discovery import build
    svc = build("calendar", "v3", credentials=_get_creds(), cache_discovery=False)
    svc.events().delete(calendarId="primary", eventId=event_id).execute()
    return True


def _patch_event(event_id: str, start: str | None = None, end: str | None = None,
                 summary: str | None = None) -> bool:
    """Cambia hora/título de un evento (mover/reprogramar/renombrar)."""
    from googleapiclient.discovery import build
    svc = build("calendar", "v3", credentials=_get_creds(), cache_discovery=False)
    body: dict = {}
    if summary:
        body["summary"] = summary
    if start:
        body["start"] = {"dateTime": start, "timeZone": _TZ}
        body["end"] = {"dateTime": end or start, "timeZone": _TZ}
    if not body:
        return False
    svc.events().patch(calendarId="primary", eventId=event_id, body=body).execute()
    return True


def _send_gmail(to: str, subject: str, body: str) -> str:
    """Envía un correo REAL desde la cuenta del operador. Devuelve el id."""
    from email.mime.text import MIMEText
    from googleapiclient.discovery import build
    svc = build("gmail", "v1", credentials=_get_creds(), cache_discovery=False)
    m = MIMEText(body, _charset="utf-8")
    m["to"] = to
    m["subject"] = subject
    raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
    sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    return sent.get("id", "")


# ================== CREAR eventos / tareas (ESCRITURA) ==================
_TZ = "Europe/Madrid"     # Adri está en España; para eventos con hora
_DIAS = {"lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3,
         "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6}
_TIME_RX = re.compile(
    r"\ba\s+las\s+(\d{1,2})(?:[:.](\d{2}))?\s*(?:h|horas)?\s*"
    r"(?:de\s+la\s+(mañana|tarde|noche)|(am|pm))?", re.IGNORECASE)


def _parse_when(text: str):
    """De una orden natural saca (start, end, all_day). start/end en ISO.
    all_day=True → start/end son fechas (YYYY-MM-DD). None si no hay fecha clara."""
    low = text.lower()
    today = dt.date.today()
    date_ = None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", low)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else (today.year if (mo, d) >= (today.month, today.day) else today.year + 1)
        y = y + 2000 if y < 100 else y
        try:
            date_ = dt.date(y, mo, d)
        except ValueError:
            date_ = None
    if not date_:
        m = re.search(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MES_NUM) + r")\b", low)
        if m:
            d, mo = int(m.group(1)), _MES_NUM[m.group(2)]
            y = today.year if (mo, d) >= (today.month, today.day) else today.year + 1
            try:
                date_ = dt.date(y, mo, d)
            except ValueError:
                date_ = None
    if not date_:
        if "pasado mañana" in low:
            date_ = today + dt.timedelta(days=2)
        elif "mañana" in low or "manana" in low:
            date_ = today + dt.timedelta(days=1)
        elif re.search(r"\bhoy\b", low):
            date_ = today
        else:
            for name, wd in _DIAS.items():
                if re.search(rf"\b(?:el\s+|este\s+|pr[oó]ximo\s+)?{name}\b", low):
                    delta = (wd - today.weekday()) % 7 or 7
                    date_ = today + dt.timedelta(days=delta)
                    break
    if not date_:
        return None
    tm = _TIME_RX.search(low)
    if tm:
        h, mnt = int(tm.group(1)), int(tm.group(2) or 0)
        franja = (tm.group(3) or "").lower()
        ampm = (tm.group(4) or "").lower()
        if franja in ("tarde", "noche") and h < 12:
            h += 12
        if ampm == "pm" and h < 12:
            h += 12
        h = min(h, 23)
        start = dt.datetime(date_.year, date_.month, date_.day, h, mnt)
        end = start + dt.timedelta(hours=1)
        return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"), False
    return date_.isoformat(), (date_ + dt.timedelta(days=1)).isoformat(), True


# ══════════ EVENTOS DE VARIOS DÍAS Y TÍTULO LIMPIO (se reutiliza el tablero) ══════════
_TABLERO = None          # módulo tasks_board cacheado: se carga una sola vez


def _tablero():
    """Devuelve el módulo de la skill tasks_board (carpeta hermana).

    Los rangos («del miércoles al domingo», «del 5 al 9 de agosto»), la limpieza
    del título y el cuerpo que espera Google ya están resueltos y probados ahí:
    se importan en vez de repetir aquí las mismas expresiones regulares.
    `from skills.tasks_board import skill` NO sirve: skills_loader carga cada
    skill con spec_from_file_location y `skills` no es un paquete importable."""
    global _TABLERO
    if _TABLERO is None:
        import importlib.util
        ruta = Path(__file__).resolve().parents[1] / "tasks_board" / "skill.py"
        spec = importlib.util.spec_from_file_location("skills.tasks_board", ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TABLERO = mod
    return _TABLERO


# El verbo y el «un evento / una cita» que lo acompañan: son la orden, no el asunto.
# El \b tras «de» es obligatorio: sin él, «crea un evento DEL 5 al 9» perdía la
# «de» de «del», el rango dejaba de reconocerse y solo se guardaba una fecha.
_DISPARADOR_RX = re.compile(
    r"^\s*(?:crea(?:me)?|a[ñn][aá]de(?:me)?|agr[eé]ga(?:me)?|ap[uú]nta(?:me)?|"
    r"ag[eé]nda(?:me)?|pon(?:me)?|mete(?:me)?)\s+(?:un\s+|una\s+)?"
    r"(?:evento|cita|reuni[oó]n|recordatorio)?\s*(?:(?:de|para)\b|:)?\s*", re.IGNORECASE)

# Fechas sueltas («el jueves», «25/07», «5 de agosto») fuera del título.
_FECHA_SUELTA_RX = re.compile(
    r"\b(?:el\s+|para\s+el\s+|para\s+|este\s+|pr[oó]ximo\s+)?"
    r"(?:hoy|ma[ñn]ana|pasado\s+ma[ñn]ana|lunes|martes|mi[eé]rcoles|jueves|"
    r"viernes|s[aá]bado|domingo|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
    r"\d{1,2}\s+de\s+\w+)\b", re.IGNORECASE)

# «el evento Festival Sonorama» → el asunto es el festival; «evento» es el
# continente. El lookahead deja fuera «la cita CON el dentista» y «la reunión DE
# equipo», donde esa palabra SÍ es parte del asunto.
_GENERICO_RX = re.compile(
    r"^(?:el|la|un|una)\s+(?:evento|cita|reuni[oó]n|recordatorio)\s+"
    r"(?!(?:con|de|del|para|en|entre|sobre|a|al)\b)", re.IGNORECASE)


def _titulo_evento(resto: str, tb) -> str:
    """Deja solo el asunto: quita el continente («el evento», «la cita») y el
    relleno que ya sabe limpiar el tablero («que dure», conectores colgados)."""
    return tb._limpia_titulo(_GENERICO_RX.sub("", (resto or "").strip(), count=1))


def _datos_evento(text: str) -> tuple[str, str | None, str | None, bool, str]:
    """De la orden saca (titulo, start, end, all_day, ultimo_dia).

    `ultimo_dia` es el último día del rango INCLUSIVE ('' si el evento ocupa un
    solo día): Google quiere el fin exclusivo, pero el tablero guarda el último
    día real. start/end en ISO; start es None si no hay fecha entendible."""
    tb = _tablero()
    cuerpo = _DISPARADOR_RX.sub("", text, count=1)
    cuerpo = re.sub(r"\b(?:al|en\s+(?:el|mi|google))\s+calendario\b", "",
                    cuerpo, flags=re.IGNORECASE)
    resto, hora = tb._extract_time(cuerpo)
    resto, ini, fin = tb._extract_range(resto)
    if ini and fin:
        start, end, all_day = tb._cuerpo_evento(ini, hora or "", fin)
        return _titulo_evento(resto, tb), start, end, all_day, fin
    # Sin rango manda el parser de siempre: una fecha con hora dura una hora y
    # una fecha pelada ocupa el día entero.
    titulo = _titulo_evento(_TIME_RX.sub("", _FECHA_SUELTA_RX.sub("", cuerpo)), tb)
    when = _parse_when(text)
    if not when:
        return titulo, None, None, False, ""
    start, end, all_day = when
    return titulo, start, end, all_day, ""


def _create_event(summary: str, start: str, end: str | None = None,
                  description: str = "", all_day: bool = False) -> str:
    """Crea un evento REAL en el calendario principal. Devuelve el enlace."""
    from googleapiclient.discovery import build
    svc = build("calendar", "v3", credentials=_get_creds(), cache_discovery=False)
    if all_day:
        d0 = dt.date.fromisoformat(start)
        body = {"summary": summary, "description": description,
                "start": {"date": start},
                "end": {"date": end or (d0 + dt.timedelta(days=1)).isoformat()}}
    else:
        body = {"summary": summary, "description": description,
                "start": {"dateTime": start, "timeZone": _TZ},
                "end": {"dateTime": end or start, "timeZone": _TZ}}
    ev = svc.events().insert(calendarId="primary", body=body).execute()
    return ev.get("htmlLink", "")


def _create_task(title: str, due_date: str | None = None, notes: str = "") -> str:
    """Crea una tarea REAL en Google Tasks (lista por defecto). due_date = YYYY-MM-DD."""
    from googleapiclient.discovery import build
    svc = build("tasks", "v1", credentials=_get_creds(), cache_discovery=False)
    body: dict = {"title": title[:1000]}
    if notes:
        body["notes"] = notes[:2000]
    if due_date:
        # Google Tasks quiere RFC3339; usa solo la parte de fecha.
        body["due"] = f"{due_date}T00:00:00.000Z"
    t = svc.tasks().insert(tasklist="@default", body=body).execute()
    return t.get("id", "")


def _create_everywhere(title: str, due_date: str | None, notes: str,
                       priority: str = "alta") -> str:
    """Crea la tarea en GOOGLE (Calendar si hay fecha, si no Tasks) Y en el TABLERO
    INTERNO de nexus. Devuelve un texto con los destinos donde quedó guardada."""
    dests = []
    try:
        if due_date:
            _create_event(title, due_date, None, notes, all_day=True)
            dests.append("Google Calendar")
        else:
            _create_task(title, None, notes)
            dests.append("Google Tasks (To-Do)")
    except Exception as exc:                                   # noqa: BLE001
        dests.append(f"(Google falló: {type(exc).__name__})")
    try:
        from backend.core.dominio import board
        board.add_task(title, due=due_date, priority=priority, tag="correo")
        dests.append("tablero interno")
    except Exception as exc:                                   # noqa: BLE001
        dests.append(f"(tablero falló: {type(exc).__name__})")
    return " + ".join(dests) if dests else "ningún destino"


async def _email_urgent_job(ctx, channel: str) -> dict:
    """URGENTES EN 2º PLANO: lee los no-leídos con cuerpo, decide con el LLM cuáles
    corren prisa y AVISA al terminar por el canal de origen (chat + voz en el PC,
    Telegram si vino de ahí). Regla de Adri: TODO lo de segundo plano avisa al acabar."""
    global _last_emails
    from backend.core.comun.events import bus
    try:
        msgs, unread, total = await _load_unread_bodies(30)
        if not unread:
            reply = "✅ Revisión terminada: 0 sin leer, nada urgente."
            corto = "Revisión terminada: nada urgente."
        else:
            _last_emails = msgs
            analysis, sin_clasificar = await _analyze_emails(msgs)
            urg = [(msgs[a["i"]], a) for a in analysis if a.get("urgente")]
            ambito = ("" if len(msgs) >= unread
                      else f" (analizados los {len(msgs)} más recientes)")
            # NO SABER no es NO HAY. Si el modelo se ha dejado correos, se dice:
            # callarlo es lo que hizo que una alerta de seguridad pasara por
            # «nada urgente» el 31/07/2026.
            fallo = ""
            if sin_clasificar:
                fallo = (f"\n\n⚠️ Y ojo: {len(sin_clasificar)} de {len(msgs)} no he podido "
                         "clasificarlos (el modelo no devolvió respuesta válida). No digo "
                         "que no corran prisa; digo que NO LOS HE MIRADO. Si quieres, "
                         "vuelve a pedírmelo o baja «por_lote» en config/umbrales.json.")
            if len(sin_clasificar) == len(msgs):
                reply = (f"❌ No he podido analizar NINGUNO de tus {unread} correos sin leer: "
                         "el modelo no ha devuelto una clasificación válida. No te digo que "
                         "no haya nada urgente, porque no lo sé.")
                corto = "No he podido analizar los correos. No te fíes."
            elif not urg:
                reply = (f"✅ Revisión terminada: de tus {unread} sin leer{ambito}, "
                         "ninguno parece urgente." + fallo)
                corto = (f"Revisión terminada: {unread} sin leer y nada urgente."
                         if not sin_clasificar else
                         f"Nada urgente, pero {len(sin_clasificar)} se han quedado sin analizar.")
            else:
                lines = [f"🔴 {m['from']} — «{m['subject']}»" +
                         (f" · {a.get('motivo','')}" if a.get('motivo') else "")
                         for m, a in urg]
                reply = (f"✅ Revisión terminada — de tus {unread} sin leer{ambito}, "
                         f"{len(urg)} urgente(s):\n" + "\n".join(lines) + fallo +
                         "\n\n¿Te creo tareas para tratarlos? Di «crea tareas de lo importante del correo».")
                corto = f"Revisión terminada: {len(urg)} urgentes de {unread} sin leer."
    except Exception as exc:                                   # noqa: BLE001
        reply = f"❌ La revisión de urgentes ha fallado: {type(exc).__name__}: {exc}"
        corto = "La revisión de correos ha fallado."
    await bus.emit("chat", {"user": "[correos urgentes]", "reply": reply,
                            "provider": "minion:google_workspace",
                            "skill": "google_workspace", "channel": channel})
    if channel == "pc":
        try:
            from backend.core.infraestructura import tts
            await tts.speak(corto)
        except Exception:
            pass
    if channel == "telegram":
        try:
            from backend.core.infraestructura.telegram_bridge import send_telegram
            await send_telegram(reply)
        except Exception:
            pass
    return {"reply": reply}


async def _email_actions_job(ctx, channel: str) -> dict:
    """ANÁLISIS DE CORREOS EN SEGUNDO PLANO (orden de Adri: «analiza» = hazlo por
    detrás y ACTÚA). Lee no-leídos, decide accionables con el LLM, crea tareas
    (Google + tablero) y entrega el resultado por el CANAL de origen."""
    global _last_emails
    from backend.core.comun.events import bus
    try:
        msgs, unread, total = await _load_unread_bodies(30)
        if not unread:
            reply = "He revisado la bandeja: sin correos nuevos, nada que convertir en tareas."
        else:
            _last_emails = msgs
            analysis, sin_clasificar = await _analyze_emails(msgs)
            acts = [(msgs[a["i"]], a) for a in analysis if a.get("accionable")]
            # Igual que en la revisión de urgentes: lo que no se ha mirado se dice.
            # Aquí encima duele el doble, porque «no accionable» = no se crea tarea.
            fallo = ("" if not sin_clasificar else
                     f"\n\n⚠️ {len(sin_clasificar)} de {len(msgs)} se han quedado SIN "
                     "clasificar (el modelo no devolvió respuesta válida): de esos no he "
                     "creado tarea, y no porque no la merezcan.")
            if len(sin_clasificar) == len(msgs):
                reply = (f"❌ No he podido analizar NINGUNO de tus {unread} correos sin leer, "
                         "así que no he creado ninguna tarea. El modelo no devolvió una "
                         "clasificación válida.")
            elif not acts:
                ambito = "" if len(msgs) >= unread else f" (los {len(msgs)} más recientes)"
                reply = (f"He analizado tus {unread} correos sin leer{ambito} y ninguno pide "
                         "una acción concreta: no he creado tareas." + fallo)
            else:
                creadas = []
                for m, a in acts:
                    titulo = (a.get("tarea") or "").strip() or f"Tratar correo de {m['from']}: {m['subject']}"
                    fecha = (a.get("fecha") or "").strip() or None
                    prio = "alta" if (a.get("urgente") or a.get("importancia") == "alta") else "media"
                    notas = f"De {m['from']} — Asunto: {m['subject']}"
                    destinos = await asyncio.to_thread(_create_everywhere, titulo, fecha, notas, prio)
                    creadas.append((titulo, fecha, destinos))
                lines = [f"• {t}" + (f" (para {f})" if f else "") + f"  → {d}" for t, f, d in creadas]
                n_ok = sum(1 for _t2, _f2, d in creadas
                           if ("tablero interno" in d) or ("Google" in d and "falló" not in d))
                if n_ok == 0:
                    reply = (f"Análisis hecho, preparé {len(creadas)} tarea(s)… pero NO pude "
                             "GUARDAR ninguna:\n" + "\n".join(lines) +
                             "\n\nCasi seguro falta aceptar la autorización de ESCRITURA de "
                             "Google en el navegador del PC.")
                else:
                    aviso = ""
                    if not any("Google" in d and "falló" not in d for _t2, _f2, d in creadas):
                        aviso = ("\n\n⚠ En Google no pude guardarlas (autorización pendiente); "
                                 "en tu tablero SÍ están.")
                    reply = (f"Análisis de correos terminado — {n_ok} tarea(s) creadas:\n"
                             + "\n".join(lines) + aviso + fallo)
    except Exception as exc:                                   # noqa: BLE001
        reply = f"El análisis de correos ha fallado: {type(exc).__name__}: {exc}"
    await bus.emit("chat", {"user": "[análisis de correos]", "reply": reply,
                            "provider": "minion:google_workspace",
                            "skill": "google_workspace", "channel": channel})
    # AVISO al terminar (regla de Adri: todo lo de 2º plano avisa). Voz en el PC.
    if channel == "pc":
        try:
            from backend.core.infraestructura import tts
            await tts.speak("Análisis de correos terminado.")
        except Exception:
            pass
    if channel == "telegram":
        try:
            from backend.core.infraestructura.telegram_bridge import send_telegram
            await send_telegram(reply)
        except Exception:
            pass
    return {"reply": reply}


def _parse_json_array(raw: str, n: int) -> list:
    """Extrae un array JSON de la respuesta del LLM (tolera ```json y texto alrededor)."""
    import json
    t = (raw or "").strip()
    t = re.sub(r"```(?:json)?", "", t).strip().strip("`").strip()
    m = re.search(r"\[.*\]", t, re.DOTALL)
    if m:
        t = m.group(0)
    try:
        data = json.loads(t)
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# LA RED QUE HAY DEBAJO DEL MODELO
#
# 31/07/2026. Adri: «no ha sido capaz de un mail que pone alert marcarlo como
# urgente». Cierto, y el motivo no era el modelo: era la CANTIDAD. Los 30
# no-leídos se mandaban en UNA llamada (22.000 caracteres). Ollama corta el
# prompt a 4096 tokens por defecto, el modelo se salía del formato y contestaba
# en prosa. `_parse_json_array` no encontraba array, devolvía [] — y arriba se
# leía como «cero urgentes» y se respondía «ninguno parece urgente».
#
# Ese es el pecado de verdad: NO SABER != NO HAY. Ahora son tres cosas:
#   1. se trocea en lotes (el modelo acierta con 6, se ahoga con 30),
#   2. las marcas de config/umbrales.json fuerzan urgente pase lo que pase,
#   3. lo que no se ha podido clasificar SE DICE, no se da por tranquilo.
# ─────────────────────────────────────────────────────────────────────────────
_CORREOS_RESERVA = {
    "por_lote": 6,
    "por_lote_por_proveedor": {"ollama": 6, "openai": 30, "anthropic": 30,
                               "gemini": 30, "cloud": 30},
    "marcas_urgentes": ["[alerta]", "[urgente]", "[urgent]", "[critico]", "[critical]",
                        "alerta de seguridad", "security alert", "acceso no autorizado",
                        "intento de acceso", "actividad sospechosa",
                        "suspension de cuenta", "pago rechazado", "factura vencida"],
}


def _entero(v, minimo: int, maximo: int) -> int | None:
    """Un entero de configuración dentro de rango, o None si no vale."""
    if isinstance(v, int) and not isinstance(v, bool) and minimo <= v <= maximo:
        return v
    return None


def _carga_correos() -> dict:
    """Lee la sección «correos» de config/umbrales.json sobre los de reserva.
    Un JSON roto no puede dejar la bandeja sin red: se cae a los de reserva."""
    vals = dict(_CORREOS_RESERVA)
    vals["por_lote_por_proveedor"] = dict(_CORREOS_RESERVA["por_lote_por_proveedor"])
    try:
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            import json
            leido = (json.loads(f.read_text(encoding="utf-8")) or {}).get("correos") or {}
            n = _entero(leido.get("por_lote"), 1, 60)
            if n:
                vals["por_lote"] = n
            tabla = leido.get("por_lote_por_proveedor")
            if isinstance(tabla, dict):
                for prov, v in tabla.items():
                    n = _entero(v, 1, 60)
                    if n:
                        vals["por_lote_por_proveedor"][str(prov).strip().lower()] = n
            marcas = leido.get("marcas_urgentes")
            if isinstance(marcas, list):
                limpias = [str(x).strip() for x in marcas if str(x).strip()]
                if limpias:                    # una lista vacía es casi seguro un descuido
                    vals["marcas_urgentes"] = limpias
    except Exception:
        pass
    return vals


def _por_lote() -> int:
    """Correos por llamada, según el proveedor que haya puesto AHORA MISMO.

    Se resuelve en cada análisis, no al importar: Adri cambia de modelo desde la
    rueda de ajustes y sería absurdo tener que reiniciar para que el tamaño de
    lote se entere. El 6 se midió con qwen3:8b, que se ahoga con 30 de golpe; un
    modelo de nube con ventana grande se los traga en una sola llamada.

    Si el proveedor no está en la tabla, se usa el valor prudente (el pequeño):
    con un modelo desconocido, mejor cinco llamadas de más que una alerta menos."""
    prov = "ollama"
    try:
        from backend.core.comun.config import settings
        prov = str(settings.get("llm_provider", "ollama") or "ollama").strip().lower()
    except Exception:
        pass                                   # sin ajustes legibles, el prudente
    return _CORREOS["por_lote_por_proveedor"].get(prov, _CORREOS["por_lote"])


def _sin_tildes(s: str) -> str:
    """«CRÍTICO» → «critico». Para comparar marcas sin depender de cómo se teclee."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn")


def _marca_urgente(m: dict) -> str:
    """La marca que dispara en el remitente o el asunto, o "" si ninguna.
    Deliberadamente NO mira el cuerpo: un boletín que cite «alerta de seguridad»
    en un párrafo no es una alerta, y llenar esto de falsos positivos lo mata."""
    campo = _sin_tildes(f'{m.get("from", "")} {m.get("subject", "")}')
    for marca in _CORREOS["marcas_urgentes"]:
        if _sin_tildes(marca) in campo:
            return marca
    return ""


_CORREOS = _carga_correos()


async def _analyze_emails(msgs: list[dict]) -> tuple[list[dict], list[int]]:
    """Clasifica CADA correo: urgente, importancia, accionable, tarea y fecha.

    Devuelve (análisis, sin_clasificar). **Hay que mirar el segundo valor**: son
    los índices que ni el modelo clasificó ni tienen marca. Tratarlos como «no
    urgentes» es exactamente el fallo del 31/07/2026."""
    por_lote = max(1, _por_lote())
    por_indice: dict[int, dict] = {}
    for ini in range(0, len(msgs), por_lote):
        lote = msgs[ini:ini + por_lote]
        for a in await _analyze_batch(lote):
            por_indice[ini + a["i"]] = {**a, "i": ini + a["i"]}   # reíndice al global

    # La red: la marca manda sobre el modelo, y sirve aunque el modelo no conteste.
    for i, m in enumerate(msgs):
        marca = _marca_urgente(m)
        if not marca:
            continue
        a = por_indice.get(i)
        if a is None:                          # el modelo ni lo miró: lo levantamos nosotros
            por_indice[i] = {"i": i, "urgente": True, "importancia": "alta",
                             "accionable": True, "fecha": "",
                             "tarea": f"Revisar correo de {m.get('from', '')}: {m.get('subject', '')}"[:120],
                             "motivo": f"marca «{marca}» en el asunto"}
        elif not a.get("urgente"):             # dijo que no; la marca pesa más
            a["urgente"] = True
            a["importancia"] = "alta"
            a["motivo"] = (f"marca «{marca}» en el asunto"
                           + (f" · el modelo decía: {a['motivo']}" if a.get("motivo") else ""))

    sin_clasificar = [i for i in range(len(msgs)) if i not in por_indice]
    return [por_indice[i] for i in sorted(por_indice)], sin_clasificar


async def _analyze_batch(msgs: list[dict]) -> list[dict]:
    """Una sola llamada al modelo con UN LOTE. Índices LOCALES al lote."""
    from backend.core.infraestructura import llm
    partes = []
    for i, m in enumerate(msgs):
        cuerpo = (m.get("body") or m.get("snippet") or "")[:700]
        partes.append(f'[{i}] De: {m["from"]}\nAsunto: {m["subject"]}\nContenido: {cuerpo}')
    digest = "\n\n".join(partes)
    hoy = dt.date.today().isoformat()
    system = (
        f"Eres un clasificador de correos. Hoy es {hoy}. Analiza CADA correo por su CONTEXTO "
        "(asunto + contenido), no por palabras sueltas. Devuelve SOLO un JSON válido: un array "
        "con un objeto por correo, en el MISMO orden, con estas claves exactas: "
        '{"i": entero (índice del correo), "urgente": true|false, "importancia": "alta"|"media"|"baja", '
        '"accionable": true|false, "tarea": "título breve en imperativo de lo que hay que hacer, o cadena vacía", '
        '"fecha": "YYYY-MM-DD si el correo implica una fecha/plazo, o cadena vacía", '
        '"motivo": "5-10 palabras"}. '
        "urgente = necesita atención hoy/mañana, hay un plazo inminente, o hay consecuencias por no actuar. "
        "accionable = el correo te pide hacer algo concreto (pagar, responder, revisar, confirmar, agendar). "
        "NO inventes fechas: pon fecha solo si aparece o se implica claramente. Responde ÚNICAMENTE el JSON, sin texto extra."
    )
    try:
        raw, _prov = await llm.ask_llm(digest, system=system)
    except Exception:
        return []
    out = _parse_json_array(raw, len(msgs))
    # saneado: quedarnos con índices válidos
    clean = []
    for a in out:
        try:
            idx = int(a.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(msgs):
            clean.append({**a, "i": idx})
    return clean


async def _load_unread_bodies(max_n: int = 30) -> tuple[list[dict], int, int | None]:
    """Trae los NO leídos con su CUERPO leído (para poder analizar por contexto)."""
    unread, total = await asyncio.to_thread(_count_unread)
    if not unread:
        return [], 0, total
    msgs = await asyncio.to_thread(_fetch_emails, min(unread, max_n), True)
    for m in msgs:
        try:
            m["body"] = await asyncio.to_thread(_read_email, m["id"])
        except Exception:
            m["body"] = m.get("snippet", "")
    return msgs, unread, total


def _parse_send(text: str) -> tuple[str, str, str]:
    """Extrae (destinatario, asunto, cuerpo) de una orden en lenguaje natural:
    «envía un correo a x@y.com con asunto Reunión diciendo que llego tarde»."""
    to_m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
    to = to_m.group(0) if to_m else ""
    subj_m = re.search(
        r"con\s+(?:el\s+)?asunto\s+[«\"']?([^«»\"'\n]+?)[»\"']?"
        r"(?=\s+(?:dici[eé]ndo|que\s+diga|con\s+el\s+(?:texto|cuerpo|mensaje)|y\s+(?:cuerpo|texto)|:)|$)",
        text, re.IGNORECASE)
    subject = subj_m.group(1).strip() if subj_m else ""
    body_m = re.search(
        r"(?:dici[eé]ndo(?:le|les)?\s+(?:que\s+)?|que\s+(?:le\s+)?diga\s+(?:que\s+)?"
        r"|con\s+el\s+(?:texto|cuerpo|mensaje)\s+|(?:cuerpo|texto|mensaje):\s*)(.+)$",
        text, re.IGNORECASE | re.DOTALL)
    body = body_m.group(1).strip() if body_m else ""
    return to, subject, body


async def _llm_text(order: str) -> str:
    """Pide texto al cerebro de nexus; '' si solo está el mock."""
    try:
        from backend.core.infraestructura import llm
        reply, prov = await llm.ask_llm(order)
        if prov != "mock" and reply:
            return reply.strip()
    except Exception:
        pass
    return ""


# ── GOOGLE DRIVE ─────────────────────────────────────────────────────────────
# Para qué existe esto: el informe diario de competencia se genera en .md, se manda
# por correo (_send_gmail) y se sube AQUÍ, para que después ChatGPT o Claude —que
# están conectados a ese Drive— trabajen sobre él. Sin esta pieza el ciclo se corta
# en el correo y hay que subir el archivo a mano todos los días.
#
# Todo lo de abajo está escrito contra el discovery doc oficial de drive.v3
# (rev. 20260428, el que trae google-api-python-client) y la guía de búsqueda de
# Google. Nada de nombres de campo de memoria: files.create + files.list, el
# mimeType de carpeta «application/vnd.google-apps.folder», y el operador `q` con
# la sintaxis `name = 'x' and mimeType = '...' and trashed = false`.

DRIVE_CARPETA_RESERVA = "nexus"          # solo si umbrales.json falta o está roto
DRIVE_MIME_CARPETA = "application/vnd.google-apps.folder"
DRIVE_RAIZ = "root"                 # id literal que Drive acepta para «Mi unidad»
DRIVE_PALABRAS_RAIZ = {"raíz", "raiz", "root", "mi unidad", "mi drive", "drive"}
# Campos que se piden SIEMPRE. Sin `fields` la API devuelve un puñado mínimo y
# faltarían `parents` (imprescindible para mover) o `webViewLink`.
DRIVE_CAMPOS = "id, name, mimeType, parents, webViewLink, modifiedTime, size"
DRIVE_CAMPOS_LISTA = f"files({DRIVE_CAMPOS})"
# Exportación de los formatos nativos de Google (Docs/Sheets/Slides no se
# descargan con alt=media: hay que pasar por files.export). Tabla oficial de
# «Export MIME types for Google Workspace documents».
DRIVE_EXPORTACION = {
    "application/vnd.google-apps.document": ("text/markdown", ".md"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


class DriveNoEncontrado(LookupError):
    """El nombre que dijo el usuario no existe en su Drive. Se DICE, no se adivina:
    con el scope completo, «parecido» sería tocar un documento real equivocado."""
REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"

_ultimo_subido: dict = {}                # id/enlace de lo último que subió nexus


def _umbrales_drive() -> dict:
    """Lee la sección «drive» de config/umbrales.json. El nombre de la carpeta NO
    está a fuego en el código a propósito: si mañana se quiere que los informes
    caigan en «Informes nexus» o en «CONTENIDO», se cambia una línea del JSON y ya,
    sin tocar Python ni volver a autorizar nada."""
    vals = {"carpeta": DRIVE_CARPETA_RESERVA}
    try:
        import json as _j
        f = CONFIG_DIR / "umbrales.json"
        if f.is_file():
            leido = (_j.loads(f.read_text(encoding="utf-8")) or {}).get("drive") or {}
            if isinstance(leido.get("carpeta"), str) and leido["carpeta"].strip():
                vals["carpeta"] = leido["carpeta"].strip()
    except Exception:
        pass                              # archivo roto → reserva, nunca reventar
    return vals


def _drive_escape(valor: str) -> str:
    """Escapa un literal para el parámetro `q`. Google lo dice explícitamente: la
    comilla simple y la contrabarra se escapan con contrabarra. Sin esto, una
    carpeta llamada «Adri's» genera una consulta rota (error 400) en vez de una
    búsqueda que no encuentra nada, que es peor porque parece un fallo de red."""
    return valor.replace("\\", "\\\\").replace("'", "\\'")


def _drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_creds(), cache_discovery=False)


def _drive_carpeta_id(svc, nombre: str, padre: str = "", crear: bool = True) -> str:
    """Id de una carpeta, que puede ser una RUTA anidada tipo «Clientes/2026/agosto».

    Cada tramo se busca DENTRO del anterior (`'<id>' in parents`); el primero se
    busca en todo el Drive, que es lo que hace que ahora sí valga una carpeta que
    creaste tú a mano. `crear=False` para las operaciones de LECTURA: listar o
    buscar en una carpeta que no existe NO debe crearla de rebote — devuelve "".
    «raíz»/«root»/«mi drive» apuntan a la raíz real (el id literal es "root")."""
    actual = padre
    for tramo in [t.strip() for t in str(nombre).replace("\\", "/").split("/") if t.strip()]:
        if tramo.lower() in DRIVE_PALABRAS_RAIZ:
            actual = DRIVE_RAIZ
            continue
        q = (f"name = '{_drive_escape(tramo)}' and mimeType = '{DRIVE_MIME_CARPETA}' "
             f"and trashed = false")
        if actual:
            q += f" and '{_drive_escape(actual)}' in parents"
        res = svc.files().list(q=q, spaces="drive", pageSize=10,
                               fields="files(id, name)",
                               supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute()
        encontradas = res.get("files", [])
        if encontradas:
            actual = encontradas[0]["id"]
            continue
        if not crear:
            return ""
        cuerpo = {"name": tramo, "mimeType": DRIVE_MIME_CARPETA}
        if actual:
            cuerpo["parents"] = [actual]
        actual = svc.files().create(body=cuerpo, fields="id",
                                    supportsAllDrives=True).execute()["id"]
    return actual or DRIVE_RAIZ


def _drive_subir(ruta: Path, carpeta: str = "", mimetype: str = "") -> dict:
    """Sube un fichero a la carpeta configurada y devuelve id, nombre y enlace.

    `resumable=True` a propósito: un informe de competencia con imágenes o varios
    cientos de KB por una conexión doméstica es justo el caso en el que una subida
    simple se corta a la mitad y hay que empezar de cero."""
    from googleapiclient.http import MediaFileUpload
    nombre_carpeta = carpeta or _umbrales_drive()["carpeta"]
    svc = _drive_service()
    padre = _drive_carpeta_id(svc, nombre_carpeta)
    mime = mimetype or _drive_mime(ruta)
    media = MediaFileUpload(str(ruta), mimetype=mime, resumable=True)
    try:
        creado = svc.files().create(
            body={"name": ruta.name, "parents": [padre]},
            media_body=media,
            # webViewLink es el enlace «para abrirlo en el navegador»; es el que hay
            # que pegarle a ChatGPT/Claude. webContentLink es de descarga directa y
            # NO sirve para eso.
            fields="id, name, webViewLink, mimeType, size",
            supportsAllDrives=True).execute()
    finally:
        # MediaFileUpload deja el fichero ABIERTO y solo lo cierra en su __del__.
        # En Windows eso significa que, mientras el objeto siga vivo, el .md queda
        # bloqueado y nadie puede moverlo ni reescribirlo. Se cierra a mano, que es
        # de las cosas que se descubren tarde y siempre con el informe del día.
        try:
            media.stream().close()
        except Exception:
            pass
    creado["carpeta"] = nombre_carpeta
    return creado


def _drive_mime(ruta: Path) -> str:
    """text/markdown para los .md (RFC 7763). Se pone a mano porque el mimetypes de
    Python NO conoce .md y devolvería None → Drive lo guardaría como binario y
    ChatGPT/Claude no sabrían leerlo."""
    ext = ruta.suffix.lower()
    if ext in (".md", ".markdown"):
        return "text/markdown"
    import mimetypes
    return mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"


def _drive_listar(limite: int = 10, carpeta: str = "") -> list[dict]:
    """El contenido de una carpeta, lo más reciente primero. Con el scope completo
    vale CUALQUIER carpeta del Drive, no solo la de nexus. `crear=False`: listar
    nunca debe crear la carpeta que buscabas (eso sería inventarse la respuesta)."""
    nombre_carpeta = carpeta or _umbrales_drive()["carpeta"]
    svc = _drive_service()
    padre = _drive_carpeta_id(svc, nombre_carpeta, crear=False)
    if not padre:
        return []
    res = svc.files().list(
        q=f"'{_drive_escape(padre)}' in parents and trashed = false",
        spaces="drive", pageSize=max(1, min(limite, 50)),
        orderBy="modifiedTime desc",
        fields=DRIVE_CAMPOS_LISTA,
        supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    return res.get("files", [])


# ── CRUD: localizar, buscar, crear, mover, renombrar, reemplazar, descargar ──
def _drive_localizar(svc, nombre: str, carpeta: str = "") -> list[dict]:
    """Ficheros o carpetas con ese nombre EXACTO. Exacto y no «parecido» a
    propósito: tocar el documento equivocado de un Drive real no se deshace solo."""
    q = f"name = '{_drive_escape(nombre)}' and trashed = false"
    if carpeta:
        padre = _drive_carpeta_id(svc, carpeta, crear=False)
        if not padre:
            return []
        q += f" and '{_drive_escape(padre)}' in parents"
    res = svc.files().list(q=q, spaces="drive", pageSize=10, orderBy="modifiedTime desc",
                           fields=DRIVE_CAMPOS_LISTA, supportsAllDrives=True,
                           includeItemsFromAllDrives=True).execute()
    return res.get("files", [])


def _drive_uno(svc, nombre: str, carpeta: str = "") -> dict:
    hallados = _drive_localizar(svc, nombre, carpeta)
    if not hallados:
        raise DriveNoEncontrado(nombre)
    return hallados[0]


def _drive_buscar(texto: str = "", tipo: str = "", carpeta: str = "",
                  limite: int = 15) -> list[dict]:
    """Búsqueda por trozo de nombre y/o tipo. `contains` es el operador de la guía
    oficial de búsqueda de Drive; `=` sería nombre exacto y aquí queremos aproximar."""
    svc = _drive_service()
    partes = ["trashed = false"]
    if texto:
        partes.append(f"name contains '{_drive_escape(texto)}'")
    if tipo == "carpeta":
        partes.append(f"mimeType = '{DRIVE_MIME_CARPETA}'")
    elif tipo:
        partes.append(f"mimeType contains '{_drive_escape(tipo)}'")
    if carpeta:
        padre = _drive_carpeta_id(svc, carpeta, crear=False)
        if not padre:
            return []
        partes.append(f"'{_drive_escape(padre)}' in parents")
    res = svc.files().list(q=" and ".join(partes), spaces="drive",
                           pageSize=max(1, min(limite, 50)), orderBy="modifiedTime desc",
                           fields=DRIVE_CAMPOS_LISTA, supportsAllDrives=True,
                           includeItemsFromAllDrives=True).execute()
    return res.get("files", [])


def _drive_crear_carpeta(ruta: str) -> dict:
    """Crea la carpeta (y los tramos intermedios que falten si es una ruta a/b/c)."""
    svc = _drive_service()
    fid = _drive_carpeta_id(svc, ruta, crear=True)
    return svc.files().get(fileId=fid, fields=DRIVE_CAMPOS,
                           supportsAllDrives=True).execute()


def _drive_mover(nombre: str, destino: str = "") -> dict:
    """files.update con addParents/removeParents: mover NO es borrar y crear, es
    cambiar de padre. No es destructivo, así que va directo, sin confirmación."""
    svc = _drive_service()
    f = _drive_uno(svc, nombre)
    padre_nuevo = _drive_carpeta_id(svc, destino or _umbrales_drive()["carpeta"])
    viejos = ",".join(f.get("parents") or [])
    movido = svc.files().update(fileId=f["id"], addParents=padre_nuevo,
                                removeParents=viejos or None, fields=DRIVE_CAMPOS,
                                supportsAllDrives=True).execute()
    movido["destino"] = destino or _umbrales_drive()["carpeta"]
    return movido


def _drive_renombrar(nombre: str, nuevo: str) -> dict:
    svc = _drive_service()
    f = _drive_uno(svc, nombre)
    return svc.files().update(fileId=f["id"], body={"name": nuevo},
                              fields=DRIVE_CAMPOS, supportsAllDrives=True).execute()


def _drive_reemplazar(nombre: str, ruta: Path) -> dict:
    """Sustituye el CONTENIDO de un fichero que ya está en Drive conservando su id
    (y por tanto su enlace, que es lo que le has pegado a ChatGPT/Claude)."""
    from googleapiclient.http import MediaFileUpload
    svc = _drive_service()
    f = _drive_uno(svc, nombre)
    media = MediaFileUpload(str(ruta), mimetype=_drive_mime(ruta), resumable=True)
    try:
        return svc.files().update(fileId=f["id"], media_body=media, fields=DRIVE_CAMPOS,
                                  supportsAllDrives=True).execute()
    finally:
        try:                              # ver el comentario de _drive_subir
            media.stream().close()
        except Exception:
            pass


def _drive_dentro(svc, fid: str, limite: int = 100) -> int:
    """Cuántos elementos hay dentro de una carpeta. Sirve para AVISAR antes de
    borrarla: vaciar una carpeta en silencio es exactamente lo que no se hace."""
    res = svc.files().list(q=f"'{_drive_escape(fid)}' in parents and trashed = false",
                           spaces="drive", pageSize=max(1, min(limite, 100)),
                           fields="files(id, name)", supportsAllDrives=True,
                           includeItemsFromAllDrives=True).execute()
    return len(res.get("files", []))


def _drive_descargar(nombre: str, destino_dir: Path) -> Path:
    """Baja un fichero de Drive al disco. Los formatos nativos de Google (Docs,
    Sheets, Slides) NO se bajan con alt=media: hay que exportarlos (files.export)."""
    from googleapiclient.http import MediaIoBaseDownload
    svc = _drive_service()
    f = _drive_uno(svc, nombre)
    mime = f.get("mimeType", "")
    if mime == DRIVE_MIME_CARPETA:
        raise IsADirectoryError(f.get("name", nombre))
    nombre_final = f.get("name") or nombre
    if mime.startswith("application/vnd.google-apps"):
        exp, ext = DRIVE_EXPORTACION.get(mime, ("application/pdf", ".pdf"))
        peticion = svc.files().export_media(fileId=f["id"], mimeType=exp)
        if not nombre_final.lower().endswith(ext):
            nombre_final += ext
    else:
        peticion = svc.files().get_media(fileId=f["id"])
    destino_dir.mkdir(parents=True, exist_ok=True)
    salida = destino_dir / nombre_final
    with open(salida, "wb") as fh:
        bajada = MediaIoBaseDownload(fh, peticion)
        terminado = False
        while not terminado:
            _, terminado = bajada.next_chunk()
    return salida


# Los dos borrados reciben el fichero YA LOCALIZADO, no un nombre. A propósito:
# si volvieran a buscarlo, entre el aviso («esta carpeta tiene 3 cosas dentro»)
# y el «sí» del usuario podría haber aparecido otro fichero con ese nombre y se
# borraría uno distinto del que se le enseñó. Se borra EL id que se le enseñó.
def _drive_a_papelera(f: dict) -> dict:
    """BORRADO POR DEFECTO: `trashed = true`, que es REVERSIBLE desde
    drive.google.com/drive/trash. Nunca files.delete por defecto — regla del
    proyecto tras el incidente del tablero, y con el Drive entero aún más."""
    return _drive_service().files().update(
        fileId=f["id"], body={"trashed": True},
        fields="id, name, mimeType, trashed", supportsAllDrives=True).execute()


def _drive_destruir(f: dict) -> dict:
    """files.delete: DEFINITIVO, no pasa por la papelera, no hay vuelta atrás.
    NO SE LLAMA NUNCA DESDE handle() DIRECTAMENTE: solo desde dentro del
    `action` de un confirm.request(), igual que board.purge_trash() y purga."""
    _drive_service().files().delete(fileId=f["id"], supportsAllDrives=True).execute()
    return f


def _drive_fichero_pedido(text: str) -> Path | None:
    """Qué fichero hay que subir. Por orden: 1) una ruta o un nombre con extensión
    dicho en la propia orden; 2) el informe .md más reciente de data/reports.
    Si no hay ninguno devuelve None y el handler lo DICE, en vez de subir algo que
    el usuario no ha pedido — subir el fichero equivocado al Drive de alguien es de
    los errores que no se deshacen solos."""
    m = re.search(r"[«\"']([^«»\"'\n]+\.[A-Za-z0-9]{1,5})[»\"']", text)
    if not m:
        m = re.search(r"\b([A-Za-z]:[\\/][^\s«»\"']+\.[A-Za-z0-9]{1,5})", text)
    if not m:
        # INCIDENTE: aquí había [\w .\-]+ , que ADMITE ESPACIOS y es codicioso, así
        # que en «sube viejo.md a drive» se llevaba también el verbo y buscaba un
        # fichero llamado «sube viejo.md». Sin espacios: un nombre con espacios se
        # dice entre comillas y lo coge la primera regex.
        m = re.search(r"(?:^|\s)([\w\-.]+\.(?:md|markdown|txt|pdf|docx|xlsx|csv|json|html?))\b",
                      text, re.IGNORECASE)
    if m:
        cand = Path(m.group(1).strip()).expanduser()
        if cand.is_file():
            return cand
        enreports = REPORTS_DIR / cand.name
        if enreports.is_file():
            return enreports
        if REPORTS_DIR.is_dir():        # el usuario no escribe respetando mayúsculas
            for p in REPORTS_DIR.iterdir():
                if p.is_file() and p.name.lower() == cand.name.lower():
                    return p
        return None                     # nombrado y no encontrado → se DICE, no se suple
    if REPORTS_DIR.is_dir():
        mds = sorted((p for p in REPORTS_DIR.glob("*.md") if p.is_file()),
                     key=lambda p: p.stat().st_mtime, reverse=True)
        if mds:
            return mds[0]
    return None


# ── De la frase al nombre: qué toco y dónde ────────────────────────────────
_DRIVE_RELLENO = {"de", "del", "en", "el", "la", "los", "las", "mi", "mis", "un", "una",
                  "a", "al", "que", "drive", "google", "carpeta", "archivo", "fichero"}
_DRIVE_GENERICOS = {"archivo", "archivos", "fichero", "ficheros", "documento",
                    "documentos", "carpeta", "carpetas", "directorio", "directorios",
                    "todos", "todas", "cosa", "cosas"}
_DRIVE_COLA = (r"(?:\s+(?:de|del|en|dentro\s+de)\s+(?:mi\s+|el\s+|tu\s+)?"
               r"(?:google\s+)?drive\b.*)?$")


def _drive_entrecomillado(text: str) -> str:
    m = re.search(r"[«\"']([^«»\"'\n]{1,120})[»\"']", text)
    return m.group(1).strip() if m else ""


def _drive_objetivo(text: str) -> str:
    """El nombre de LO QUE se toca. Por orden: entrecomillado, lo que va detrás de
    «carpeta/archivo/fichero/documento», o un nombre con extensión suelto."""
    citado = _drive_entrecomillado(text)
    if citado:
        return citado
    m = re.search(r"\b(?:carpetas?|directorios?|archivos?|ficheros?|documentos?|informes?)\s+"
                  r"(?:llamad[oa]\s+)?(?:el\s+|la\s+|mi\s+)?([\w.\-]+(?:/[\w.\-]+)*)",
                  text, re.IGNORECASE)
    if m and m.group(1).lower() not in _DRIVE_RELLENO:
        return m.group(1)
    m = re.search(r"(?:^|\s)([\w\-.]+\.[A-Za-z0-9]{1,5})\b", text)
    return m.group(1).strip() if m else ""


def _drive_carpeta_pedida(text: str) -> str:
    """La carpeta que nombra la orden («en la carpeta X», «a la raíz»), o "" para
    quedarse con la de umbrales.json. Acepta rutas anidadas «a/b/c»."""
    if re.search(r"\b(?:a|en|hacia|hasta|de)\s+(?:la\s+)?ra[ií]z\b", text, re.IGNORECASE):
        return "raiz"
    m = re.search(r"\b(?:carpeta|directorio|folder)\s+(?:nuev[ao]\s+)?(?:llamad[oa]\s+)?"
                  r"(?:el\s+|la\s+|mi\s+)?[«\"']?([\w .\-]*[\w\-](?:/[\w .\-]*[\w\-])*)[»\"']?",
                  text, re.IGNORECASE)
    if not m:
        return ""
    nombre = m.group(1).strip()
    # el hueco admite espacios (hay carpetas «Informes de clientes»), así que puede
    # haberse llevado la cola: «carpeta Informes de mi drive» → «Informes».
    nombre = re.sub(r"\s+(?:de|del|en|dentro\s+de)\s+(?:mi\s+|el\s+|tu\s+)?"
                    r"(?:google\s+)?drive\s*$", "", nombre, flags=re.IGNORECASE).strip()
    return "" if nombre.lower() in _DRIVE_RELLENO else nombre


def _drive_dos_partes(text: str, verbos: str, enlaces: str) -> tuple[str, str]:
    """«<verbo> ORIGEN <enlace> DESTINO [en drive]» → (origen, destino). Lo usan
    mover y renombrar, que son las dos órdenes con dos nombres dentro."""
    m = re.search(rf"\b(?:{verbos})\s+(?:el\s+|la\s+|los\s+|las\s+|mi\s+)?"
                  r"(?:archivo\s+|fichero\s+|documento\s+|carpeta\s+|directorio\s+|informe\s+)?"
                  r"[«\"']?(?P<orig>[^«»\"'\n]+?)[»\"']?\s+"
                  rf"(?:{enlaces})\s+(?:la\s+|el\s+|mi\s+)?"
                  r"(?:carpeta\s+|directorio\s+)?[«\"']?(?P<dest>[^«»\"'\n]+?)[»\"']?"
                  + _DRIVE_COLA, text, re.IGNORECASE)
    if not m:
        return "", ""
    orig, dest = m.group("orig").strip(), m.group("dest").strip()
    if orig.lower() in _DRIVE_RELLENO or not dest:
        return "", ""
    return orig, dest


def _drive_texto_buscado(text: str) -> tuple[str, str]:
    """(trozo de nombre, tipo) de «busca los pdf de contratos en drive».

    Primero se corta la COLA de ubicación («en drive», «en la carpeta X»): sin
    eso, «localiza informe en la carpeta Clientes de drive» veía la palabra
    «carpeta» y se ponía a buscar carpetas en vez del informe."""
    cabeza = re.split(r"\s+(?:en|dentro\s+de)\s+(?:mi\s+|el\s+|tu\s+|la\s+)?"
                      r"(?:google\s+)?(?:drive|carpeta|directorio)\b",
                      text, maxsplit=1, flags=re.IGNORECASE)[0]
    tipo = ""
    if re.search(r"\bcarpetas?\b", cabeza, re.IGNORECASE):
        tipo = "carpeta"
    else:
        m = re.search(r"\b(pdf|png|jpe?g|csv|zip|docx?|xlsx?|md|markdown|json|txt)s?\b",
                      cabeza, re.IGNORECASE)
        if m:
            tipo = m.group(1).lower()
    citado = _drive_entrecomillado(text)
    if citado:
        return citado, tipo
    m = re.search(r"\b(?:busca(?:me)?|b[uú]sca(?:me)?|buscar|encuentra|localiza)\s+"
                  r"(?:me\s+)?(?P<q>[^«»\"'\n]+)$", cabeza, re.IGNORECASE)
    if not m:
        return "", tipo
    q = " ".join(p for p in m.group("q").split()
                 if p.lower() not in _DRIVE_RELLENO
                 and p.lower() not in _DRIVE_GENERICOS
                 and p.lower().rstrip("s") != tipo)
    return q.strip(), tipo


def _drive_es_definitivo(text: str) -> bool:
    """¿Ha pedido borrado PERMANENTE? Solo entonces se plantea files.delete, y aun
    así detrás de confirm.request()."""
    return bool(re.search(r"\b(?:definitiv\w+|permanente\w*|para\s+siempre|del\s+todo"
                          r"|sin\s+papelera|no\s+la\s+quiero\s+en\s+la\s+papelera"
                          r"|destruye\w*|destruir)\b", text, re.IGNORECASE))


def _drive_ficha(f: dict) -> str:
    que = "carpeta" if f.get("mimeType") == DRIVE_MIME_CARPETA else "archivo"
    enlace = f.get("webViewLink") or ""
    return f"• {que} «{f.get('name', '?')}»" + (f" — {enlace}" if enlace else "")


DRIVE_SIN_SCOPE_MSG = (
    "Para usar Google Drive necesito un permiso que tu autorización actual no "
    "tiene todavía. Desde el 02/08/2026 pido el permiso de Drive COMPLETO "
    "(auth/drive), que es lo que me deja tocar carpetas tuyas y no solo las que "
    "yo creo. Arreglo: borra config/google_token.json y vuelve a pedírmelo — se "
    "abrirá el navegador UNA vez para que lo autorices. Si Google se queja de "
    "que la API no está habilitada, entra en console.cloud.google.com → APIs y "
    "servicios → habilita «Google Drive API» en el mismo proyecto que ya usas "
    "para Gmail."
)


def _write_creds(cid: str, csec: str) -> None:
    import json
    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(json.dumps({"installed": {
        "client_id": cid, "client_secret": csec,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT_URI, "http://127.0.0.1", f"http://localhost:{OAUTH_PORT}/"],
    }}, indent=2), encoding="utf-8")


def _ensure_credentials(ctx) -> bool:
    """Genera google_credentials.json desde el client_id/secret de ⚙. Si el archivo
    ya existe pero su client_id NO coincide con el de ⚙ (cambiaste de cliente —p.ej.
    de «web» a «escritorio»—), lo REGENERA y borra el token para reautorizar con el
    nuevo. Así cambiar de credenciales en ⚙ «simplemente funciona»."""
    cid = ctx["settings"].secret("google_client_id")
    csec = ctx["settings"].secret("google_client_secret")
    if CREDS_FILE.exists():
        file_cid = ""
        try:
            import json
            data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
            file_cid = (data.get("installed") or data.get("web") or {}).get("client_id", "")
        except Exception:
            pass
        if cid and csec and file_cid and cid != file_cid:
            _write_creds(cid, csec)          # cambió el cliente → regenerar
            try:
                TOKEN_FILE.unlink()          # y forzar reautorización con el nuevo
            except Exception:
                pass
        return True
    if cid and csec:
        _write_creds(cid, csec)
        return True
    return False


async def handle(intent: str, text: str, match, ctx) -> dict:
    global _last_emails, _ultimo_subido
    # Diagnóstico preciso: distinguir librerías que faltan de credenciales que faltan
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
    except ImportError:
        return {"reply": "No puedo hablar con Google porque FALTAN LAS LIBRERÍAS en el "
                         "entorno (no es problema de tus credenciales). Arréglalo con: "
                         "`pip install google-api-python-client google-auth-oauthlib` "
                         "dentro del venv, o simplemente vuelve a ejecutar run.bat que "
                         "ahora lo instala solo."}
    if not _ensure_credentials(ctx):
        return {"reply": SETUP_MSG + " — O más fácil: pega el Client ID y el Client "
                         "Secret en ⚙ (sección Google) y yo genero el archivo solo."}

    try:
        if intent == "unread_count":
            # «cuántos» = SOLO cantidades, números pelados (orden de Adri).
            unread, total = await asyncio.to_thread(_count_unread)
            extra = f" · {total} en la bandeja" if total is not None else ""
            return {"reply": f"{unread} sin leer{extra}."}

        if intent == "unread_from":
            # SOLO remitente + asunto de los NO leídos. Nada de cuerpo/contenido (era el bug:
            # al preguntar «de quién son» soltaba remitente+asunto+CONTENIDO de todos).
            unread, total = await asyncio.to_thread(_count_unread)
            if not unread:
                return {"reply": "No tienes correos sin leer ahora mismo. Bandeja al día."}
            shown = min(unread, 12)
            _last_emails = await asyncio.to_thread(_fetch_emails, shown, True)  # only_unread (global)
            if not _last_emails:
                return {"reply": f"Tienes {unread} correos sin leer, pero Gmail no me ha "
                                 "devuelto la lista ahora mismo. Reinténtalo en un momento."}
            lines = [f"{i+1}. {m['from']} — «{m['subject']}»"
                     for i, m in enumerate(_last_emails)]
            recorte = "" if unread <= len(_last_emails) else \
                f" (los {len(_last_emails)} más recientes)"
            # «cuáles» = SOLO remitente y asunto (orden de Adri): ni cuerpo ni consejos.
            return {"reply": f"{unread} sin leer{recorte}:\n" + "\n".join(lines)}

        if intent == "mark_read":
            # CRUD Gmail: marcar como leídos. Si dice «el correo N», solo ese; si no, TODOS.
            mnum = re.search(r"\b(\d+)\b", text)
            if mnum and _last_emails:
                idx = int(mnum.group(1)) - 1
                if 0 <= idx < len(_last_emails):
                    n = await asyncio.to_thread(_mark_read, [_last_emails[idx]["id"]])
                    return {"reply": f"Marcado como leído: «{_last_emails[idx]['subject']}»."}
            n = await asyncio.to_thread(_mark_read, None)   # todos los no leídos
            return {"reply": f"Hecho: {n} correo(s) marcados como leídos. Bandeja al día."
                    if n else "No había correos sin leer; nada que marcar."}

        if intent == "mark_unread":
            if not _last_emails:
                return {"reply": "No tengo una lista reciente de correos para marcar como no "
                                 "leídos. Di «cuáles correos tengo» y luego «marca el N como no leído»."}
            mnum = re.search(r"\b(\d+)\b", text)
            ids = ([_last_emails[int(mnum.group(1)) - 1]["id"]] if mnum
                   and 0 <= int(mnum.group(1)) - 1 < len(_last_emails)
                   else [m["id"] for m in _last_emails])
            n = await asyncio.to_thread(_mark_unread, ids)
            return {"reply": f"Marcado(s) {n} correo(s) como NO leídos otra vez."}

        if intent == "delete_email":
            # CRUD Gmail: a la papelera (recuperable 30 días). «borra el correo N»,
            # «borra los correos de <remitente>», «borra los correos de más de 30 días».
            mnum = None
            try:
                mnum = match.group("n")
            except Exception:
                mnum = None
            if mnum and _last_emails:
                idx = int(mnum) - 1
                if 0 <= idx < len(_last_emails):
                    m = _last_emails[idx]
                    n = await asyncio.to_thread(_trash_emails, [m["id"]])
                    return {"reply": f"🗑 A la papelera: «{m['subject']}» de {m['from']} "
                                     "(recuperable 30 días)."}
            # por criterio: «de <remitente>» → búsqueda Gmail; «antiguos/más de N días»
            rest = ""
            try:
                rest = (match.group("rest") or "")
            except Exception:
                rest = ""
            q = None
            # OJO CON EL PUNTO (02/08/2026): aquí ponía [^\s,.;], que EXCLUYE el punto,
            # así que «borra los correos de facturacion@empresa.com» buscaba
            # «from:facturacion@empresa» — el dominio cortado a la mitad. Es el mismo
            # fallo que rompía los nombres de fichero en los patrones de Drive. Ahora
            # el punto entra y la puntuación final se quita después.
            mfrom = re.search(r"\bde\s+([^\s,;]+(?:\s+[^\s,;]+){0,2})", rest or text, re.I)
            mdays = re.search(r"m[aá]s\s+de\s+(\d+)\s+d[ií]as|(\d+)\s+d[ií]as|antiguos?", text, re.I)
            if re.search(r"antiguos?|viejos?", text, re.I) or mdays:
                dias = 30
                if mdays and (mdays.group(1) or mdays.group(2)):
                    dias = int(mdays.group(1) or mdays.group(2))
                q = f"older_than:{dias}d in:inbox"
            elif mfrom:
                q = f"from:{mfrom.group(1).strip(' .,;:')}"
            if not q:
                return {"reply": "Dime QUÉ correos borrar: «borra el correo 2», «borra los "
                                 "correos de Amazon» o «borra los correos de más de 30 días». "
                                 "Van a la papelera (recuperables 30 días), no se pierden."}
            ids = await asyncio.to_thread(_search_email_ids, q, 50)
            if not ids:
                return {"reply": f"No he encontrado correos que casen con eso ({q})."}
            n = await asyncio.to_thread(_trash_emails, ids)
            return {"reply": f"🗑 {n} correo(s) a la papelera ({q}). Recuperables 30 días."}

        if intent == "delete_event":
            # DOS SELECTORES: por FECHA («los eventos del día 5», «las citas del
            # miércoles», «el 5 y el 9») y, si no hay fecha, por TÍTULO como antes.
            # Y nada se borra sin enseñar antes QUÉ se va a borrar y esperar un sí:
            # mismo cinturón que la papelera del tablero y el borrado de Drive.
            from backend.core.comun import confirm
            canal = ctx.get("channel", "pc")
            what = ""
            for grupo in ("what", "whatcal"):
                try:
                    what = (match.group(grupo) or "").strip(" .,;:") or what
                except Exception:                                  # noqa: BLE001
                    pass
            fechas = _fechas_pedidas(text)

            if fechas:
                evs = await asyncio.to_thread(_eventos_en, fechas, 100)
                # Y LAS TAREAS CON FECHA. La agenda del HUD pinta las dos cosas
                # en el mismo día, así que «borra lo que haya el día 5» se
                # refiere a lo que se VE. Mirar solo el calendario contestaba
                # «no hay nada» con dos cosas en pantalla: cierto e inútil.
                tareas = await asyncio.to_thread(_tareas_en, fechas)
                dias = " y ".join(_fmt_cuando(f.isoformat()) for f in fechas)
                if not evs and not tareas:
                    return {"reply": f"No hay nada el {dias}, ni en el calendario "
                                     "ni en el tablero."}
                victimas = [{"id": e["id"], "title": e["what"], "tipo": "evento",
                             "when": _fmt_cuando(f"{e['fecha']}T{e['hora']}" if e.get("hora")
                                                 else e["fecha"])} for e in evs]
                victimas += [{"id": t["id"], "title": t.get("title") or "(sin título)",
                              "tipo": "tarea", "when": _fmt_cuando(t.get("due") or "")}
                             for t in tareas]
            else:
                evs = await asyncio.to_thread(_find_events, what, 10)
                if not evs:
                    return {"reply": f"No encuentro ningún evento de «{what}»." if what
                            else "No encuentro ningún evento próximo que borrar."}
                if what:
                    evs = evs[:6]
                else:
                    evs = evs[:1]
                victimas = [{"id": e["id"], "title": e["summary"], "tipo": "evento",
                             "when": _fmt_cuando(e["start"])} for e in evs]

            def _borrar() -> str:
                """Borra cada víctima donde vive: el calendario o el tablero."""
                n = 0
                for v in victimas:
                    try:
                        if v.get("tipo") == "tarea":
                            from backend.core.dominio import board
                            # A la papelera, no destruido: el tablero ya sabe
                            # deshacer un borrado y esto no es una excepción.
                            n += 1 if board.delete_task(v["id"],
                                                        reason="borrar por fecha") else 0
                        else:
                            _delete_event(v["id"])
                            n += 1
                    except Exception:                              # noqa: BLE001, PERF203
                        pass
                total = len(victimas)
                if n == total == 1:
                    return f"🗑 Borrado: «{victimas[0]['title']}»."
                if n == total:
                    return f"🗑 Borrados {n}."
                return f"🗑 Borrados {n} de {total}. El resto ha fallado."

            # «bórralo directamente», «sin preguntar», «ya lo he comprobado yo»,
            # «no preguntes más»: la confirmación existe para que nadie borre a
            # ciegas, no para hacerla repetir. Si dice que ya lo ha mirado, ya
            # está mirado — y todo va a la papelera, que se puede deshacer.
            if _SIN_PREGUNTAR_RX.search(text):
                hecho = await asyncio.to_thread(_borrar)
                return {"reply": hecho}

            if len(victimas) == 1:
                v = victimas[0]
                pregunta = f"Voy a borrar «{v['title']}» ({v['when']}). ¿Lo borro?"
            else:
                lineas = "\n".join(f"• {v['when']} — {v['title']}" for v in victimas)
                pregunta = f"Voy a borrar {len(victimas)}:\n{lineas}\n¿Los borro?"
            return {"reply": confirm.request(
                channel=canal, kind="borrar_eventos", summary=pregunta,
                request_text=text, targets=victimas,
                action=lambda: asyncio.to_thread(_borrar),
                cancel_reply="Vale, no borro nada.")}

        if intent == "edit_event":
            what = ""
            try:
                what = (match.group("what2") or "").strip(" .,;:")
            except Exception:
                what = ""
            # nueva hora/fecha del texto (reutiliza el parser de create_event)
            when = _parse_when(text)
            evs = await asyncio.to_thread(_find_events, re.sub(
                r"\b(?:a\s+las?\s+\d.*|el\s+\w+|ma[ñn]ana|hoy)\b", "", what, flags=re.I).strip(), 10)
            if not evs:
                return {"reply": "No encuentro ese evento en tu calendario para moverlo. "
                                 "Di «mueve la reunión con X al jueves a las 10»."}
            ev = evs[0]
            if not when or not when[0]:
                return {"reply": f"¿A qué día y hora muevo «{ev['summary']}»? "
                                 "Ej.: «mueve esa reunión al viernes a las 17»."}
            start, end, all_day = when
            await asyncio.to_thread(_patch_event, ev["id"], None if all_day else start,
                                    None if all_day else end)
            return {"reply": f"📅 Movido: «{ev['summary']}» → {_fmt_cuando(start)}."}

        if intent == "email_urgent":
            # EN SEGUNDO PLANO (orden de Adri): acuse ya, análisis por detrás y
            # AVISO por el canal de origen cuando termine — como email_actions.
            from backend.core.aplicacion.jobs import jobs as job_mgr
            _chan = ctx.get("channel", "pc")
            await job_mgr.submit("Revisar correos urgentes",
                                 lambda c=_chan: _email_urgent_job(ctx, c), kind="correo")
            return {"reply": "Voy a ello en segundo plano: reviso tus correos sin leer y "
                             "te aviso en cuanto termine con lo urgente."}

        if intent == "email_actions_pron":
            # «analízalos» sin decir de qué. Solo tiene sentido si acabo de enseñarle
            # una lista de correos. Si no la hay, PREGUNTO: adivinar aquí es como
            # decir «ninguno parece urgente» sin haber mirado.
            if not _last_emails:
                return {"reply": "¿Que analice el qué? No te he listado correos todavía. "
                                 "Dime «analiza los correos» y me pongo con la bandeja."}
            intent = "email_actions"           # a partir de aquí, lo mismo de siempre

        if intent == "email_actions":
            # EN SEGUNDO PLANO (orden de Adri): acuse inmediato, análisis por detrás,
            # resultado por el canal que lo pidió.
            from backend.core.aplicacion.jobs import jobs as job_mgr
            _chan = ctx.get("channel", "pc")
            await job_mgr.submit("Correos: análisis y tareas",
                                 lambda c=ctx, ch=_chan: _email_actions_job(c, ch),
                                 kind="correo")
            return {"reply": "Voy a ello en segundo plano: analizo los correos sin leer y "
                             "convierto en tareas lo que pida acción. Sigo contigo — te "
                             "traigo el resultado en cuanto acabe."}

        if intent == "create_event":
            titulo, start, end, all_day, ultimo = _datos_evento(text)
            if not titulo:
                # Sin asunto se PREGUNTA, no se inventa. Un evento titulado
                # «Evento» en el calendario es peor que no crearlo: mañana no
                # dice nada. Mismo criterio que el tablero con las tareas.
                cuando = _fmt_cuando(start) if start else ""
                return {"reply": f"¿Evento de qué{f', el {cuando}' if cuando else ''}? "
                                 "Dime el nombre y lo apunto."}
            if not start:
                return {"reply": "¿Para cuándo lo pongo? Dime la fecha (y hora si quieres): "
                                 "«crea un evento reunión con Ana el viernes a las 17:00» "
                                 "o «apunta el evento Feria del libro del 5 al 9 de agosto»."}
            try:
                _link = await asyncio.to_thread(_create_event, titulo, start, end, "", all_day)
            except Exception as exc:                              # noqa: BLE001
                raise exc
            # espejo en el tablero interno (con la fecha del evento; en los
            # rangos, con el último día INCLUSIVE para que la agenda lo pinte
            # todos los días)
            try:
                from backend.core.dominio import board
                await asyncio.to_thread(board.add_task, titulo,
                                        start[:10], "media", "agenda",
                                        kind="evento", due_end=ultimo)
            except Exception:
                pass
            if ultimo and ultimo != start[:10]:
                cuando = (f"del {_fmt_cuando(start)} al {_fmt_cuando(ultimo)}"
                          + ("" if not all_day else " (todos los días)"))
            else:
                cuando = (f"el {_fmt_cuando(start)}" if not all_day
                          else f"el {_fmt_cuando(start)} (todo el día)")
            return {"reply": f"📅 Evento creado en tu Google Calendar: «{titulo}» {cuando}. "
                             "Lo he reflejado también en tu tablero. Si te arrepientes, "
                             "di «cancela ese evento» y desaparece."}

        if intent == "create_task":
            when = _parse_when(text)
            fecha = when[0][:10] if when else None
            titulo = re.sub(
                r"^\s*(?:crea(?:me)?|a[ñn][aá]de(?:me)?|ap[uú]nta(?:me)?|mete(?:me)?)\s+(?:una\s+|la\s+)?"
                r"tarea\s*(?:de|para|:)?\s*", "", text, flags=re.IGNORECASE)
            titulo = re.sub(r"\b(?:en\s+(?:el\s+|mi\s+)?)?(?:to-?do|google\s+tasks?|"
                            r"tareas?\s+de\s+google|lista\s+de\s+google)\b", "", titulo, flags=re.IGNORECASE)
            titulo = re.sub(r"\b(?:para\s+el\s+|para\s+|el\s+)?"
                            r"(?:hoy|ma[ñn]ana|pasado\s+ma[ñn]ana|lunes|martes|mi[eé]rcoles|jueves|"
                            r"viernes|s[aá]bado|domingo|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
                            r"\d{1,2}\s+de\s+\w+)\b", "", titulo, flags=re.IGNORECASE).strip(" ,.:-")
            if not titulo:
                return {"reply": "¿Qué tarea añado? «crea una tarea en el to-do: pagar al proveedor el viernes»."}
            try:
                await asyncio.to_thread(_create_task, titulo, fecha,
                                        "Creada desde nexus")
            except Exception as exc:                              # noqa: BLE001
                raise exc
            try:
                from backend.core.dominio import board
                await asyncio.to_thread(board.add_task, titulo, fecha, "media", "to-do")
            except Exception:
                pass
            extra = f" (para el {_fmt_cuando(fecha)})" if fecha else ""
            return {"reply": f"✔ Tarea añadida a tu Google To-Do: «{titulo}»{extra}. "
                             "También la tienes en tu tablero interno. Di «tareas de "
                             "google» cuando quieras repasar la lista."}

        if intent == "send_email":
            to, subject, body = _parse_send(text)
            if not to:
                return {"reply": "¿A qué dirección lo envío? Dímelo así: «envía un correo a "
                                 "nombre@dominio.com con asunto X diciendo Y»."}
            if not body:
                # sin cuerpo explícito → el cerebro lo redacta a partir de la orden
                body = await _llm_text(
                    "Redacta SOLO el cuerpo del correo que pide esta orden (español, "
                    "breve, natural, sin asunto ni despedidas raras; fírmalo como "
                    f"{ctx['settings'].get('operator_name', 'el operador')}): {text}")
            if not body:
                return {"reply": "Dime qué quieres que ponga: «… diciendo <mensaje>»."}
            if not subject:
                subject = " ".join(body.split()[:7]) + ("…" if len(body.split()) > 7 else "")
            await asyncio.to_thread(_send_gmail, to, subject, body)
            return {"reply": f"✔ Enviado a {to} — asunto «{subject}»:\n{body[:300]}"}

        if intent == "summarize_emails":
            try:
                n = match.group("n")
            except Exception:
                n = None
            if n:                                   # resumen de UN correo concreto
                if not _last_emails:
                    _last_emails = await asyncio.to_thread(_fetch_emails, 5)
                i = int(n)
                if i < 1 or i > len(_last_emails):
                    return {"reply": "Ese número no está en la última lista. Pídeme "
                                     "«lee mis correos» y luego «resume el correo N»."}
                m = _last_emails[i - 1]
                cuerpo = await asyncio.to_thread(_read_email, m["id"])
                resumen = await _llm_text(
                    "Resume este correo en 2-3 frases, súper concreto (quién, qué pide, "
                    f"fechas/cifras):\nDe: {m['from']}\nAsunto: {m['subject']}\n{cuerpo[:3000]}")
                return {"reply": resumen or f"Correo de {m['from']} — «{m['subject']}»: "
                                            f"{m['snippet']}"}
            _last_emails = await asyncio.to_thread(_fetch_emails, 5)
            if not _last_emails:
                return {"reply": "Bandeja de entrada limpia. Nada que resumir."}
            listado = "\n".join(f"- {m['from']}: {m['subject']} — {m['snippet']}"
                                for m in _last_emails)
            resumen = await _llm_text(
                "Resume estos correos en 3-4 frases, súper concreto (remitentes, qué "
                "piden, qué urge):\n" + listado)
            return {"reply": resumen or "Resumen de la bandeja:\n" + listado}

        if intent == "emails":
            # Por defecto SOLO los NO leídos. Los ya leídos solo si lo pides explícitamente
            # («todos», «leídos») → así no te suelta correos viejos que ya habías visto.
            quiere_leidos = bool(re.search(r"\ble[ií]d[oa]s?\b|\btod[oa]s\b|\btoda\s+la\s+bandeja\b",
                                           text, re.IGNORECASE))
            _last_emails = await asyncio.to_thread(_fetch_emails, 6, not quiere_leidos)
            if not _last_emails:
                return {"reply": "No tienes correos sin leer. Bandeja al día." if not quiere_leidos
                                 else "Bandeja de entrada limpia. Nada nuevo, operador."}
            lines = [f"{i+1}. {'●' if m['unread'] else '○'} {m['from']}: "
                     f"{m['subject']} — {m['snippet']}"
                     for i, m in enumerate(_last_emails)]
            unread = sum(1 for m in _last_emails if m["unread"])
            cab = ("Correos sin leer" if not quiere_leidos else "Últimos correos") + \
                  (f" ({unread} sin leer)" if quiere_leidos else "")
            return {"reply": f"{cab}:\n" + "\n".join(lines) +
                             "\n\nDi «abre el correo N» para leer uno."}

        if intent == "open_email":
            n = int(match.group("n"))
            if not _last_emails or n < 1 or n > len(_last_emails):
                return {"reply": "Primero pídeme «lee mis correos» y luego el número."}
            body = await asyncio.to_thread(_read_email, _last_emails[n - 1]["id"])
            m = _last_emails[n - 1]
            return {"reply": f"Correo de {m['from']} — «{m['subject']}»:\n{body[:900]}"}

        if intent == "gcal":
            # UN BORRADO QUE FALLA NO SE CONVIERTE EN UN LISTADO (03/08/2026).
            # Cuando ninguna regex casaba, el planificador del cerebro mandaba
            # «elimina las tareas del calendario del día 5» aquí y nexus soltaba
            # la agenda entera. Adri: «Por qué lees las citas del calendario si no
            # lo he pedido». Si la frase pide BORRAR, aquí no se lista nada.
            if _PIDE_BORRAR_RX.search(text):
                return {"reply": "Eso es un borrado, no una consulta. Dime qué día: "
                                 "«borra los eventos del día 5»."}
            rango = _month_range(text)
            if rango:                                # «todas las citas de julio»
                tmin, tmax, nombre = rango
                events = await asyncio.to_thread(_fetch_events, 50, tmin, tmax)
                if not events:
                    return {"reply": f"No tienes ninguna cita en {nombre}."}
                lines = [f"• {_fmt_cuando(e['when'])} — {e['what']}" for e in events]
                return {"reply": f"Tienes {len(events)} citas en {nombre}:\n" + "\n".join(lines)}
            events = await asyncio.to_thread(_fetch_events, 6)
            if not events:
                return {"reply": "No tienes nada en el calendario."}
            lines = [f"• {_fmt_cuando(e['when'])} — {e['what']}" for e in events]
            return {"reply": "📅 Próximos eventos:\n" + "\n".join(lines)}

        if intent == "gtasks":
            tasks = await asyncio.to_thread(_fetch_tasks, 10)
            if not tasks:
                return {"reply": "Tu Google Tasks está en blanco: cero pendientes. Di «crea "
                                 "una tarea en el to-do: pagar al proveedor el viernes» y "
                                 "estreno la lista."}
            return {"reply": "Tus tareas de Google:\n" + "\n".join(f"• {t}" for t in tasks) +
                             "\n\nDi «crea una tarea en el to-do: …» si quieres añadir otra."}

        # ── DRIVE: CRUD de ficheros Y carpetas ───────────────────────────────
        # Lo que MODIFICA (crear carpeta, mover, renombrar) va directo: es
        # reversible a mano. Lo que BORRA lleva cinturón, y está unos párrafos
        # más abajo, en drive_delete.
        if intent == "drive_folder_create":
            ruta_carpeta = _drive_carpeta_pedida(text) or _drive_entrecomillado(text)
            if not ruta_carpeta or ruta_carpeta == "raiz":
                return {"reply": "Dime cómo se llama la carpeta: «crea la carpeta "
                                 "Informes en drive». Si me das una ruta "
                                 "(«crea la carpeta Clientes/2026/agosto en drive») "
                                 "creo los tramos que falten."}
            f = await asyncio.to_thread(_drive_crear_carpeta, ruta_carpeta)
            return {"reply": f"Carpeta «{ruta_carpeta}» lista en tu Drive: "
                             f"{f.get('webViewLink') or '(sin enlace)'}",
                    "data": {"drive": f}}

        if intent == "drive_move":
            origen, destino = _drive_dos_partes(
                text, r"mu[eé]ve(?:me|lo|la)?|mover|traslada|trasladar|ll[eé]va(?:me|lo|la)?|pasa",
                r"a|al|hacia|hasta|dentro\s+de|en")
            if not origen:
                return {"reply": "No te he pillado qué muevo ni adónde. Dilo así: "
                                 "«mueve informe-2026-08-02.md a la carpeta Clientes "
                                 "en drive» (o «a la raíz de drive»)."}
            f = await asyncio.to_thread(_drive_mover, origen, destino)
            return {"reply": f"Movido: «{f.get('name')}» está ahora en "
                             f"«{f.get('destino')}». Sigue siendo el mismo archivo, "
                             f"con el mismo enlace: {f.get('webViewLink') or '(sin enlace)'}",
                    "data": {"drive": f}}

        if intent == "drive_rename":
            origen, nuevo = _drive_dos_partes(
                text, r"ren[oó]mbra(?:me|lo|la)?|renombrar"
                      r"|c[aá]mbia(?:le)?\s+el\s+nombre(?:\s+(?:de|del|a|al))?",
                r"a|por|como")
            if not origen:
                return {"reply": "Dime el nombre de ahora y el nuevo: «renombra "
                                 "informe.md a informe-final.md en drive»."}
            f = await asyncio.to_thread(_drive_renombrar, origen, nuevo)
            return {"reply": f"Renombrado: «{origen}» → «{f.get('name')}». El enlace no "
                             f"cambia: {f.get('webViewLink') or '(sin enlace)'}",
                    "data": {"drive": f}}

        if intent == "drive_replace":
            # Actualizar ≠ volver a subir: subir otra vez deja DOS ficheros con el
            # mismo nombre y un enlace nuevo. El enlace viejo es justo el que le
            # has pegado a ChatGPT/Claude, así que se conserva el id.
            ruta = _drive_fichero_pedido(text)
            if not ruta:
                return {"reply": "No sé qué archivo local uso para actualizarlo. Dime "
                                 "«actualiza informe-2026-08-02.md en drive» y cojo ese "
                                 "de data/reports."}
            f = await asyncio.to_thread(_drive_reemplazar, ruta.name, ruta)
            return {"reply": f"Actualizado «{f.get('name')}» en tu Drive: mismo archivo y "
                             f"MISMO ENLACE ({f.get('webViewLink') or 'sin enlace'}), "
                             "contenido nuevo. No he dejado un duplicado.",
                    "data": {"drive": f}}

        if intent == "drive_download":
            nombre = _drive_objetivo(text)
            if not nombre:
                return {"reply": "Dime qué archivo bajo: «descarga informe.md de drive». "
                                 "Los Google Docs/Sheets/Slides te los exporto (a .md, "
                                 ".csv y .pdf respectivamente)."}
            destino_dir = REPORTS_DIR.parent / "drive"
            ruta = await asyncio.to_thread(_drive_descargar, nombre, destino_dir)
            return {"reply": f"Descargado «{ruta.name}» en {ruta}.",
                    "data": {"drive": {"name": ruta.name, "ruta": str(ruta)}}}

        if intent == "drive_search":
            texto_q, tipo = _drive_texto_buscado(text)
            carpeta_q = _drive_carpeta_pedida(text)
            if not texto_q and not tipo:
                return {"reply": "Dime qué busco: «busca contratos en drive», «busca los "
                                 "pdf de 2026 en drive» o «busca las carpetas de clientes "
                                 "en drive»."}
            hallados = await asyncio.to_thread(_drive_buscar, texto_q, tipo, carpeta_q, 15)
            if not hallados:
                return {"reply": f"En tu Drive no encuentro nada con «{texto_q or tipo}»"
                                 + (f" dentro de «{carpeta_q}»" if carpeta_q else "") +
                                 ". Busco por trozo de nombre, no por contenido."}
            return {"reply": f"{len(hallados)} resultado(s) en tu Drive:\n" +
                             "\n".join(_drive_ficha(f) for f in hallados),
                    "data": {"drive": hallados}}

        if intent == "drive_delete":
            # ⚠️ EL SITIO DELICADO DE TODA LA SKILL. Con el scope completo esto
            # apunta a documentos REALES del usuario, y aquí se llega por una
            # regex. Por eso: (1) por defecto PAPELERA, que se deshace;
            # (2) el borrado definitivo solo dentro de confirm.request();
            # (3) una carpeta con cosas dentro DICE cuántas antes de tocar nada.
            nombre = _drive_objetivo(text)
            if not nombre:
                return {"reply": "No pienso adivinar qué borro de tu Drive. Dímelo por su "
                                 "nombre exacto: «borra informe-viejo.md de drive» (va a "
                                 "la papelera de Drive, se recupera)."}
            definitivo = _drive_es_definitivo(text)
            canal = (ctx or {}).get("channel", "pc") if isinstance(ctx, dict) else "pc"
            svc = await asyncio.to_thread(_drive_service)
            f = await asyncio.to_thread(_drive_uno, svc, nombre)
            es_carpeta = f.get("mimeType") == DRIVE_MIME_CARPETA
            dentro = await asyncio.to_thread(_drive_dentro, svc, f["id"]) if es_carpeta else 0
            from backend.core.comun import confirm

            if definitivo or dentro:
                que = "carpeta" if es_carpeta else "archivo"
                aviso = (f"⚠️ La {que} «{f.get('name')}» de tu Drive")
                if dentro:
                    aviso += (f" tiene {dentro} elemento(s) dentro"
                              f"{' (al menos)' if dentro >= 100 else ''} y se van con ella")
                aviso += (". Borrado DEFINITIVO: no pasa por la papelera y NO se puede "
                          "recuperar. " if definitivo else
                          ". Va a la papelera de Drive, de donde se puede recuperar. ")
                aviso += "¿Lo confirmas? Responde «sí» o «no»."

                def _ejecutar(_d=definitivo, _f=f):
                    if _d:
                        _drive_destruir(_f)
                        return (f"Destruido para siempre: «{_f.get('name')}». "
                                "Esa no vuelve.")
                    _drive_a_papelera(_f)
                    return (f"«{_f.get('name')}» está en la papelera de tu Drive. "
                            "Se restaura desde drive.google.com/drive/trash.")
                return {"reply": confirm.request(
                    channel=canal, kind="drive_borrar", summary=aviso,
                    action=_ejecutar, request_text=text,
                    targets=[{"id": f.get("id"), "title": f.get("name"),
                              "mimeType": f.get("mimeType")}],
                    cancel_reply="Vale, no toco nada de tu Drive."),
                    "data": {"confirm": True, "dentro": dentro,
                             "definitivo": definitivo}}

            borrado = await asyncio.to_thread(_drive_a_papelera, f)
            return {"reply": f"«{borrado.get('name')}» a la papelera de tu Drive. NO está "
                             "borrado del todo: se restaura desde "
                             "drive.google.com/drive/trash. Si quieres que desaparezca "
                             "de verdad, dime «bórralo definitivamente de drive» y te "
                             "pediré confirmación.",
                    "data": {"drive": borrado}}

        if intent == "drive_upload":
            ruta = _drive_fichero_pedido(text)
            if ruta is None:
                # Honestidad antes que iniciativa: NO se sube «algo parecido».
                return {"reply": "No sé qué archivo quieres que suba. Dímelo por su "
                                 "nombre («sube informe-2026-08-02.md a drive») o genera "
                                 "antes el informe y yo subo el último .md de "
                                 "data/reports. Ahora mismo ahí no hay ninguno."}
            # la carpeta de umbrales.json es el DEFECTO, no una cárcel: si la orden
            # nombra otra («sube el informe a la carpeta Clientes de drive»), manda esa.
            carpeta = _drive_carpeta_pedida(text) or _umbrales_drive()["carpeta"]
            f = await asyncio.to_thread(_drive_subir, ruta, carpeta)
            _ultimo_subido = f
            enlace = f.get("webViewLink") or "(Drive no ha devuelto enlace)"
            return {"reply": f"Subido a tu Drive, carpeta «{carpeta}»: «{f.get('name')}».\n"
                             f"{enlace}\n"
                             f"(id {f.get('id')}) — ya puedes decirle a ChatGPT o Claude "
                             f"que lo lea de ahí.",
                    "data": {"drive": f}}

        if intent == "drive_link":
            if _ultimo_subido.get("webViewLink"):
                return {"reply": f"«{_ultimo_subido.get('name')}» → "
                                 f"{_ultimo_subido['webViewLink']}"}
            carpeta = _umbrales_drive()["carpeta"]
            subidos = await asyncio.to_thread(_drive_listar, 1, carpeta)
            if not subidos:
                return {"reply": f"Todavía no he subido nada a la carpeta «{carpeta}» de "
                                 "tu Drive, así que no hay enlace que darte. Di «sube el "
                                 "informe a drive» y te devuelvo el enlace."}
            u = subidos[0]
            return {"reply": f"Lo último que subí: «{u.get('name')}» → "
                             f"{u.get('webViewLink', '(sin enlace)')}"}

        if intent == "drive_list":
            pedida = _drive_carpeta_pedida(text)
            carpeta = pedida or _umbrales_drive()["carpeta"]
            subidos = await asyncio.to_thread(_drive_listar, 25, carpeta)
            if not subidos:
                if pedida:
                    # NO se dice «no existe»: _drive_listar devuelve lo mismo para
                    # «no hay carpeta» que para «carpeta sin nada dentro».
                    return {"reply": f"En «{carpeta}» no veo nada dentro. Si la carpeta "
                                     "tiene otro nombre dímelo tal cual (respeto "
                                     "mayúsculas y acentos), o prueba «busca "
                                     f"{carpeta} en drive»."}
                return {"reply": f"No he subido nada a la carpeta «{carpeta}» y ahí "
                                 "dentro tampoco hay nada tuyo. Puedo listarte "
                                 "cualquier otra: «qué hay en la carpeta X de drive»."}
            lineas = [f"{i+1}. {_drive_ficha(u)[2:]}" for i, u in enumerate(subidos)]
            return {"reply": f"Contenido de «{carpeta}» ({len(subidos)}, lo más "
                             f"reciente primero):\n" + "\n".join(lineas),
                    "data": {"drive": subidos, "carpeta": carpeta}}

    except FileNotFoundError as exc:
        # Distinguir «faltan las credenciales» de «el archivo que ibas a subir ya no
        # está»: antes ambos salían como SETUP_MSG y mandaban a reconfigurar Google
        # por un .md que alguien había movido.
        if intent.startswith("drive_") and getattr(exc, "filename", "") \
                and "google_credentials" not in str(getattr(exc, "filename", "")):
            return {"reply": f"Ese archivo ya no está donde decía: {exc.filename}. "
                             "No he subido nada. Dime el nombre correcto o vuelve a "
                             "generar el informe."}
        return {"reply": SETUP_MSG}
    except DriveNoEncontrado as exc:
        # Va ANTES del except genérico: DriveNoEncontrado es un LookupError y allí
        # abajo se convertiría en un «error raro» sin decir lo único que importa.
        return {"reply": f"En tu Drive no encuentro nada que se llame «{exc}», así que "
                         "no he tocado nada. Busco por nombre EXACTO a propósito: con "
                         "permiso sobre todo tu Drive, coger «el más parecido» es cómo "
                         "se acaba moviendo el documento equivocado. Comprueba el "
                         f"nombre (respeto mayúsculas y acentos) o dime «busca {exc} "
                         "en drive» y te enseño lo que hay."}
    except IsADirectoryError as exc:
        return {"reply": f"«{exc}» es una carpeta, y una carpeta no se descarga de una "
                         f"pieza. Dime «qué hay en la carpeta {exc} de drive» y bajamos "
                         "los archivos que quieras."}
    except Exception as exc:
        msg = str(exc).lower()
        # DRIVE PRIMERO, y por un motivo concreto: la comprobación de «acceso
        # bloqueado» de abajo captura «400» y «unauthorized», así que se tragaba el
        # fallo típico de Drive (token viejo sin el scope nuevo, o la Drive API sin
        # habilitar) y soltaba un texto de redirect_uri que no arregla nada. Un
        # mensaje que manda a arreglar lo que no está roto es peor que ninguno.
        if intent.startswith("drive_"):
            if any(k in msg for k in (
                    "insufficient", "scope", "insufficientpermissions",
                    "access_token_scope", "forbidden", "403",
                    "has not been used", "accessnotconfigured", "disabled")):
                return {"reply": DRIVE_SIN_SCOPE_MSG}
            if any(k in msg for k in ("notfound", "not found", "404", "file not found")):
                return {"reply": "Drive dice que ese archivo ya no está (404). O lo han "
                                 "borrado, o está en la papelera, o el enlace es de otra "
                                 "cuenta. No he cambiado nada."}
            if any(k in msg for k in ("insufficientfilepermissions", "permission",
                                      "cannotmodify", "not writable")):
                return {"reply": "Ese archivo es de tu Drive pero no te deja modificarlo: "
                                 "suele ser un documento COMPARTIDO del que no eres "
                                 "dueño, o está en una unidad compartida con permisos de "
                                 "solo lectura. Pídele permiso de edición al dueño; yo "
                                 "no lo puedo saltar."}
            if isinstance(exc, (PermissionError, OSError)) and not isinstance(exc, FileNotFoundError):
                return {"reply": f"No he podido leer el archivo para subirlo: {exc}. "
                                 "Comprueba que existe y que no lo tiene abierto otro "
                                 "programa (Word bloquea el archivo mientras lo edita)."}
        # «Acceso bloqueado / solicitud no válida» = Error 400 del cliente OAuth.
        blocked = any(k in msg for k in (
            "redirect_uri", "mismatch", "invalid_request", "invalid request",
            "access blocked", "acceso bloqueado", "no es válida", "not valid",
            "400", "timeout", "timed out", "invalid_client", "unauthorized"))
        if blocked:
            return {"reply": BLOCKED_MSG}
        if "access_denied" in msg or "verif" in msg or "test user" in msg or "usuario de prueba" in msg:
            return {"reply":
                    "Google bloqueó el acceso porque la app está sin verificar. En "
                    "console.cloud.google.com → «Pantalla de consentimiento OAuth», con la "
                    "app en modo «Prueba», añade tu cuenta de Google en «Usuarios de prueba». "
                    "Luego borra config/google_token.json y reintenta."}
        return {"reply": f"Google respondió con un error: {type(exc).__name__}: {exc}. "
                         "Si es de autorización, borra config/google_token.json y reintenta."}

    return {"reply": "Esa orden de Google no la tengo mapeada. Prueba «lee mis correos», "
                     "«cuántos correos sin leer», «qué tengo en el calendario», "
                     "«tareas de google» o «sube el informe a drive»."}
