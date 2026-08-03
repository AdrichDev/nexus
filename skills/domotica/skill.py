"""Minion DOMÓTICA — descubre y controla los dispositivos de tu red local.

Filosofía: no cableamos marca por marca a mano, seguimos los ESTÁNDARES:
  1. DESCUBRIR (rastreo ACTIVO, como el «buscar dispositivos» del Bluetooth):
     • PING SWEEP de toda la subred (.1–.254 en paralelo) → despierta y encuentra
       TODO lo que tiene IP, aunque esté callado (no solo lo que ya estaba en caché).
     • Tabla ARP del sistema → IP + MAC de cada aparato encontrado.
     • Fabricante por la MAC (OUI): Apple, Samsung, LG, Google, Amazon, Xiaomi…
     • SSDP/UPnP → Smart TVs, altavoces, Chromecast, NAS, impresoras…
     • mDNS/Bonjour → nombres bonitos y tipo (Chromecast, AirPlay, HomeKit,
       impresora, Spotify, Xiaomi…). Las respuestas vienen del propio aparato.
     • DNS inverso + sondeo de puertos típicos (Roku 8060, Chromecast 8008,
       impresora 9100, Home Assistant 8123, Plex 32400, SSH/SMB/HTTP…) → tipo.
  2. CONTROLAR:
     • Wake-on-LAN  → encender PCs y TVs con «wake on network» (paquete mágico).
     • Roku ECP     → HTTP simple, sin emparejar (Roku, algunas TCL/Hisense).
     • Samsung Tizen→ WebSocket (guarda un token; la 1ª vez la TV pide permiso).
     • Home Assistant → si lo tienes, es el MANDO UNIVERSAL: luces, enchufes,
       termostatos, persianas, ventiladores, teles… todo por su API REST.

Config (⚙ → sección CASA / DOMÓTICA, o config/secrets.json):
  • homeassistant_url   (ajuste)  ej. http://homeassistant.local:8123
  • homeassistant_token (secreto) token de acceso de larga duración de HA
  • known_devices       (ajuste)  lista [{name, ip, mac, brand}] de tus aparatos
Sin nada configurado, «escanea la red» ya te lista lo que encuentra.
"""
from __future__ import annotations

import asyncio
import re
import socket
import subprocess
import time

# Sustantivo de TV, compartido por todos los patrones de televisión.
# Las alternativas van de más larga a más corta: «televisor» debe ganarle a «tele».
_TV = r"(?:televisi[oó]n|televisor(?:es)?|smart\s*tv|tele|tv)"
# Pronombre enclítico opcional: «apágalo», «enciéndemela», «quítale», «ponlos».
# Se pega SIEMPRE a la forma con tilde del verbo, porque el enclítico la desplaza
# (apaga→apágalo, enciende→enciéndelo, sube→súbeme).
_CL = r"(?:(?:me|te|le|nos|se)?(?:lo|la|los|las)?)"

SKILL = {
    "name": "Casa / Domótica",
    "description": "Escanea tu red (nombre, marca, IP y MAC de cada aparato) y controla la casa: TVs por su nombre —encender, apagar, volumen, canal, apps—, PCs por Wake-on-LAN y luces/enchufes/persianas vía Home Assistant",
    # ORDEN: lo específico (TV, WoL, descubrir) ANTES del genérico de casa (HA).
    # Y dentro de la TV, «silenciar» ANTES de «apagar»/«encender»: «quita el sonido
    # de la tele» y «pon la tele en silencio» casarían también con esos dos.
    "patterns": {
        "descubrir": r"(?:escan[eé]a(?:me)?|escaneo|esc[aá]ner|r[aá]strea(?:me)?|sondea|detecta|busca|"
                     r"b[uú]sca(?:me)?|descubre|lista|revisa|mira|mu[eé]stra(?:me)?|ens[eé][ñn]a(?:me)?|"
                     r"dime|cu[aá]nt[oa]s|qui[eé]n(?:es)?|qu[eé]\s+hay|qu[eé]\s+dispositivos|"
                     r"qu[eé]\s+aparatos)\b[^.\n]{0,30}\b(?:dispositivos?|aparatos?|cacharros?|"
                     r"(?:en\s+)?(?:la\s+red|mi\s+red|el\s+wifi)|red\s+local|conectad|dom[oó]tic)"
                     r"|\bqu[eé]\s+(?:dispositivos?|aparatos?|cacharros?)\b",
        "tv_mute": r"(?:sil[eé]ncia" + _CL + r"|mut[eé]a" + _CL + r"|c[aá]lla" + _CL +
                   r"|qu[ií]ta" + _CL + r"\s+el\s+(?:sonido|ruido|volumen)|sin\s+sonido)"
                   r"\b[^.\n]{0,20}\b(?:de\s+)?(?:la\s+)?" + _TV + r"\b"
                   r"|\b" + _TV + r"\b[^.\n]{0,15}\ben\s+silencio\b",
        # El SUBJUNTIVO cuenta: al repetir una orden nadie dice «apaga la tele»
        # otra vez, dice «te he dicho que APAGUES la tele». Sin él, insistir se
        # quedaba sin dueño y acababa en el planificador.
        "tv_off": r"(?:ap[aá]ga" + _CL + r"|ap[aá]gues|apagar|desconecta|desconectes|"
                  r"qu[ií]ta" + _CL + r"|quites|corta|cortes)"
                  r"\b[^.\n]{0,18}\b(?:la\s+)?" + _TV + r"\b",
        "tv_on": r"(?:enci[eé]nde" + _CL + r"|enciendas|encender|arranca|arranques|"
                 r"pr[eé]nde" + _CL + r"|prendas|activa|actives|pon\s+en\s+marcha)"
                 r"\b[^.\n]{0,18}\b(?:la\s+)?" + _TV + r"\b"
                 r"|(?:p[oó]n" + _CL + r"|quiero\s+ver|dale\s+a)\s+(?:la\s+)?" + _TV + r"\b",
        # OJO: exige mención de «tele/tv» para NO robarle a la skill de MÚSICA
        # órdenes como «pon spotify»/«pon youtube» (que van a media, no a la TV).
        "tv_app": r"(?:abre|pon|lanza|quiero\s+ver)\b[^.\n]{0,25}\b(?P<app>netflix|youtube|prime\s*video|prime|disney\+?|hbo\s*max|hbo|movistar|spotify|plex|twitch)\b[^.\n]{0,20}\b(?:en\s+)?(?:la\s+)?" + _TV + r"\b"
                  r"|\b(?:en\s+)?(?:la\s+)?" + _TV + r"\b[^.\n]{0,20}\b(?:abre|pon|lanza|quiero\s+ver)?\s*(?P<app2>netflix|youtube|prime\s*video|prime|disney\+?|hbo\s*max|hbo|movistar|spotify|plex|twitch)\b",
        # El volumen EXIGE nombrar la tele, igual que `tv_mute`. Sin esa palabra
        # la orden no es de aquí: el destino lo dice siempre quien da la orden y
        # el volumen sin destino lo pregunta `system_pc`.
        "tv_volume": r"(?P<dir>s[uú]be\w*|b[aá]ja\w*|m[aá]s|menos)\b[^.\n]{0,15}\b(?:el\s+)?volumen\b"
                     r"[^.\n]{0,15}\b(?:de\s+|a\s+|en\s+)?(?:la\s+|el\s+|mi\s+)?" + _TV + r"\b"
                     r"|\b" + _TV + r"\b[^.\n]{0,20}\b(?P<dir2>s[uú]be\w*|b[aá]ja\w*|m[aá]s|menos)\b"
                     r"[^.\n]{0,15}\b(?:el\s+)?volumen\b",
        "tv_channel": r"(?:p[oó]n" + _CL + r"|c[aá]mbia" + _CL + r"(?:\s+al?)?|salta\s+al?|pasa\s+al?|quiero)"
                      r"\b[^.\n]{0,15}\b(?:el\s+)?canal\s+(?:(?P<n>\d+)|(?P<nw>uno|dos|tres|cuatro|"
                      r"cinco|seis|siete|ocho|nueve|diez))\b"
                      r"|(?P<dir2>siguiente|anterior)\s+canal|canal\s+(?P<dir3>siguiente|anterior)",
        "wol": r"(?:enci[eé]nde" + _CL + r"|arranca|despierta|despi[eé]rta" + _CL + r"|levanta|"
               r"lev[aá]nta" + _CL + r"|pr[eé]nde" + _CL + r")\b[^.\n]{0,20}\b"
               r"(?P<dev>pc|ordenador|ordenata|port[aá]til|equipo|servidor|m[aá]quina|torre|sobremesa|nas)\b",
        # GENÉRICO → Home Assistant (todo lo domotizado)
        "casa": r"(?:enci[eé]nde" + _CL + r"|ap[aá]ga" + _CL + r"|desconecta|p[oó]n" + _CL +
                r"|s[uú]be" + _CL + r"|b[aá]ja" + _CL + r"|activa|desactiva|ci[eé]rra" + _CL +
                r"|[aá]bre" + _CL + r"|qu[ií]ta" + _CL + r"|arranca|para)"
                r"\b[^.\n]{0,45}\b(?P<what>luz|luces|l[aá]mpara|foco|led|bombilla|enchufe|regleta|"
                r"persiana|estor|toldo|termostato|calefacci[oó]n|aire|climatizaci[oó]n|ventilador|"
                r"calefactor|estufa|radiador|caldera|riego|aspersor|toma|humidificador|purificador|"
                r"cafetera|horno|lavadora|secadora|lavavajillas|puerta|port[oó]n|cancela|"
                r"sal[oó]n|comedor|cocina|habitaci[oó]n|dormitorio|cuarto|ba[ñn]o|aseo|pasillo|"
                r"entrada|recibidor|garaje|jard[ií]n|terraza|balc[oó]n|porche|trastero|s[oó]tano|"
                r"buhardilla|oficina|despacho)\b",
    },
}

SETUP_HA = (
    "Aún no tengo Home Assistant conectado, y es el mando universal de la casa "
    "(luces, enchufes, persianas, termostatos…). Para activarlo: en HA → tu perfil "
    "(abajo a la izquierda) → «Tokens de acceso de larga duración» → crea uno y "
    "pégalo en ⚙ (sección CASA) junto con la URL de HA "
    "(p.ej. http://homeassistant.local:8123). Mientras tanto, sin HA ya descubro "
    "tu red y manejo TVs por Roku/Samsung/Wake-on-LAN: di «escanea la red»."
)


# ---------------------------------------------------------------- red local
def _arp_table() -> list[dict]:
    """Lee la tabla ARP del sistema → [{ip, mac}]. Multiplataforma (arp -a)."""
    out = []
    try:
        # errors="replace": en Windows «arp» escribe en la página de códigos de la
        # consola (cp850/cp1252), no en UTF-8. Sin esto la lectura reventaba y nos
        # quedábamos sin tabla ARP, que es de donde sale la IP actual de cada MAC.
        raw = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                             errors="replace", timeout=6).stdout
    except Exception:
        return out
    for ip, mac in re.findall(
            r"(\d{1,3}(?:\.\d{1,3}){3})\D+([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})",
            raw or ""):
        out.append({"ip": ip, "mac": mac.replace("-", ":").lower()})
    return out


def _ssdp_discover(timeout: float = 3.0) -> dict:
    """Descubre dispositivos UPnP/SSDP (Smart TVs, altavoces, Chromecast, NAS…).
    Devuelve {ip: {server, st, location}}."""
    msg = ("M-SEARCH * HTTP/1.1\r\n"
           "HOST:239.255.255.250:1900\r\n"
           'MAN:"ssdp:discover"\r\n'
           "MX:2\r\nST:ssdp:all\r\n\r\n").encode()
    found: dict = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(timeout)
        s.sendto(msg, ("239.255.255.250", 1900))
        while True:
            try:
                data, addr = s.recvfrom(65507)
            except socket.timeout:
                break
            ip = addr[0]
            hdr = {}
            for line in data.decode("utf-8", "replace").split("\r\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    hdr[k.strip().lower()] = v.strip()
            prev = found.get(ip, {})
            found[ip] = {"server": hdr.get("server", prev.get("server", "")),
                         "st": hdr.get("st", prev.get("st", "")),
                         "location": hdr.get("location", prev.get("location", ""))}
        s.close()
    except Exception:
        pass
    return found


def _guess_type(server: str, st: str) -> str:
    blob = (server + " " + st).lower()
    for key, label in (("roku", "TV Roku"), ("samsung", "TV Samsung"),
                       ("webos", "TV LG"), ("lg ", "TV LG"), ("bravia", "TV Sony"),
                       ("dial", "TV/Chromecast"), ("cast", "Chromecast"),
                       ("sonos", "Altavoz Sonos"), ("spotify", "Altavoz"),
                       ("philips", "TV/Hue Philips"), ("printer", "Impresora"),
                       ("nas", "NAS"), ("router", "Router"), ("ipcamera", "Cámara")):
        if key in blob:
            return label
    return "Dispositivo UPnP"


# ------------------------------------------------- rastreo ACTIVO de la subred
def _primary_ipv4() -> str:
    """IP local principal (la de la ruta por defecto), sin enviar nada a internet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.4)
        s.connect(("8.8.8.8", 80))   # no manda paquetes, solo elige interfaz/IP
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return ""


def _subnets() -> list[str]:
    """Prefijos /24 a barrer (ej. '192.168.1'). Prioriza la interfaz principal y
    añade las demás IPv4 privadas del equipo (varias NIC/WiFi+cable)."""
    bases, seen = [], set()

    def _add(ip: str):
        if not ip or ip.startswith("127.") or ip.startswith("169.254."):
            return
        base = ip.rsplit(".", 1)[0]
        if base not in seen:
            seen.add(base)
            bases.append(base)

    _add(_primary_ipv4())
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            _add(info[4][0])
    except Exception:
        pass
    return bases or ["192.168.1"]


_SWEEP_PORTS = (80, 443, 22, 445, 7)     # tocamos varios: alguno suele contestar


async def _touch_port(ip: str, port: int) -> bool:
    """Intenta abrir TCP. 'Abierto' o 'rechazado' (RST) = HOST VIVO. El propio intento
    fuerza la resolución ARP, así que RELLENA la tabla ARP aunque no haya servicio."""
    try:
        fut = asyncio.open_connection(ip, port)
        _, w = await asyncio.wait_for(fut, timeout=0.6)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True
    except (ConnectionRefusedError, ConnectionResetError):
        return True                      # respondió con RST → está vivo
    except Exception:
        return False


async def _touch_host(ip: str, sem: asyncio.Semaphore) -> str | None:
    async with sem:
        oks = await asyncio.gather(*[_touch_port(ip, p) for p in _SWEEP_PORTS],
                                   return_exceptions=True)
    return ip if any(o is True for o in oks) else None


async def _ping_sweep(timeout: float = 6.0) -> set:
    """Barre .1–.254 de cada subred en paralelo (como el 'buscar' del Bluetooth).
    Usa TCP en vez de ICMP: no depende de 'ping' ni del tipo de event-loop, y el
    intento RELLENA la tabla ARP con la MAC de cada aparato. Los que contestan
    (abierto o RST) se marcan como 'vivos seguro'. Devuelve ese conjunto de IPs."""
    sem = asyncio.Semaphore(96)
    tasks = []
    for base in _subnets()[:3]:            # como mucho 3 subredes
        for i in range(1, 255):
            tasks.append(_touch_host(f"{base}.{i}", sem))
    if not tasks:
        return set()
    try:
        done = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True),
                                      timeout=timeout)
    except asyncio.TimeoutError:
        done = []
    return {ip for ip in done if isinstance(ip, str)}


# OUI → fabricante (primeros 3 bytes de la MAC). Foco en marcas de casa/consumo.
_MAC_VENDORS = {
    # Apple
    "F0:18:98": "Apple", "A4:83:E7": "Apple", "3C:06:30": "Apple", "AC:BC:32": "Apple",
    "D0:03:4B": "Apple", "F4:0F:24": "Apple", "68:AB:1E": "Apple", "88:66:5A": "Apple",
    "00:03:93": "Apple", "00:CD:FE": "Apple", "DC:2B:2A": "Apple", "F8:E9:4E": "Apple",
    # Samsung
    "00:12:FB": "Samsung", "5C:0A:5B": "Samsung", "8C:71:F8": "Samsung", "BC:72:B1": "Samsung",
    "78:BD:BC": "Samsung", "1C:62:B8": "Samsung", "E8:50:8B": "Samsung", "F0:5A:09": "Samsung",
    "94:35:0A": "Samsung", "AC:5F:3E": "Samsung",
    # LG
    "00:1C:62": "LG", "00:1E:75": "LG", "10:F1:F2": "LG", "A0:39:F7": "LG", "C4:36:6C": "LG",
    "58:A2:B5": "LG", "88:36:6C": "LG",
    # Sony
    "00:13:A9": "Sony", "FC:0F:E6": "Sony", "54:42:49": "Sony", "D8:D4:3C": "Sony",
    # Google / Nest / Chromecast
    "F4:F5:D8": "Google", "F4:F5:E8": "Google", "1C:F2:9A": "Google", "20:DF:B9": "Google",
    "48:D6:D5": "Google", "6C:AD:F8": "Google", "94:EB:2C": "Google", "DA:A1:19": "Google",
    # Amazon (Echo / Fire TV)
    "68:37:E9": "Amazon", "FC:65:DE": "Amazon", "44:65:0D": "Amazon", "50:DC:E7": "Amazon",
    "74:C2:46": "Amazon", "F0:27:2D": "Amazon", "AC:63:BE": "Amazon", "40:B4:CD": "Amazon",
    # Xiaomi / smart home
    "78:11:DC": "Xiaomi", "64:09:80": "Xiaomi", "F0:B4:29": "Xiaomi", "50:EC:50": "Xiaomi",
    "34:CE:00": "Xiaomi", "28:6C:07": "Xiaomi", "A4:C1:38": "Xiaomi/BLE",
    # Espressif (ESP8266/ESP32 — casi toda la domótica DIY/enchufes/bombillas baratas)
    "24:0A:C4": "Espressif (IoT)", "3C:71:BF": "Espressif (IoT)", "84:CC:A8": "Espressif (IoT)",
    "A0:20:A6": "Espressif (IoT)", "5C:CF:7F": "Espressif (IoT)", "18:FE:34": "Espressif (IoT)",
    "EC:FA:BC": "Espressif (IoT)", "30:AE:A4": "Espressif (IoT)", "7C:9E:BD": "Espressif (IoT)",
    "C4:4F:33": "Espressif (IoT)", "BC:DD:C2": "Espressif (IoT)", "DC:4F:22": "Espressif (IoT)",
    # Tuya (enchufes/bombillas Wi-Fi de marca blanca)
    "10:D5:61": "Tuya (IoT)", "50:02:91": "Tuya (IoT)", "68:57:2D": "Tuya (IoT)",
    "D8:1F:12": "Tuya (IoT)", "84:E3:42": "Tuya (IoT)",
    # Sonos / Philips Hue / Ring
    "00:0E:58": "Sonos", "5C:AA:FD": "Sonos", "48:A6:B8": "Sonos", "94:9F:3E": "Sonos",
    "00:17:88": "Philips Hue", "EC:B5:FA": "Philips Hue",
    "B0:09:DA": "Ring", "F0:81:73": "Ring",
    # Routers / red
    "00:1D:AA": "Router (D-Link)", "C0:25:E9": "Router (TP-Link)", "50:C7:BF": "TP-Link",
    "EC:08:6B": "TP-Link", "A4:2B:B0": "TP-Link", "14:CC:20": "TP-Link",
    "10:BE:F5": "Router (Movistar)", "F8:8E:85": "Router (Comtrend)", "5C:33:8E": "Router",
    "44:32:C8": "Router (Technicolor)", "84:26:15": "Router (Technicolor)",
    # PCs / genéricos
    "00:15:5D": "PC (Hyper-V)", "08:00:27": "PC (VirtualBox)", "52:54:00": "PC (QEMU/KVM)",
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
    "00:1A:2B": "Impresora", "00:26:73": "Impresora (HP)", "3C:D9:2B": "Impresora (HP)",
    "9C:93:4E": "Impresora (Xerox)", "00:00:48": "Impresora (Epson)", "A4:5D:36": "HP",
    "3C:2A:F4": "Impresora (Brother)", "00:80:77": "Impresora (Brother)",
}

# Más OUI de consumo: móviles, portátiles, TVs, consolas y routers domésticos.
_MAC_VENDORS.update({
    # Apple (móviles/iPad/Mac — muy comunes)
    "04:0C:CE": "Apple", "28:CF:E9": "Apple", "28:E7:CF": "Apple", "3C:15:C2": "Apple",
    "40:6C:8F": "Apple", "5C:95:AE": "Apple", "60:FB:42": "Apple", "6C:70:9F": "Apple",
    "70:CD:60": "Apple", "7C:D1:C3": "Apple", "8C:58:77": "Apple", "90:B2:1F": "Apple",
    "A4:D1:8C": "Apple", "A8:66:7F": "Apple", "AC:3C:0B": "Apple", "B8:17:C2": "Apple",
    "BC:52:B7": "Apple", "C0:9F:42": "Apple", "C8:BC:C8": "Apple", "D0:23:DB": "Apple",
    "DC:A9:04": "Apple", "E0:B9:BA": "Apple", "F0:DB:F8": "Apple", "F4:37:B7": "Apple",
    "FC:FC:48": "Apple", "00:16:CB": "Apple", "00:23:12": "Apple", "44:00:10": "Apple",
    "68:5B:35": "Apple", "84:38:35": "Apple", "A8:BB:CF": "Apple", "E4:CE:8F": "Apple",
    # Samsung (móviles/TVs)
    "08:37:3D": "Samsung", "0C:14:20": "Samsung", "14:49:E0": "Samsung", "1C:5A:3E": "Samsung",
    "20:64:32": "Samsung", "28:39:5E": "Samsung", "2C:44:01": "Samsung", "30:19:66": "Samsung",
    "34:23:BA": "Samsung", "38:AA:3C": "Samsung", "3C:5A:37": "Samsung", "44:F4:59": "Samsung",
    "5C:E8:EB": "Samsung", "84:25:DB": "Samsung", "8C:77:12": "Samsung", "94:D7:71": "Samsung",
    "B4:3A:28": "Samsung", "C4:73:1E": "Samsung", "D0:22:BE": "Samsung", "E4:B0:21": "Samsung",
    "EC:1F:72": "Samsung", "F0:08:F1": "Samsung", "10:D5:42": "Samsung", "24:4B:03": "Samsung",
    # Xiaomi / Redmi
    "0C:1D:AF": "Xiaomi", "14:F6:5A": "Xiaomi", "18:59:36": "Xiaomi", "20:82:C0": "Xiaomi",
    "34:80:B3": "Xiaomi", "3C:BD:3E": "Xiaomi", "44:23:7C": "Xiaomi", "50:8F:4C": "Xiaomi",
    "58:44:98": "Xiaomi", "64:B4:73": "Xiaomi", "68:DF:DD": "Xiaomi", "74:23:44": "Xiaomi",
    "7C:1D:D9": "Xiaomi", "8C:BE:BE": "Xiaomi", "98:FA:E3": "Xiaomi", "9C:99:A0": "Xiaomi",
    "AC:C1:EE": "Xiaomi", "B0:E2:35": "Xiaomi", "C4:6A:B7": "Xiaomi", "F8:A4:5F": "Xiaomi",
    # Huawei / Honor
    "04:BD:70": "Huawei", "0C:37:DC": "Huawei", "10:47:80": "Huawei", "18:C5:8A": "Huawei",
    "20:F1:7C": "Huawei", "24:09:95": "Huawei", "28:31:52": "Huawei", "34:6B:D3": "Huawei",
    "3C:DF:BD": "Huawei", "44:6E:E5": "Huawei", "48:46:FB": "Huawei", "54:25:EA": "Huawei",
    "5C:7D:5E": "Huawei", "60:DE:44": "Huawei", "70:72:3C": "Huawei", "80:B6:86": "Huawei",
    "88:E3:AB": "Huawei", "A4:99:47": "Huawei", "AC:E2:15": "Huawei", "BC:76:70": "Huawei",
    "C8:94:BB": "Huawei", "D4:6E:5C": "Huawei", "E8:BD:D1": "Huawei", "F4:55:9C": "Huawei",
    # OnePlus / Google / Nest
    "94:65:2D": "OnePlus", "C0:EE:FB": "OnePlus", "64:A2:F9": "OnePlus", "AC:37:43": "OnePlus",
    "3C:28:6D": "Google", "94:95:A0": "Google", "9C:D3:5B": "Google", "38:8B:59": "Google",
    "D4:F5:47": "Google", "64:16:66": "Google/Nest", "AC:67:84": "Google/Nest",
    # Intel (WiFi de portátiles)
    "3C:A9:F4": "Intel (portátil)", "44:85:00": "Intel (portátil)", "48:51:B7": "Intel (portátil)",
    "5C:E0:C5": "Intel (portátil)", "7C:B0:C2": "Intel (portátil)", "84:3A:4B": "Intel (portátil)",
    "8C:16:45": "Intel (portátil)", "94:65:9C": "Intel (portátil)", "A4:34:D9": "Intel (portátil)",
    "AC:7B:A1": "Intel (portátil)", "B4:6B:FC": "Intel (portátil)", "C4:85:08": "Intel (portátil)",
    "D8:F2:CA": "Intel (portátil)", "E4:A7:A0": "Intel (portátil)", "90:E8:68": "Intel (portátil)",
    "34:C9:3D": "Intel (portátil)", "08:11:96": "Intel (portátil)",
    # Roku / consolas
    "DC:3A:5E": "Roku (TV)", "B0:A7:37": "Roku (TV)", "D8:31:34": "Roku (TV)", "AC:3A:7A": "Roku (TV)",
    "88:DE:A9": "Roku (TV)", "CC:6D:A0": "Roku (TV)", "B8:3E:59": "Roku (TV)",
    "34:AF:2C": "Nintendo", "58:BD:A3": "Nintendo", "7C:BB:8A": "Nintendo", "8C:56:C5": "Nintendo",
    "98:B6:E9": "Nintendo", "9C:E6:35": "Nintendo", "A4:38:CC": "Nintendo", "CC:9E:00": "Nintendo",
    "2C:CC:44": "PlayStation", "70:9E:29": "PlayStation", "A8:E3:EE": "PlayStation",
    "BC:60:A7": "PlayStation", "C8:63:F1": "PlayStation",
    "00:17:FA": "Xbox/Microsoft", "3C:83:75": "Microsoft", "58:82:A8": "Xbox", "98:5F:D3": "Xbox",
    "9C:AA:1B": "Xbox", "C4:9D:ED": "Microsoft", "D0:57:7B": "Microsoft", "E4:98:D6": "Microsoft",
    # Routers / repetidores comunes
    "A0:63:91": "Router (Netgear)", "20:E5:2A": "Router (Netgear)", "9C:3D:CF": "Router (Netgear)",
    "2C:56:DC": "Asus", "AC:22:0B": "Asus", "D0:17:C2": "Asus", "50:46:5D": "Asus",
    "C8:3A:35": "Tenda", "70:4F:57": "Router (Movistar)", "F0:8B:FE": "Router",
})


def _mac_vendor(mac: str) -> str:
    """Fabricante a partir de la MAC (prefijo OUI). '' si no lo conocemos."""
    if not mac:
        return ""
    oui = mac.upper().replace("-", ":")[:8]
    return _MAC_VENDORS.get(oui, "")


# ------------------------------------------------------------------- mDNS/Bonjour
_MDNS_SERVICES = [
    "_services._dns-sd._udp.local", "_googlecast._tcp.local", "_airplay._tcp.local",
    "_raop._tcp.local", "_spotify-connect._tcp.local", "_hap._tcp.local",
    "_printer._tcp.local", "_ipp._tcp.local", "_ipps._tcp.local", "_http._tcp.local",
    "_workstation._tcp.local", "_smb._tcp.local", "_ssh._tcp.local",
    "_amzn-wplay._tcp.local", "_androidtvremote2._tcp.local", "_miio._udp.local",
    "_home-assistant._tcp.local", "_esphomelib._tcp.local", "_sonos._tcp.local",
]

# etiqueta legible por tipo de servicio mDNS
_MDNS_LABEL = {
    "googlecast": "Chromecast/Google", "airplay": "AirPlay", "raop": "AirPlay (audio)",
    "spotify-connect": "Spotify Connect", "hap": "HomeKit", "printer": "Impresora",
    "ipp": "Impresora", "ipps": "Impresora", "smb": "Compartición (SMB)",
    "ssh": "SSH", "workstation": "Ordenador", "amzn-wplay": "Fire TV/Amazon",
    "androidtvremote2": "Android TV", "miio": "Xiaomi", "home-assistant": "Home Assistant",
    "esphomelib": "ESPHome (IoT)", "sonos": "Sonos",
}


def _dns_name(data: bytes, off: int) -> tuple[str, int]:
    """Lee un nombre DNS (con punteros de compresión). Devuelve (nombre, offset_tras)."""
    labels, jumped, orig_off = [], False, off
    hops = 0
    while True:
        if off >= len(data) or hops > 30:
            break
        length = data[off]
        if length == 0:
            off += 1
            break
        if length & 0xC0 == 0xC0:                       # puntero de compresión
            ptr = ((length & 0x3F) << 8) | data[off + 1]
            if not jumped:
                orig_off = off + 2
            off = ptr
            jumped = True
            hops += 1
            continue
        labels.append(data[off + 1:off + 1 + length].decode("utf-8", "replace"))
        off += 1 + length
    return ".".join(labels), (orig_off if jumped else off)


def _mdns_parse(pkt: bytes) -> tuple[set, set]:
    """Extrae de una respuesta mDNS: (nombres_legibles, tipos_de_servicio)."""
    names, services = set(), set()
    try:
        qd = int.from_bytes(pkt[4:6], "big")
        an = int.from_bytes(pkt[6:8], "big")
        ns = int.from_bytes(pkt[8:10], "big")
        ar = int.from_bytes(pkt[10:12], "big")
        off = 12
        for _ in range(qd):                              # saltar preguntas
            _, off = _dns_name(pkt, off)
            off += 4
        for _ in range(an + ns + ar):
            rname, off = _dns_name(pkt, off)
            if off + 10 > len(pkt):
                break
            rtype = int.from_bytes(pkt[off:off + 2], "big")
            rdlen = int.from_bytes(pkt[off + 8:off + 10], "big")
            rdata_off = off + 10
            # nombre de servicio → etiqueta de tipo
            for tok, lab in _MDNS_LABEL.items():
                if "_" + tok + "." in rname:
                    services.add(lab)
            if rtype in (12, 33):                        # PTR / SRV → nombre de instancia
                nm, _ = _dns_name(pkt, rdata_off if rtype == 12 else rdata_off + 6)
                inst = nm.split("._")[0].replace(".local", "").strip()
                if inst and not inst.startswith("_") and len(inst) > 1:
                    names.add(inst)
            elif rtype == 1 and rdlen == 4:              # A → hostname
                host = rname.replace(".local", "").strip(".")
                if host and not host.startswith("_"):
                    names.add(host)
            off = rdata_off + rdlen
    except Exception:
        pass
    return names, services


def _mdns_discover(timeout: float = 3.0) -> dict:
    """Consulta mDNS (224.0.0.251:5353) por los servicios típicos de casa. Cada
    respuesta llega DESDE el aparato → mapeamos por IP de origen. {ip:{names,services}}."""
    def _q(name: str) -> bytes:
        pkt = bytearray(b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        for part in name.split("."):
            pkt += bytes([len(part)]) + part.encode()
        pkt += b"\x00\x00\x0c\x00\x01"                   # QTYPE=PTR QCLASS=IN
        return bytes(pkt)

    found: dict = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.settimeout(timeout)
        for svc in _MDNS_SERVICES:
            try:
                s.sendto(_q(svc), ("224.0.0.251", 5353))
            except Exception:
                pass
        import time as _t
        t0 = _t.monotonic()
        while _t.monotonic() - t0 < timeout:
            try:
                data, addr = s.recvfrom(9000)
            except socket.timeout:
                break
            except Exception:
                break
            ip = addr[0]
            names, services = _mdns_parse(data)
            e = found.setdefault(ip, {"names": set(), "services": set()})
            e["names"] |= names
            e["services"] |= services
        s.close()
    except Exception:
        pass
    return found


# ---------------------------------------------------- sondeo de puertos → tipo
_PORT_HINTS = {
    8060: "TV Roku", 8001: "TV Samsung", 8002: "TV Samsung", 55000: "TV Samsung",
    8008: "Chromecast", 8009: "Chromecast", 7000: "AirPlay",
    32400: "Servidor Plex", 8123: "Home Assistant", 1883: "IoT (MQTT)",
    9100: "Impresora", 631: "Impresora (IPP)", 554: "Cámara IP (RTSP)",
    445: "PC/servidor (SMB)", 3389: "PC Windows (escritorio remoto)",
    22: "Linux/servidor (SSH)", 62078: "iPhone/iPad", 5353: "mDNS",
    53: "Router/DNS", 8080: "Web/panel",
}


async def _try_port(ip: str, port: int) -> bool:
    try:
        fut = asyncio.open_connection(ip, port)
        _, w = await asyncio.wait_for(fut, timeout=0.4)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _probe_ports(ip: str, sem: asyncio.Semaphore) -> str:
    """Toca los puertos característicos EN PARALELO (≈0.4 s por host, no por puerto)
    y devuelve la etiqueta del más significativo que esté abierto. '' si ninguno."""
    async with sem:
        ports = list(_PORT_HINTS.keys())
        oks = await asyncio.gather(*[_try_port(ip, p) for p in ports],
                                   return_exceptions=True)
    for port, ok in zip(ports, oks):        # orden de _PORT_HINTS = prioridad
        if ok is True:
            return _PORT_HINTS[port]
    return ""


async def _reverse_dns(ip: str, sem: asyncio.Semaphore) -> str:
    async with sem:
        try:
            host = await asyncio.wait_for(
                asyncio.to_thread(lambda: socket.gethostbyaddr(ip)[0]), timeout=1.0)
            return (host or "").split(".")[0]
        except Exception:
            return ""


def _netbios_name(ip: str) -> str:
    """Nombre NetBIOS del equipo (nombre de PC Windows) por UDP 137. En redes de casa
    es lo que DE VERDAD da el nombre real (el DNS inverso casi nunca resuelve). '' si el
    aparato no responde (los móviles/Apple no suelen tener NetBIOS)."""
    name_enc = b"\x20" + b"CK" + b"A" * 30 + b"\x00"      # nombre comodin "*" codificado
    q = b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00" + name_enc + b"\x00\x21\x00\x01"
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.7)
        s.sendto(q, (ip, 137))
        data, _ = s.recvfrom(2048)
    except Exception:
        return ""
    finally:
        try:
            if s:
                s.close()
        except Exception:
            pass
    try:
        count = data[56]
        names = data[57:]
        for i in range(min(count, 30)):
            entry = names[i * 18:i * 18 + 18]
            if len(entry) < 18:
                break
            nm = entry[:15].decode("latin-1", "ignore").replace("\x00", "").strip()
            suffix = entry[15]
            group = bool((entry[16] << 8 | entry[17]) & 0x8000)
            if suffix == 0x00 and not group and nm and nm != "__MSBROWSE__":
                return nm
    except Exception:
        pass
    return ""


async def _netbios_lookup(ip: str, sem: asyncio.Semaphore) -> str:
    async with sem:
        return await asyncio.to_thread(_netbios_name, ip)


def _known(ctx) -> list[dict]:
    return list(ctx["settings"].get("known_devices", []) or [])


_TV_CACHE: dict = {"tv": None, "ts": 0.0}


def _mac_for_ip(ip: str) -> str:
    """MAC de una IP según la tabla ARP del sistema ('' si no aparece)."""
    if not ip:
        return ""
    for e in _arp_table():
        if e.get("ip") == ip:
            return e.get("mac", "")
    return ""


def _ip_for_mac(mac: str) -> str:
    """IP ACTUAL de una MAC según la tabla ARP del sistema ('' si no aparece).
    La IP la reparte el router por DHCP y caduca; la MAC no cambia nunca."""
    m = (mac or "").replace("-", ":").strip().lower()
    if not m:
        return ""
    for e in _arp_table():
        if (e.get("mac") or "").lower() == m:
            return e.get("ip", "")
    return ""


def _save_ip(ctx, mac: str, ip: str) -> None:
    """Anota la IP nueva de una MAC en my_devices y en known_devices."""
    m = (mac or "").replace("-", ":").strip().lower()
    if not m or not ip:
        return
    try:
        for clave in ("my_devices", "known_devices"):
            devs = list(ctx["settings"].get(clave, []) or [])
            tocado = False
            for d in devs:
                if (d.get("mac") or "").replace("-", ":").lower() == m and d.get("ip") != ip:
                    d["ip"] = ip
                    tocado = True
            if tocado:
                ctx["settings"].set(clave, devs)
    except Exception:
        pass


def _save_tv(ctx, tv: dict) -> None:
    """Persiste la TV en known_devices (⚙) para NO re-escanear en cada orden."""
    try:
        devs = _known(ctx)
        for d in devs:
            if (tv.get("ip") and d.get("ip") == tv.get("ip")) or \
               (tv.get("mac") and (d.get("mac") or "").lower() == tv["mac"].lower()):
                d.update({k: v for k, v in tv.items() if v})
                d["is_tv"] = True
                break
        else:
            devs.append(dict(tv, is_tv=True))
        ctx["settings"].set("known_devices", devs)
    except Exception:
        pass


def _save_estado(ctx, tv: dict, encendido: bool) -> None:
    """Guarda en known_devices si el aparato quedó ENCENDIDO o APAGADO, para que el
    estado sobreviva al reinicio."""
    import datetime as _dt
    try:
        devs = _known(ctx)
        for d in devs:
            if (tv.get("ip") and d.get("ip") == tv.get("ip")) or \
               (tv.get("mac") and (d.get("mac") or "").lower() == (tv.get("mac") or "").lower()):
                d["on"] = bool(encendido)
                d["on_ts"] = _dt.datetime.now().isoformat(timespec="seconds")
                d["is_tv"] = True
                break
        else:
            devs.append({"ip": tv.get("ip", ""), "mac": tv.get("mac", ""),
                         "brand": tv.get("brand", ""), "is_tv": True,
                         "on": bool(encendido)})
        ctx["settings"].set("known_devices", devs)
    except Exception:
        pass


def _mark_paired(ctx, tv: dict, paired: bool = True) -> None:
    """Persiste que el aparato quedó EMPAREJADO (permiso aceptado en su pantalla), para
    que la UI lo muestre como conectado tras reiniciar o reescanear."""
    try:
        devs = _known(ctx)
        for d in devs:
            if (tv.get("ip") and d.get("ip") == tv.get("ip")) or \
               (tv.get("mac") and (d.get("mac") or "").lower() == (tv.get("mac") or "").lower()):
                d["paired"] = paired
                d["is_tv"] = True
                break
        else:
            devs.append({"ip": tv.get("ip", ""), "mac": tv.get("mac", ""),
                         "brand": tv.get("brand", ""), "is_tv": True, "paired": paired})
        ctx["settings"].set("known_devices", devs)
    except Exception:
        pass


# Palabras del nombre de una TV que NO sirven para distinguirla de otra TV: o
# las lleva cualquiera («tv», «tele») o son la marca, y con dos Samsung en casa
# la marca no desempata.
_PALABRAS_SIN_VALOR_ENTRE_TVS = {
    "tv", "tvs", "tele", "teles", "television", "televisor", "televisores",
    "smart", "samsung", "roku", "sony", "philips", "hisense", "xiaomi",
    "generic", "generica", "pantalla", "monitor",
}


def _clave_fonetica(palabra: str) -> str:
    """Cómo SUENA una palabra, en castellano y sin adornos.

    El dictado por voz escribe mal los nombres propios, y un nombre guardado
    puede tener una errata («salóm» por «salón»). Comparar letra a letra falla en
    los dos casos aunque suenen igual, así que primero se reduce cada palabra a
    su sonido: se quitan tildes, la hache muda, y se unifican los pares que en
    castellano suenan idéntico (qu/c → k, z → s, v → b, ll → y)."""
    s = _norm_txt(palabra)
    s = re.sub(r"[^a-z]", "", s)
    for viejo, nuevo in (("qu", "k"), ("gu", "g"), ("ll", "y"), ("c", "k"),
                         ("z", "s"), ("v", "b"), ("h", "")):
        s = s.replace(viejo, nuevo)
    return s


# Cuánto tienen que parecerse dos sonidos para darlos por el mismo nombre.
# Medido con lo que dictó el micro sobre un nombre real: sus dos transcripciones
# erróneas dieron 0,77 y 0,67; una palabra ajena al nombre se quedó en 0,27, muy
# lejos. 0,66 los separa con aire.
_PARECIDO_MINIMO = 0.66


def _suena_como(tv: dict, text: str) -> float:
    """Cuánto se parece el nombre de esta TV a lo que se ha dicho (0 a 1)."""
    import difflib
    propias = [w for w in re.findall(r"[a-z0-9]+", _norm_txt(tv.get("name") or ""))
               if len(w) >= 4 and w not in _PALABRAS_SIN_VALOR_ENTRE_TVS]
    dichas = [w for w in re.findall(r"[a-z0-9]+", _norm_txt(text)) if len(w) >= 4]
    mejor = 0.0
    for p in propias:
        cp = _clave_fonetica(p)
        for d in dichas:
            mejor = max(mejor, difflib.SequenceMatcher(None, cp,
                                                       _clave_fonetica(d)).ratio())
    return mejor


def _nombre_de_tv_en_la_frase(d: dict, text: str) -> bool:
    """¿La frase nombra a ESTA TV? Vale cualquier palabra propia de su nombre,
    incluida la estancia, porque aquí ya solo se elige entre televisiones."""
    tn = _norm_txt(text)
    nn = _norm_txt(d.get("name") or "")
    if not nn:
        return False
    if nn in tn:
        return True
    propias = [w for w in re.findall(r"[a-z0-9]+", nn)
               if len(w) >= 4 and w not in _PALABRAS_SIN_VALOR_ENTRE_TVS]
    return any(re.search(rf"\b{re.escape(w)}\b", tn) for w in propias)


def _tvs_guardadas(ctx) -> list[dict]:
    """Las TVs que tienes configuradas, sin repetir.

    `my_devices` y `known_devices` listan los mismos aparatos, así que se
    deduplica por MAC —lo único estable— y gana la ficha de `my_devices`, que es
    la que tú mantienes. Sin deduplicar, dos TVs parecen cuatro."""
    vistas: dict[str, dict] = {}
    for origen in (ctx["settings"].get("my_devices", []) or [], _known(ctx)):
        for d in origen:
            if not _is_tv_device(d):
                continue
            clave = (d.get("mac") or "").replace("-", ":").lower() or (d.get("ip") or "")
            if clave and clave not in vistas:
                vistas[clave] = d
    return list(vistas.values())


# La última TV que nombraste, por canal. Diez minutos.
#
# Sin esto, decir «la de la habitación» y a la orden siguiente volver a
# preguntarte cuál es lo que hace una máquina, no alguien con quien hablas. No es
# adivinar: solo se guarda lo que has dicho TÚ, y se olvida enseguida.
_ULTIMA_TV: dict[str, dict] = {}
_MEMORIA_TV = 600.0


def _canal(ctx) -> str:
    return (ctx.get("channel") or "pc") if hasattr(ctx, "get") else "pc"


def _recuerda_tv(ctx, tv: dict) -> None:
    _ULTIMA_TV[_canal(ctx)] = {"tv": dict(tv), "ts": time.monotonic()}


def _tv_recordada(ctx, tvs: list[dict]) -> dict | None:
    """La última que nombraste, si sigue siendo una de las que hay y no ha
    caducado."""
    guardada = _ULTIMA_TV.get(_canal(ctx))
    if not guardada or time.monotonic() - guardada["ts"] > _MEMORIA_TV:
        return None
    mac = (guardada["tv"].get("mac") or "").lower()
    for d in tvs:
        if mac and (d.get("mac") or "").lower() == mac:
            return d
    return None


async def _elegir_tv(ctx, text: str) -> tuple[dict | None, list[dict]]:
    """(la TV que toca, las candidatas si NO se puede decidir).

    Antes se devolvía siempre la PRIMERA TV de la lista sin mirar la frase: «la
    de la habitación» y «la del salón» acababan las dos en la misma, y que
    acertara dependía del orden de la lista.

    Ahora manda el nombre que digas. Si no nombras ninguna y hay más de una, no
    se elige por ti: se pregunta. Actuar sobre un aparato que no has nombrado es
    peor que preguntar."""
    nombrada = _resolve_named_device(ctx, text)
    if nombrada and _is_tv_device(nombrada):
        _recuerda_tv(ctx, nombrada)
        return nombrada, []
    tvs = _tvs_guardadas(ctx)
    if len(tvs) == 1:
        return tvs[0], []
    if len(tvs) > 1:
        # Aquí ya sabemos que la orden es de TV, así que la ESTANCIA sirve para
        # elegir entre ellas. `_resolve_named_device` las descarta a propósito,
        # pero por otro motivo: allí decide si la frase es de una TV o de una luz,
        # y «salón» a secas no puede decidir eso. Elegir entre dos TVs, sí.
        casan = [d for d in tvs if _nombre_de_tv_en_la_frase(d, text)]
        if not casan:
            # Último recurso: por cómo SUENA. El dictado se come los nombres
            # propios, y un nombre guardado puede llevar una errata. Solo vale
            # si señala a UNA sola: entre dos parecidas se pregunta, porque
            # actuar sobre la que no era es peor que preguntar.
            sonando = sorted(((_suena_como(d, text), d) for d in tvs),
                             key=lambda x: x[0], reverse=True)
            if sonando and sonando[0][0] >= _PARECIDO_MINIMO and (
                    len(sonando) == 1 or sonando[0][0] - sonando[1][0] >= 0.15):
                casan = [sonando[0][1]]
        if len(casan) == 1:
            _recuerda_tv(ctx, casan[0])
            return casan[0], []
        if not casan:
            recordada = _tv_recordada(ctx, tvs)
            if recordada:
                return recordada, []
        return None, casan or tvs
    return await _resolve_tv(ctx), []       # ninguna guardada: a buscarla por la red


async def _resolve_tv(ctx) -> dict | None:
    """Elige la TV a controlar sin bloquear el loop. Por orden: known_devices
    (instantáneo) -> caché de 10 min -> SSDP en un hilo -> escaneo completo. Lo
    encontrado se persiste con su MAC (tabla ARP) para que la siguiente orden sea
    inmediata y el encendido por Wake-on-LAN sea posible."""
    for d in _known(ctx):
        if "tv" in (d.get("brand", "") + d.get("name", "")).lower() or d.get("is_tv"):
            if not d.get("mac") and d.get("ip"):
                mac = await asyncio.to_thread(_mac_for_ip, d["ip"])
                if mac:
                    d["mac"] = mac
                    _save_tv(ctx, d)
            return d
    now = time.monotonic()
    if _TV_CACHE["tv"] and now - _TV_CACHE["ts"] < 600:
        return _TV_CACHE["tv"]

    def _scan():
        for ip, info in _ssdp_discover(2.5).items():
            t = _guess_type(info["server"], info["st"])
            if t.startswith("TV"):
                brand = ("roku" if "Roku" in t else "samsung" if "Samsung" in t
                         else "lg" if "LG" in t else "generic")
                return {"name": t, "ip": ip, "brand": brand,
                        "mac": _mac_for_ip(ip), "is_tv": True}
        return None

    tv = await asyncio.to_thread(_scan)
    if not tv:
        # Último recurso: el descubrimiento completo ve TVs que el SSDP rápido no ve
        # (mDNS, sondeo de puertos, marca por MAC). Misma heurística que el buscador.
        try:
            scan = await _discover_all(ctx)
            for ip in sorted(scan["devices"], key=_ip_key):
                dev = scan["devices"][ip]
                brand = _dev_brand(dev)
                if _dev_is_tv(dev) or brand in ("roku", "samsung", "lg", "sony"):
                    tv = {"name": _label_device(dev) or "TV", "ip": ip,
                          "brand": brand if brand != "generic" else "generic",
                          "mac": dev.get("mac") or _mac_for_ip(ip), "is_tv": True}
                    break
        except Exception:
            tv = None
    if tv:
        _TV_CACHE.update(tv=tv, ts=now)
        _save_tv(ctx, tv)
    return tv


# ---------------------------------------------------------------- Wake-on-LAN
def wake_on_lan(mac: str, broadcast: str = "255.255.255.255") -> bool:
    """Envía el paquete mágico para encender un equipo/TV por su MAC."""
    hexmac = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(hexmac) != 12:
        return False
    packet = b"\xff" * 6 + bytes.fromhex(hexmac) * 16
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            s.sendto(packet, (broadcast, port))
        s.close()
        return True
    except Exception:
        return False


def _wol_burst(mac: str, ip: str = "", broadcast: str = "") -> bool:
    """Ráfaga Wake-on-LAN: broadcast global, broadcast de la subred del aparato y
    UNICAST a su última IP, por los puertos 9 y 7, repetido 3 veces. Las TVs por WiFi
    (WoWLAN) muchas veces solo despiertan con el paquete dirigido a su IP."""
    hexmac = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(hexmac) != 12:
        return False
    packet = b"\xff" * 6 + bytes.fromhex(hexmac) * 16
    dests = ["255.255.255.255"]
    if broadcast:
        dests.append(broadcast)
    if ip and ip.count(".") == 3:
        dests.append(".".join(ip.split(".")[:3]) + ".255")   # broadcast de su subred
        dests.append(ip)                                     # unicast (WoWLAN)
    ok = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for n in range(3):
            for d in dict.fromkeys(dests):
                for port in (9, 7):
                    try:
                        s.sendto(packet, (d, port))
                        ok = True
                    except OSError:
                        pass
            if n < 2:
                time.sleep(0.12)
        s.close()
    except Exception:
        return ok
    return ok


async def _tv_esta_viva(ip: str, timeout: float = 1.2) -> bool:
    """¿La TV responde en su puerto de control? (Roku 8060 / Samsung 8001-8002).
    Si responde, está ENCENDIDA o en reposo con red: acepta órdenes directas.

    Los tres puertos se prueban A LA VEZ. En serie, una TV apagada costaba tres
    esperas completas seguidas, y esta comprobación se hace varias veces por
    orden."""
    if not ip:
        return False

    async def _puerto(p: int) -> bool:
        try:
            _r, w = await asyncio.wait_for(asyncio.open_connection(ip, p), timeout=timeout)
            w.close()
            return True
        except Exception:
            return False

    return any(await asyncio.gather(*(_puerto(p) for p in (8001, 8002, 8060))))


async def _tv_ip_actual(ctx, tv: dict) -> tuple[str, bool]:
    """(IP por la que se puede hablar AHORA con el aparato, si contesta por ella).

    La IP guardada caduca (DHCP); la MAC no. Si la guardada no contesta, se busca
    la MAC en la tabla ARP y, si sale otra IP, se actualiza la configuración.

    Devuelve también si contesta porque para saberlo ya ha habido que preguntar:
    que lo vuelva a preguntar quien llama es pagar la misma espera dos veces."""
    ip = (tv.get("ip") or "").strip()
    mac = (tv.get("mac") or "").strip()
    if ip and await _tv_esta_viva(ip):
        return ip, True
    if not mac:
        return ip, False
    nueva = await asyncio.to_thread(_ip_for_mac, mac)
    if nueva and nueva != ip:
        _save_ip(ctx, mac, nueva)
        return nueva, await _tv_esta_viva(nueva)
    return nueva or ip, False


async def _samsung_power_state(ip: str) -> str:
    """`device.PowerState` de la API REST de una Samsung: 'on' | 'standby'.
    Devuelve '' si la TV no contesta o si el modelo no publica ese campo (los
    anteriores a la serie RU no lo traen)."""
    if not ip:
        return ""
    try:
        import httpx
    except Exception:
        return ""
    try:
        async with httpx.AsyncClient(timeout=2.5) as cli:
            r = await cli.get(f"http://{ip}:8001/api/v2/")
            data = r.json()
    except Exception:
        return ""
    return str((data.get("device") or {}).get("PowerState") or "").strip().lower()


async def _samsung_mute_upnp(ip: str) -> str:
    """`CurrentMute` del RenderingControl UPnP de una Samsung (puerto 9197):
    '0' | '1', o '' si no contesta.

    Es la única señal de encendido que dan los modelos que NO publican
    `PowerState`. Medido contra una UE32N4300 con el estado conocido: encendida
    responde 0; en reposo con la red viva, 1, estable en lecturas seguidas.

    Solo se usa el 0. El 1 es ambiguo —reposo, o encendida y silenciada— y
    confundirlos al revés significaría encender la tele al pedir que se apague."""
    if not ip:
        return ""
    try:
        import httpx
    except Exception:
        return ""
    svc = "urn:schemas-upnp-org:service:RenderingControl:1"
    cuerpo = ('<?xml version="1.0"?>'
              '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
              's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
              f'<u:GetMute xmlns:u="{svc}"><InstanceID>0</InstanceID>'
              '<Channel>Master</Channel></u:GetMute></s:Body></s:Envelope>')
    try:
        async with httpx.AsyncClient(timeout=2.5) as cli:
            r = await cli.post(f"http://{ip}:9197/upnp/control/RenderingControl1",
                               content=cuerpo.encode(),
                               headers={"Content-Type": 'text/xml; charset="utf-8"',
                                        "SOAPACTION": f'"{svc}#GetMute"'})
        m = re.search(r"<CurrentMute>(\d)</CurrentMute>", r.text)
        return m.group(1) if m else ""
    except Exception:
        return ""


async def _tv_estado(ip: str, tras_apagar: bool = False) -> str:
    """Estado REAL de la TV, preguntándoselo a ella:

      'off'  no contesta, o dice que está en reposo.
      'on'   dice que está encendida.
      'on?'  contesta pero no publica su estado: está encendida O en reposo con
             la red aún viva, y por esa vía no se pueden distinguir.

    `tras_apagar` es el contexto: acabamos de mandar el apagado a una TV que se
    sabía encendida, así que la señal ambigua deja de serlo. Toda lectura de
    estado pasa por aquí a propósito — con dos sitios que preguntan por su cuenta,
    acaban contestando cosas distintas.
    """
    if not ip:
        return "off"
    ps = await _samsung_power_state(ip)
    if ps:
        return "on" if ps == "on" else "off"
    # Los modelos que no publican `PowerState` sí delatan el encendido por UPnP.
    # Solo cuenta el 0: prueba que está encendida y con eso el interruptor es
    # seguro. El 1 no distingue reposo de encendida-y-silenciada, así que sigue
    # siendo «no lo sé» y se trata como tal.
    mute = await _samsung_mute_upnp(ip)
    if mute == "0":
        return "on"
    # Silenciada es ambiguo EN FRÍO: puede ser reposo o encendida sin volumen.
    # Justo después de mandar el apagado a una TV que estaba sonando, no: ahí
    # significa que ha obedecido.
    if mute == "1" and tras_apagar:
        return "off"
    if await _tv_esta_viva(ip):
        return "on?"
    return "off"


# Segundos que se espera antes de releer el estado tras mandar el apagado.
# Medido contra las TVs: de «encendida» a «reposo» tardan unos 3 s.
_ESPERA_APAGADO = 3.0

# Tope TOTAL de la orden de apagado, contando desde que entra.
# Apagar encadena sondeos de red: resolver la IP, leer el estado, mandar la
# tecla, esperar y releerlo. Cada uno falla por agotamiento y sin un tope común
# se suman: una TV desenchufada dejaba «apaga la tele» pensando medio minuto.
# Agotarlo no es un error, es dejar de esperar: la respuesta lo dice.
_LIMITE_APAGADO = 25.0


async def _o_agota(coro, segundos: float, por_defecto):
    """Espera a `coro` como mucho `segundos`; si no llega a tiempo, `por_defecto`."""
    try:
        return await asyncio.wait_for(coro, timeout=max(0.2, segundos))
    except asyncio.TimeoutError:
        return por_defecto


async def _confirma_apagado(ip: str, segundos: float) -> bool:
    """¿Se ha apagado? Se pregunta hasta que conteste o se acabe el tiempo.

    Una lectura única a los 3 s no vale: al pulsar el apagado la TV se cae de la
    red entera unos diez segundos y vuelve luego, ya en reposo. Preguntando una
    sola vez se cae justo en ese hueco y no se puede confirmar nada.

    Cuenta como apagada de dos formas: que deje de contestar, o que conteste
    diciendo que está silenciada. Lo segundo es ambiguo en frío —reposo, o
    encendida y sin volumen— pero aquí no: se acaba de mandar el apagado a una
    TV que se sabía encendida y sonando."""
    fin = time.monotonic() + max(2.0, segundos)
    while True:
        if await _tv_estado(ip, tras_apagar=True) == "off":
            return True
        if time.monotonic() >= fin:
            return False
        await asyncio.sleep(1.5)


async def _tv_apagar(ctx, tv: dict) -> dict:
    """APAGAR una TV: mirar el estado, elegir la tecla según lo que se SEPA, y
    comprobar el resultado.

    En Tizen hay dos teclas y la diferencia es justo la que importa: KEY_POWER
    apaga, pero es un interruptor y sobre una TV en reposo la ENCIENDE;
    KEY_POWEROFF no apaga (la acepta y la ignora) pero no puede encender nada.

    Por eso el interruptor SOLO se pulsa con el estado confirmado 'on'. Con
    'off' no se pulsa nada, y con 'on?' —que significa «encendida o en reposo
    con la red aún viva», sin poder distinguirlas— se manda la absoluta: puede
    que no apague, pero jamás va a encender una TV que ya estaba en reposo.
    """
    name = tv.get("name") or "la TV"
    fin = time.monotonic() + _LIMITE_APAGADO

    def _queda() -> float:
        return fin - time.monotonic()

    ip, _viva = await _o_agota(_tv_ip_actual(ctx, tv), _queda(),
                               ((tv.get("ip") or "").strip(), False))
    if not ip:
        return {"ok": False, "reply": f"No encuentro {name} en la red. ¿Está enchufada?"}
    tv = dict(tv, ip=ip)

    # '' = no ha dado tiempo a averiguarlo. Cuenta como «no lo sé», que es lo que
    # obliga a usar la tecla que no puede encender nada por error.
    antes = await _o_agota(_tv_estado(ip), _queda(), "")
    if antes == "off":
        _save_estado(ctx, tv, False)
        return {"ok": True, "state": "off", "reply": f"{name} ya estaba apagada."}

    a_ciegas = antes != "on"
    roku_path, samsung_key = _TECLA_APAGADO_SEGURA if a_ciegas else _TV_KEYMAP["off"]
    enviado = await _tv_key(ctx, tv, roku_path, samsung_key)
    if not enviado:
        return {"ok": False, "reply": _tv_fail(tv)}

    await asyncio.sleep(_ESPERA_APAGADO)
    # Sabiendo que estaba encendida se puede insistir hasta que conteste; a
    # ciegas no, porque no se sabe ni de qué se parte.
    if not a_ciegas and await _confirma_apagado(ip, _queda()):
        _save_estado(ctx, tv, False)
        return {"ok": True, "state": "off", "reply": f"{name} apagada."}
    despues = await _o_agota(_tv_estado(ip), _queda(), "")
    if despues == "off":
        _save_estado(ctx, tv, False)
        return {"ok": True, "state": "off", "reply": f"{name} apagada."}
    if a_ciegas:
        return {"ok": False, "state": None,
                "reply": f"No sé si {name} se ha apagado: este modelo no dice su estado. "
                         "Míralo."}
    if despues in ("on?", ""):
        return {"ok": True, "state": None,
                "reply": f"Orden enviada a {name}, pero ha dejado de responder. Míralo."}
    return {"ok": False, "state": None,
            "reply": f"{name} sigue encendida. Vuelve a pedírmelo."}


async def _tv_power_on(ctx, tv: dict) -> dict:
    """ENCENDER es encender, nunca un interruptor. Se mira primero si la TV está viva:

      * viva    -> orden de ENCENDER específica (KEY_POWERON / PowerOn), idempotente.
      * dormida -> SOLO Wake-on-LAN. Ninguna tecla: KEY_POWER es un toggle y volvería
                   a apagar la TV justo después de que el WoL la despierte.
    """
    name = tv.get("name") or "la TV"
    ip = tv.get("ip", "")
    mac = tv.get("mac") or await asyncio.to_thread(_mac_for_ip, ip)
    if mac and not tv.get("mac"):
        tv = dict(tv, mac=mac)
        _save_tv(ctx, dict(tv, is_tv=True))
    # La IP guardada caduca por DHCP: se re-resuelve desde la MAC antes de actuar.
    # `viva` sale de esa misma resolución: preguntarlo aparte era sondear dos veces.
    ip, viva = await _tv_ip_actual(ctx, dict(tv, ip=ip, mac=mac))
    tv = dict(tv, ip=ip)

    # Hay un estado intermedio que engaña: EN REPOSO PERO CON LA RED VIVA. La TV
    # contesta, así que parece encendida, pero está apagada — y KEY_POWERON no la
    # despierta de ahí (medido contra la UE32N4300). Con el reposo CONFIRMADO el
    # interruptor sí es seguro para encender: no puede apagar lo que ya está
    # apagado. Es la misma regla que al apagar, en el otro sentido.
    en_reposo = viva and await _samsung_mute_upnp(ip) == "1"

    async def _key():
        try:
            # KEY_POWERON es «enciende», no «cambia»: jamás apaga una TV encendida.
            samsung = "KEY_POWER" if en_reposo else "KEY_POWERON"
            return await asyncio.wait_for(
                _tv_key(ctx, tv, "keypress/PowerOn", samsung), timeout=4.5)
        except Exception:
            return False

    sent_wol, ok_key = False, False
    if viva:
        ok_key = await _key()
        if not ok_key and mac:      # no lo aceptó: probamos a despertarla por red
            sent_wol = await asyncio.to_thread(
                _wol_burst, mac, ip, ctx["settings"].get("wol_broadcast", ""))
    elif mac:
        # Dormida: solo Wake-on-LAN (la tecla la volvería a apagar).
        sent_wol = await asyncio.to_thread(
            _wol_burst, mac, ip, ctx["settings"].get("wol_broadcast", ""))
    else:
        ok_key = await _key()

    if ok_key:
        _save_estado(ctx, tv, True)
        return {"ok": True, "state": "on", "reply": f"Encendiendo {name}."}
    if sent_wol:
        _save_estado(ctx, tv, True)
    if sent_wol:
        return {"ok": True, "state": "on",
                "reply": f"Encendiendo {name} por Wake-on-LAN (paquete a su IP "
                                     "y a toda la red). Si en unos segundos no arranca, "
                                     "activa en la TV el «encendido por red» (WoL/WoWLAN) y "
                                     "que no esté en una regleta apagada."}
    if not mac:
        return {"ok": False, "reply": f"{name} no responde y no tengo su MAC para encenderla "
                                      "por red: enciéndela una vez con el mando, escanea la "
                                      "red (◎ Dispositivos) y a partir de ahí podré "
                                      "encendértela yo."}
    return {"ok": False, "reply": f"No he podido encender {name}: ni el Wake-on-LAN ni la "
                                  "orden directa han respondido. Revisa su MAC en ⚙."}


# Resultado de mandar una tecla a una TV. Es «la orden salió y no la rechazó»,
# NO «la TV hizo lo que le pedí»: para saber eso hay que leerle el estado después.
ENVIADO = "enviado"


# ---------------------------------------------------------------- Roku (ECP)
async def _roku(ip: str, path: str) -> str:
    """Manda una orden ECP a una Roku. Devuelve ENVIADO si la TV aceptó la
    petición y '' si no. ENVIADO no es «obedecido»: solo dice que la orden salió
    y la TV no la rechazó. Quien necesite saber el resultado tiene que mirarlo."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=2.5) as cli:
            r = await cli.post(f"http://{ip}:8060/{path}")
            return ENVIADO if r.status_code < 400 else ""
    except Exception:
        return ""


_ROKU_APPS = {"netflix": "12", "youtube": "837", "prime": "13", "prime video": "13",
              "disney": "291097", "disney+": "291097", "hbo": "61322", "hbo max": "61322",
              "spotify": "22297", "plex": "13535", "twitch": "227"}


# ---------------------------------------------------------------- Samsung Tizen
async def _samsung(ctx, ip: str, key: str, tvid: str = "") -> str:
    """Envía una tecla a una Samsung moderna (Tizen) por WebSocket. La primera vez la TV
    muestra un aviso para permitir el control; el token se guarda para no repetir. El
    token va POR TV (clave = su MAC/IP): con dos Samsung en casa, cada una tiene el suyo
    y no se pisan.

    Devuelve ENVIADO si la tecla salió por el socket autorizado, '' si no se pudo
    mandar. ENVIADO no es «obedecido»: Tizen acepta teclas que luego ignora (es
    justo lo que hace con KEY_POWEROFF). El resultado hay que comprobarlo aparte."""
    try:
        import base64
        import json
        import ssl
        import websockets
    except Exception:
        return ""
    _id = re.sub(r"[^0-9a-z]", "", (tvid or ip).lower())
    tok_key = f"samsung_tv_token_{_id}" if _id else "samsung_tv_token"
    token = ctx["settings"].secret(tok_key)
    name_b64 = base64.b64encode(b"nexus").decode()
    payload = json.dumps({"method": "ms.remote.control", "params": {
        "Cmd": "Click", "DataOfCmd": key, "Option": "false",
        "TypeOfRemote": "SendRemoteKey"}})
    sslctx = ssl.create_default_context()
    sslctx.check_hostname = False
    sslctx.verify_mode = ssl.CERT_NONE
    loop = asyncio.get_running_loop()
    # Probamos Tizen MODERNO (wss:8002) y, si falla, Tizen ANTIGUO (ws:8001).
    for port, sc in ((8002, sslctx), (8001, None)):
        scheme = "wss" if sc else "ws"
        url = f"{scheme}://{ip}:{port}/api/v2/channels/samsung.remote.control?name={name_b64}"
        if token and sc:
            url += f"&token={token}"
        try:
            kw = {"open_timeout": 3}
            if sc:
                kw["ssl"] = sc
            async with websockets.connect(url, **kw) as ws:
                # Esperamos la AUTORIZACION: la primera vez hay que aceptar el aviso con
                # el mando (hasta 30 s); con el token guardado es inmediato. La tecla solo
                # surte efecto tras «ms.channel.connect».
                deadline = loop.time() + (30 if not token else 6)
                while loop.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=max(0.5, deadline - loop.time()))
                    except Exception:
                        break
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue
                    tok = (data.get("data") or {}).get("token")
                    if tok and str(tok) != (token or ""):
                        token = str(tok)
                        ctx["settings"].set_secret(tok_key, token)
                    if data.get("event") == "ms.channel.connect":
                        await ws.send(payload)
                        await asyncio.sleep(0.3)
                        return ENVIADO
        except Exception:
            continue
    return ""


async def _tv_key(ctx, tv: dict, roku_path: str, samsung_key: str) -> str:
    """Manda una tecla a la TV. Devuelve ENVIADO o '' — nunca «obedecido»."""
    brand = (tv.get("brand") or "").lower()
    ip = tv.get("ip", "")
    if not ip:
        return ""
    tvid = tv.get("mac") or ip or ""     # token de Samsung POR TV (no global)
    if brand == "roku":
        return await _roku(ip, roku_path)
    if brand == "samsung":
        return await _samsung(ctx, ip, samsung_key, tvid)
    # marca desconocida: probamos Roku (HTTP) y si no, Samsung
    return await _roku(ip, roku_path) or await _samsung(ctx, ip, samsung_key, tvid)


# ---------------------------------------------------------------- Home Assistant
def _ha_config(ctx) -> tuple[str, str]:
    """(url, token) de Home Assistant tal y como están configurados. Sirve para
    distinguir «no está configurado» de «está configurado pero no responde»."""
    return ((ctx["settings"].get("homeassistant_url", "") or "").rstrip("/"),
            ctx["settings"].secret("homeassistant_token") or "")


async def _ha_states(ctx) -> list[dict]:
    import httpx
    url, token = _ha_config(ctx)
    if not url or not token:
        return []
    try:
        async with httpx.AsyncClient(timeout=8) as cli:
            r = await cli.get(f"{url}/api/states",
                              headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return r.json()
    except Exception:
        return []


async def _ha_call(ctx, domain: str, service: str, entity_id: str) -> bool:
    import httpx
    url, token = _ha_config(ctx)
    if not url or not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as cli:
            r = await cli.post(f"{url}/api/services/{domain}/{service}",
                               headers={"Authorization": f"Bearer {token}"},
                               json={"entity_id": entity_id})
            return r.status_code < 400
    except Exception:
        return False


_STOP = {"el", "la", "los", "las", "de", "del", "un", "una", "en", "y", "por",
         "favor", "enciende", "apaga", "apágame", "pon", "sube", "baja", "activa",
         "desactiva", "cierra", "abre", "arranca", "para", "me", "the"}


def _match_entity(phrase: str, states: list[dict]) -> dict | None:
    """Empareja la orden con la entidad de HA cuyo nombre amigable coincide más."""
    words = [w for w in re.findall(r"[a-záéíóúñ]+", phrase.lower()) if w not in _STOP and len(w) > 2]
    best, best_score = None, 0
    for s in states:
        dom = s.get("entity_id", "").split(".")[0]
        if dom not in ("light", "switch", "fan", "cover", "climate", "media_player",
                       "input_boolean", "scene", "script"):
            continue
        name = (s.get("attributes", {}).get("friendly_name", "")
                + " " + s.get("entity_id", "")).lower()
        score = sum(1 for w in words if w in name)
        if score > best_score:
            best, best_score = s, score
    return best if best_score > 0 else None


def _ip_key(ip: str) -> tuple:
    try:
        return tuple(int(x) for x in ip.split("."))
    except Exception:
        return (999, 999, 999, 999)


def _label_device(dev: dict) -> str:
    """Elige la mejor etiqueta de TIPO para un aparato a partir de todas las pistas."""
    # 1) servicios mDNS (los más fiables para el tipo)
    if dev.get("services"):
        return sorted(dev["services"])[0]
    # 2) SSDP
    if dev.get("ssdp_type") and dev["ssdp_type"] != "Dispositivo UPnP":
        return dev["ssdp_type"]
    # 3) puerto sondeado
    if dev.get("port_type"):
        return dev["port_type"]
    # 4) fabricante (da mucha pista: Apple/Espressif/Tuya…)
    if dev.get("vendor"):
        return dev["vendor"]
    if dev.get("ssdp_type"):
        return dev["ssdp_type"]
    return "Dispositivo de red"


def _primary_ip() -> str:
    """IP principal de ESTE PC (la de salida a internet)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return ""


def _local_ips() -> set:
    """TODAS las IPs de las interfaces de ESTE PC (incluye adaptadores virtuales de
    Docker/VMware/VirtualBox/Hyper-V/WSL) → para no listarlos como PCs duplicados."""
    ips = set()
    try:
        import psutil
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if getattr(a, "family", None) == socket.AF_INET and a.address:
                    ips.add(a.address)
    except Exception:
        pass
    try:
        ips.add(socket.gethostbyname(socket.gethostname()))
    except Exception:
        pass
    return ips


def _is_junk_ip(ip: str) -> bool:
    """IPs que NO son un dispositivo: broadcast (.255) y multicast (224-239.x.x.x)."""
    if not ip or ip == "255.255.255.255" or ip.endswith(".255"):
        return True
    try:
        if 224 <= int(ip.split(".")[0]) <= 239:
            return True
    except Exception:
        pass
    return False


def _upnp_name_from_xml(xml: str) -> dict:
    """Extrae el friendlyName (nombre que difunde el aparato) y el modelo de la
    descripción UPnP. Pura (sin red) para poder probarla. Tolera espacios de nombres."""
    out: dict = {}
    m = re.search(r"<friendlyName>\s*(.*?)\s*</friendlyName>", xml or "", re.S | re.I)
    if m:
        out["friendly"] = re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"<modelName>\s*(.*?)\s*</modelName>", xml or "", re.S | re.I)
    if m:
        out["model"] = re.sub(r"\s+", " ", m.group(1)).strip()
    return out


async def _upnp_friendly(ip: str, location: str, sem: asyncio.Semaphore) -> dict:
    """Baja la descripción UPnP (el XML de la cabecera LOCATION del SSDP) y saca el
    friendlyName real de TVs/altavoces: el nombre que el aparato difunde, en vez de un
    tipo genérico. Tope de tiempo corto y en paralelo para no meter lag."""
    if not location:
        return {}
    try:
        import httpx
    except Exception:
        return {}
    async with sem:
        try:
            async with httpx.AsyncClient(timeout=2.0) as cli:
                r = await cli.get(location)
                return _upnp_name_from_xml(r.text)
        except Exception:
            return {}


async def _samsung_tv_name(ip: str, sem: asyncio.Semaphore) -> str:
    """Nombre REAL de una Samsung moderna vía su API REST: GET http://ip:8001/api/v2/
    -> device.name (el nombre que le pusiste en la propia TV). Más fiable que el SSDP:
    usa las mismas puertas por las que ya la controlas. Solo con la TV encendida."""
    try:
        import httpx
    except Exception:
        return ""
    async with sem:
        for scheme, port in (("http", 8001), ("https", 8002)):
            try:
                async with httpx.AsyncClient(timeout=2.0, verify=False) as cli:
                    r = await cli.get(f"{scheme}://{ip}:{port}/api/v2/")
                    data = r.json()
                nm = ((data.get("device") or {}).get("name") or "").strip()
                nm = re.sub(r"^\[TV\]\s*", "", nm).strip()   # quita el prefijo «[TV] »
                if nm:
                    return nm
            except Exception:
                continue
    return ""


async def _roku_name(ip: str, sem: asyncio.Semaphore) -> str:
    """Nombre real de una Roku/TCL Roku TV: GET http://ip:8060/query/device-info ->
    <user-device-name> o <friendly-device-name>."""
    try:
        import httpx
    except Exception:
        return ""
    async with sem:
        try:
            async with httpx.AsyncClient(timeout=2.0) as cli:
                xml = (await cli.get(f"http://{ip}:8060/query/device-info")).text
        except Exception:
            return ""
    for tag in ("user-device-name", "friendly-device-name", "friendly-model-name"):
        m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", xml, re.S | re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


async def _cast_name(ip: str, sem: asyncio.Semaphore) -> str:
    """Nombre real de un Chromecast / Google / Android TV con Cast:
    GET http://ip:8008/setup/eureka_info -> name."""
    try:
        import httpx
    except Exception:
        return ""
    async with sem:
        try:
            async with httpx.AsyncClient(timeout=2.0) as cli:
                d = (await cli.get(f"http://{ip}:8008/setup/eureka_info?options=detail")).json()
        except Exception:
            return ""
    return (d.get("name") or "").strip()


async def _tv_probe_name(ip: str, sem: asyncio.Semaphore) -> str:
    """AGNÓSTICO: pregunta el nombre real por los endpoints estándar de las TVs más
    comunes a la vez (Tizen/Samsung 8001, Roku 8060, Chromecast/Google 8008) y devuelve
    el primero que conteste. No decide por marca: prueba capacidades y usa lo que responda."""
    res = await asyncio.gather(_samsung_tv_name(ip, sem), _roku_name(ip, sem),
                               _cast_name(ip, sem), return_exceptions=True)
    for nm in res:
        if isinstance(nm, str) and nm.strip():
            return nm.strip()
    return ""


async def _discover_all(ctx) -> dict:
    """Rastreo ACTIVO completo de la red local. Devuelve devices + resumen."""
    # 1) PING SWEEP (rellena la tabla ARP con TODO lo que hay) — en paralelo con
    #    los descubrimientos por multicast, que no dependen del sweep.
    live, ssdp, mdns = await asyncio.gather(
        _ping_sweep(6.0),
        asyncio.to_thread(_ssdp_discover, 3.0),
        asyncio.to_thread(_mdns_discover, 3.0),
    )
    arp = await asyncio.to_thread(_arp_table)          # ya poblada por el sweep
    by_ip = {d["ip"]: d.get("mac", "") for d in arp}

    # universo de IPs de todas las fuentes
    ips = set(by_ip) | set(ssdp) | set(mdns) | set(live)
    ips.discard("")
    # LIMPIEZA: fuera broadcast/multicast (no son aparatos) y fuera los ADAPTADORES
    # VIRTUALES de este mismo PC (Docker/VMware/VirtualBox/Hyper-V/WSL), que si no
    # salen duplicados como aparatos distintos. Dejamos solo la IP real.
    primary = _primary_ip()
    mine = _local_ips() if primary else set()
    ips = {ip for ip in ips
           if not _is_junk_ip(ip) and not (primary and ip in mine and ip != primary)}

    devices: dict = {}
    for ip in ips:
        mac = by_ip.get(ip, "")
        info = ssdp.get(ip, {})
        md = mdns.get(ip, {})
        devices[ip] = {
            "ip": ip, "mac": mac, "vendor": _mac_vendor(mac),
            "ssdp_type": _guess_type(info.get("server", ""), info.get("st", "")) if info else "",
            "names": set(md.get("names", set())), "services": set(md.get("services", set())),
            "live": ip in live, "port_type": "",
        }

    # 2) DNS inverso + sondeo de puertos + friendlyName UPnP, en paralelo para todos
    sem_p = asyncio.Semaphore(64)
    sem_d = asyncio.Semaphore(48)
    sem_up = asyncio.Semaphore(24)
    ip_list = list(devices)
    rdns, ptypes, ups = await asyncio.gather(
        asyncio.gather(*[_reverse_dns(ip, sem_d) for ip in ip_list]),
        asyncio.gather(*[_probe_ports(ip, sem_p) for ip in ip_list]),
        asyncio.gather(*[_upnp_friendly(ip, ssdp.get(ip, {}).get("location", ""), sem_up)
                         for ip in ip_list], return_exceptions=True),
    )
    # 3) NetBIOS (nombres de PCs Windows) como PASO APARTE y con TOPE DE TIEMPO DURO:
    #    si tarda o falla, seguimos SIN el -> nunca puede romper/colgar el escaneo.
    nbns = [""] * len(ip_list)
    try:
        sem_nb = asyncio.Semaphore(24)
        got = await asyncio.wait_for(
            asyncio.gather(*[_netbios_lookup(ip, sem_nb) for ip in ip_list],
                           return_exceptions=True),
            timeout=3.0)
        nbns = [n if isinstance(n, str) else "" for n in got]
    except Exception:
        nbns = [""] * len(ip_list)
    for ip, host, ptype, nb, up in zip(ip_list, rdns, ptypes, nbns, ups):
        if host:
            devices[ip]["names"].add(host)
        if nb:
            devices[ip]["names"].add(nb)
            devices[ip]["netbios"] = nb
        devices[ip]["port_type"] = ptype
        if isinstance(up, dict) and up.get("friendly"):
            devices[ip]["friendly"] = up["friendly"]
            devices[ip]["names"].add(up["friendly"])
        if isinstance(up, dict) and up.get("model"):
            devices[ip]["model"] = up["model"]

    n_ha = len(await _ha_states(ctx))
    return {"devices": devices, "live": live, "n_ha": n_ha,
            "n_upnp": len(ssdp), "n_mdns": len(mdns)}


# ---------------------------------------------------------------- handler
def _norm_txt(s: str) -> str:
    """minúsculas sin acentos, para casar nombres de dispositivo con la orden."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# canal dicho con letra: «pon el canal cinco»
_NUM_PALABRA = {"uno": "1", "dos": "2", "tres": "3", "cuatro": "4", "cinco": "5",
                "seis": "6", "siete": "7", "ocho": "8", "nueve": "9", "diez": "10"}

# palabras de estancia/tipo que por sí solas NO identifican un aparato concreto
_ROOM_WORDS = {"habitacion", "salon", "cocina", "cuarto", "bano", "pasillo", "entrada",
               "dormitorio", "comedor", "garaje", "jardin", "terraza", "oficina",
               "despacho", "tv", "tele", "television", "smart", "casa", "sala"}


def _resolve_named_device(ctx, text: str):
    """¿La orden NOMBRA un dispositivo TUYO? (p.ej. una TV llamada «Habitación
    Norte»). Busca en my_devices + known_devices el aparato cuyo NOMBRE aparece
    en la frase — aunque el nombre lleve palabras de estancia («habitación») que
    enrutarían a Home Assistant. Devuelve un dict de control o None. Gana el nombre
    MÁS ESPECÍFICO (más largo) que case."""
    tn = _norm_txt(text)
    saved = []
    for d in (ctx["settings"].get("my_devices", []) or []):
        saved.append(d)
    for d in _known(ctx):
        saved.append(d)
    best, best_len = None, 0
    for d in saved:
        name = (d.get("name") or "").strip()
        if not name or _is_generic_name(name, d.get("brand", "")):
            continue
        nn = _norm_txt(name)
        # tokens DISTINTIVOS del nombre (no palabras de estancia): sin al menos uno,
        # el nombre no permite desambiguar por voz (p.ej. «Salón» a secas) → se ignora
        # para no robarle una orden a Home Assistant («enciende la luz del salón»).
        toks = [w for w in re.findall(r"[a-z0-9]+", nn) if len(w) >= 4 and w not in _ROOM_WORDS]
        if not toks:
            continue
        matched = (nn in tn) or any(re.search(rf"\b{re.escape(w)}\b", tn) for w in toks)
        if matched and len(nn) > best_len:
            best, best_len = d, len(nn)
    return best


def _is_tv_device(d: dict) -> bool:
    """¿Es una TV? Manda lo que dice la CONFIGURACIÓN, por este orden:

      1. el flag explícito `is_tv` (si está, se respeta tal cual, también en False),
      2. el tipo declarado (`kind`/`type`),
      3. y solo si no hay nada de eso, se adivina por la marca o el nombre.

    Adivinar por el nombre es el último recurso: una TV a la que le pusiste el
    nombre de su cuarto no lleva «tv» dentro y se quedaba fuera del apagado."""
    if "is_tv" in d:
        return bool(d.get("is_tv"))
    kind = str(d.get("kind") or d.get("type") or "").strip().lower()
    if kind:
        return "tv" in kind or "tele" in kind
    blob = (str(d.get("brand", "")) + " " + str(d.get("name", ""))).lower()
    return "tv" in blob or "tele" in blob


def _wants_on(t: str) -> bool:
    return (bool(re.search(r"\b(enciende|enci[eé]nde\w*|prende|activa|arranca|abre|"
                           r"pon\s+en\s+marcha|dale)\b", t))
            and not re.search(r"\b(apaga|ap[aá]ga\w*|desactiva|desconecta|cierra|para|quita)\b", t))


async def _power_named_device(ctx, d: dict, on: bool) -> dict:
    """Enciende/apaga el dispositivo TUYO ya resuelto por nombre (TV o entidad HA)."""
    name = d.get("name") or "el dispositivo"
    if _is_tv_device(d):
        tv = {"name": name, "ip": d.get("ip", ""), "brand": (d.get("brand") or "").lower(),
              "mac": d.get("mac", ""), "is_tv": True}
        if on:
            return await _tv_power_on(ctx, tv)
        return await _tv_apagar(ctx, tv)
    # entidad de Home Assistant guardada (my_devices con entity_id)
    eid = d.get("entity_id", "")
    if eid:
        dom = eid.split(".")[0]
        if dom == "cover":
            ok = await _ha_call(ctx, "cover", "open_cover" if on else "close_cover", eid)
        else:
            ok = await _ha_call(ctx, "homeassistant", "turn_on" if on else "turn_off", eid)
        verbo = "Encendido" if on else "Apagado"
        return {"reply": f"{verbo}: {name}." if ok else f"No pude actuar sobre «{name}»."}
    return {"reply": f"Tengo «{name}» guardado pero sin forma de controlarlo (ni IP/MAC de TV "
                     "ni entidad de Home Assistant). Reconéctalo en Dispositivos."}


async def handle(intent: str, text: str, match, ctx) -> dict:
    t = text.lower()

    # RESOLUCIÓN POR NOMBRE, antes que nada en las órdenes de encender/apagar: si la
    # frase nombra un aparato tuyo, se controla ESE aunque su nombre lleve palabras de
    # estancia («habitación») que enrutarían la orden a Home Assistant.
    if intent in ("casa", "tv_on", "tv_off"):
        d = _resolve_named_device(ctx, text)
        if d:
            return await _power_named_device(ctx, d, _wants_on(t))

    if intent == "descubrir":
        scan = await _discover_all(ctx)
        devices = scan["devices"]
        if not devices:
            return {"reply": "He barrido la red y no ha contestado nadie — raro, salvo que la "
                             "red bloquee el descubrimiento (multicast/ICMP). Comprueba que "
                             "este PC está en tu WiFi de casa y repite «escanea la red»; si "
                             "sigue en blanco, añade tus aparatos a mano en ⚙ (sección CASA) "
                             "con nombre, IP y MAC, y con eso me basta para controlarlos."}
        # nombres conocidos (⚙) para etiquetar bonito lo que ya te sabes
        known_by_ip = {d.get("ip"): d for d in _known(ctx) if d.get("ip")}
        known_by_mac = {(d.get("mac") or "").upper(): d for d in _known(ctx) if d.get("mac")}

        lines = []
        for ip in sorted(devices, key=_ip_key):
            dev = devices[ip]
            kn = known_by_ip.get(ip) or known_by_mac.get((dev["mac"] or "").upper())
            # nombre a mostrar: el que le pusiste tú > mDNS/DNS > tipo
            name = _pick_name(dev, kn, _label_device(dev))
            label = _label_device(dev)
            head = name or label
            detail = []
            if name and label and label.lower() not in name.lower():
                detail.append(label)
            if dev["vendor"] and dev["vendor"] not in head and dev["vendor"] not in detail:
                detail.append(dev["vendor"])
            extra_svc = [s for s in sorted(dev["services"]) if s != label]
            detail += extra_svc[:2]
            tail = f" — {', '.join(detail)}" if detail else ""
            mac = f"  ·  {dev['mac']}" if dev["mac"] else ""
            lines.append(f"• {ip}  —  {head}{tail}{mac}")

        n = len(devices)
        smart = sum(1 for d in devices.values()
                    if d["services"] or (d["ssdp_type"] and d["ssdp_type"] != "Dispositivo UPnP")
                    or d["port_type"] or d["vendor"])
        head = (f"He rastreado tu red y encontré {n} dispositivo"
                f"{'s' if n != 1 else ''} ({smart} identificado"
                f"{'s' if smart != 1 else ''}):")
        extra = ""
        if scan["n_ha"]:
            extra = (f"\n\nHome Assistant conectado: {scan['n_ha']} entidades controlables "
                     "(luces, enchufes, persianas…). Di «enciende la luz del salón» y me encargo.")
        else:
            extra = ("\n\nLas TVs las controlo directamente («enciende la tele»); para luces y "
                     "enchufes, conecta Home Assistant en ⚙ (sección CASA).")
        return {"reply": head + "\n" + "\n".join(lines) + extra}

    if intent == "wol":
        # Orden de preferencia: el equipo NOMBRADO en la frase > la MAC del PC
        # configurada en ⚙ > un aparato guardado que NO sea una TV. Sin este
        # último filtro se mandaba el paquete a la primera MAC de known_devices,
        # que casi siempre es la TV que guarda el escáner.
        equipo = _resolve_named_device(ctx, text)
        if equipo and _is_tv_device(equipo):
            equipo = None
        mac = (equipo or {}).get("mac") or ctx["settings"].get("wol_mac", "")
        if not mac:
            for d in _known(ctx):
                if d.get("mac") and not _is_tv_device(d):
                    equipo, mac = d, d["mac"]
                    break
        if not mac:
            return {"reply": "Me falta la MAC del equipo para mandarle el paquete mágico. "
                             "Apúntala en ⚙ (MAC del PC / Wake-on-LAN) o añade el equipo a tus "
                             "dispositivos con su MAC; a partir de ahí, «enciende el pc» y listo."}
        nombre = (equipo or {}).get("name") or "el equipo"
        ok = await asyncio.to_thread(wake_on_lan, mac,
                                     ctx["settings"].get("wol_broadcast", "255.255.255.255"))
        return {"reply": f"Paquete de encendido enviado a {nombre} ({mac}). Dale unos segundos "
                         "para arrancar; recuerda que el equipo debe tener el Wake-on-LAN "
                         "activado en la BIOS/adaptador." if ok
                else f"No he podido enviar el Wake-on-LAN a {mac}: revisa que la MAC en ⚙ tenga "
                     "el formato AA:BB:CC:DD:EE:FF y que estés en la misma red que el equipo."}

    if intent in ("tv_on", "tv_off", "tv_mute", "tv_volume", "tv_channel", "tv_app"):
        tv, ambiguas = await _elegir_tv(ctx, text)
        if ambiguas:
            # Se apunta la orden para que la respuesta («la de arriba») tenga a
            # qué pegarse: suelta no significa nada.
            try:
                from backend.core import context as _ctxt
                _ctxt.note_pregunta(text, ctx.get("channel", "pc"))
            except Exception:                                  # noqa: BLE001
                pass
            nombres = " o ".join(d.get("name") or "sin nombre" for d in ambiguas)
            return {"reply": f"¿Cuál? {nombres}."}
        if not tv:
            return {"reply": "No veo ninguna TV en la red ahora mismo. Enciéndela una vez con "
                             "el mando y repítemelo (así aprendo su IP y su MAC), o añádela en "
                             "⚙ (sección CASA) con IP, marca (samsung/roku/lg) y MAC — con la "
                             "MAC guardada te la enciendo hasta estando apagada, por Wake-on-LAN."}
        name = tv.get("name", "la TV")

        if intent == "tv_on":
            return await _tv_power_on(ctx, tv)

        if intent == "tv_off":
            return await _tv_apagar(ctx, tv)

        if intent == "tv_mute":
            ok = await _tv_key(ctx, tv, "keypress/VolumeMute", "KEY_MUTE")
            return {"reply": f"{name} en silencio." if ok else _tv_fail(tv)}

        if intent == "tv_volume":
            d = _norm_txt(match.group("dir") or match.group("dir2") or "")
            up = d.startswith("sub") or d == "mas"
            ok = await _tv_key(ctx, tv, "keypress/Volume" + ("Up" if up else "Down"),
                               "KEY_VOLUP" if up else "KEY_VOLDOWN")
            return {"reply": (f"Subiendo" if up else "Bajando") + f" el volumen de {name}." if ok
                    else _tv_fail(tv)}

        if intent == "tv_channel":
            n = match.group("n") or _NUM_PALABRA.get(_norm_txt(match.group("nw") or ""), "")
            d = (match.group("dir2") or match.group("dir3") or "").lower()
            if n:
                ok = True
                for digit in n:
                    ok = await _tv_key(ctx, tv, f"keypress/Lit_{digit}", f"KEY_{digit}") and ok
                await _tv_key(ctx, tv, "keypress/Select", "KEY_ENTER")
                return {"reply": f"Cambiando {name} al canal {n}." if ok else _tv_fail(tv)}
            up = d == "siguiente"
            ok = await _tv_key(ctx, tv, "keypress/ChannelUp" if up else "keypress/ChannelDown",
                               "KEY_CHUP" if up else "KEY_CHDOWN")
            return {"reply": f"Canal {'siguiente' if up else 'anterior'} en {name}." if ok else _tv_fail(tv)}

        if intent == "tv_app":
            app = (match.group("app") or match.group("app2") or "").lower().strip()
            brand = (tv.get("brand") or "").lower()
            if brand == "roku":
                appid = _ROKU_APPS.get(app)
                ok = await _roku(tv["ip"], f"launch/{appid}") if appid else False
                return {"reply": f"Abriendo {app} en {name}." if ok
                        else f"No tengo el id de {app} para Roku."}
            # Samsung: abrir apps requiere ids por TV; de momento avisamos con honestidad
            return {"reply": f"Abrir «{app}» directo solo lo tengo fino en TVs Roku. En Samsung "
                             f"puedo encender, apagar, volumen y canales; para apps conéctala a "
                             f"Home Assistant y te la manejo entera."}

    if intent == "casa":
        states = await _ha_states(ctx)
        if not states:
            url, token = _ha_config(ctx)
            if not url or not token:
                return {"reply": SETUP_HA}
            return {"reply": f"Tengo Home Assistant configurado en {url}, pero no me ha devuelto "
                             "ninguna entidad: o no responde, o el token ya no vale. Compruébalo "
                             "en ⚙ (sección CASA) — ahí puedes probar la URL y el token en vivo "
                             "antes de guardarlos."}
        ent = _match_entity(text, states)
        if not ent:
            return {"reply": "En Home Assistant no veo nada que se llame así. Dímelo con el "
                             "nombre exacto que tiene en HA (p.ej. «enciende la luz del salón») "
                             "o di «escanea la red» y te enseño todo lo que puedo controlar."}
        on = bool(re.search(r"\b(enci[eé]nde\w*|pr[eé]nde\w*|activa|abre|[aá]bre\w*|arranca|"
                            r"s[uú]be\w*|sube|pon\w*)\b", t)) and \
            not re.search(r"\b(apaga|ap[aá]ga\w*|desactiva|desconecta|cierra|ci[eé]rra\w*|"
                          r"baja|b[aá]ja\w*|para)\b", t)
        dom = ent["entity_id"].split(".")[0]
        fname = ent.get("attributes", {}).get("friendly_name", ent["entity_id"])
        service = "turn_on" if on else "turn_off"
        # cover (persianas): open/close; sino, homeassistant.turn_on/off vale para todo
        if dom == "cover":
            dom, service = "cover", ("open_cover" if on else "close_cover")
            ok = await _ha_call(ctx, dom, service, ent["entity_id"])
        else:
            ok = await _ha_call(ctx, "homeassistant", service, ent["entity_id"])
        verbo = "Encendido" if on else "Apagado"
        if dom == "cover":
            verbo = "Abriendo" if on else "Cerrando"
        return {"reply": f"{verbo}: {fname}." if ok
                else f"No pude actuar sobre «{fname}»: Home Assistant no responde. Comprueba "
                     "la URL y el token en ⚙ (sección CASA) y vuelve a pedírmelo."}

    return {"reply": "Esa orden de casa no la tengo mapeada. Prueba «escanea la red», "
                     "«enciende la tele» o «apaga la luz del salón»."}


def _tv_fail(tv: dict) -> str:
    return (f"{tv.get('name', 'La TV')} no acepta la orden. Si sale un aviso de permiso "
            "en su pantalla, acéptalo.")


# ============================================================================
#  API para el BUSCADOR VISUAL (HUD + móvil): lista tipo «buscar Bluetooth» y
#  control al pinchar. Reutiliza TODA la lógica de arriba (escaneo + mando TV/HA).
# ============================================================================
def _dev_is_tv(dev: dict) -> bool:
    t = (dev.get("ssdp_type", "") + " " + dev.get("port_type", "")
         + " " + " ".join(dev.get("services", []))).lower()
    return "tv" in t


def _dev_brand(dev: dict) -> str:
    blob = (dev.get("ssdp_type", "") + " " + dev.get("port_type", "") + " "
            + " ".join(dev.get("services", [])) + " " + dev.get("vendor", "")).lower()
    if "roku" in blob:
        return "roku"
    if "samsung" in blob:
        return "samsung"
    if "lg" in blob or "webos" in blob:
        return "lg"
    if "sony" in blob or "bravia" in blob:
        return "sony"
    return "generic"


def _dev_icon(dev: dict, kind: str, brand: str) -> str:
    blob = (dev.get("ssdp_type", "") + " " + dev.get("port_type", "") + " "
            + " ".join(dev.get("services", [])) + " " + dev.get("vendor", "")).lower()
    if kind == "tv" or "chromecast" in blob or "fire tv" in blob or "android tv" in blob:
        return "📺"
    if "airplay" in blob or "sonos" in blob or "altavoz" in blob or "spotify" in blob:
        return "🔊"
    if "impresora" in blob or "print" in blob:
        return "🖨️"
    if "router" in blob:
        return "📶"
    if "iphone" in blob or "ipad" in blob or "apple" in blob or "android" in blob:
        return "📱"
    if "plex" in blob:
        return "🎬"
    if "home assistant" in blob:
        return "🏠"
    if "cámara" in blob or "camera" in blob or "rtsp" in blob:
        return "📷"
    if "nas" in blob:
        return "🗄️"
    if "raspberry" in blob:
        return "🍓"
    if "espressif" in blob or "tuya" in blob or "iot" in blob:
        return "🔌"
    if "ssh" in blob or "smb" in blob or "windows" in blob or "linux" in blob or "pc" in blob:
        return "🖥️"
    return "📟"


_HA_LABEL = {"light": "Luz", "switch": "Enchufe", "fan": "Ventilador",
             "cover": "Persiana", "climate": "Clima", "media_player": "Reproductor",
             "input_boolean": "Interruptor", "scene": "Escena", "script": "Script"}
_HA_ICON = {"light": "💡", "switch": "🔌", "fan": "🌀", "cover": "🪟", "climate": "🌡️",
            "media_player": "🎵", "input_boolean": "🎚️", "scene": "🎬", "script": "📜"}


async def _ha_entities(ctx) -> list:
    """Entidades de Home Assistant como 'dispositivos' controlables (luces, enchufes…)."""
    out = []
    for s in await _ha_states(ctx):
        eid = s.get("entity_id", "")
        dom = eid.split(".")[0]
        if dom not in _HA_LABEL:
            continue
        name = s.get("attributes", {}).get("friendly_name", eid)
        state = s.get("state", "")
        out.append({"ip": "", "mac": "", "vendor": "Home Assistant", "name": name,
                    "type": _HA_LABEL[dom], "kind": "ha", "brand": "ha",
                    "controllable": True, "entity_id": eid, "domain": dom,
                    "state": state, "on": state == "on", "services": [],
                    "live": True, "icon": _HA_ICON.get(dom, "🏠")})
    return out


_GENERIC_NAMES = {"", "tv", "la tv", "tv samsung", "tv roku", "tv lg", "tv sony",
                  "samsung", "roku", "lg", "sony", "smart tv", "televisor", "television",
                  "televisión", "dispositivo guardado", "dispositivo de red"}


def _is_generic_name(name: str, brand: str = "") -> bool:
    """¿Es un nombre GENÉRICO (un tipo/marca, no un nombre propio)? p.ej. «TV Samsung».
    Sirve para NO dejar que un nombre auto-guardado tape el nombre REAL que difunde la TV."""
    n = (name or "").strip().lower()
    b = (brand or "").strip().lower()
    if n in _GENERIC_NAMES:
        return True
    if b and (n == b or n == f"tv {b}"):
        return True
    return False


def _pick_name(dev: dict, kn, label: str) -> str:
    """Nombre a mostrar, por orden: el nombre PROPIO puesto en ⚙ > friendlyName UPnP (el
    que difunde el aparato) > NetBIOS > mDNS/DNS > un nombre auto-guardado genérico >
    etiqueta por tipo. Un nombre genérico guardado («TV Samsung») nunca tapa al real."""
    if kn and kn.get("name") and not _is_generic_name(kn["name"], kn.get("brand", "")):
        return kn["name"]
    if dev.get("friendly"):
        return dev["friendly"]
    if dev.get("netbios"):
        return dev["netbios"]
    nombres = [n for n in (dev.get("names") or set()) if n]
    if nombres:
        return sorted(nombres, key=len)[-1]
    if kn and kn.get("name"):
        return kn["name"]
    return label


async def scan_api(ctx) -> dict:
    """Rastreo de red serializado para el buscador visual (HUD/móvil) + entidades HA."""
    scan = await _discover_all(ctx)
    devices = scan["devices"]
    known = _known(ctx)
    known_by_ip = {d.get("ip"): d for d in known if d.get("ip")}
    known_by_mac = {(d.get("mac") or "").upper(): d for d in known if d.get("mac")}
    learned = []          # (ip, friendlyName) aprendidos EN VIVO en este escaneo
    out = []
    for ip in sorted(devices, key=_ip_key):
        dev = devices[ip]
        dev_svc = sorted(dev["services"])
        kn = known_by_ip.get(ip) or known_by_mac.get((dev["mac"] or "").upper())
        label = _label_device(dev)
        name = _pick_name(dev, kn, label)
        # Si el aparato difunde su nombre real y lo guardado es genérico o vacío, se
        # aprende para que perdure aunque luego esté apagado. Nunca pisa un nombre
        # propio puesto en ⚙.
        if dev.get("friendly") and kn and _is_generic_name(kn.get("name", ""), kn.get("brand", "")) \
                and (kn.get("name") or "") != dev["friendly"]:
            kn["name"] = dev["friendly"]
            learned.append((ip, dev["friendly"]))
        brand = ((kn.get("brand") if kn else "") or _dev_brand(dev)).lower()
        tv_ish = _dev_is_tv(dev) or brand in ("roku", "samsung", "lg", "sony")
        kind = "tv" if tv_ish else "other"
        controllable = kind == "tv"          # cualquier TV se puede intentar conectar (agnóstico)
        out.append({"ip": ip, "mac": dev["mac"], "vendor": dev["vendor"], "name": name,
                    "type": label, "kind": kind, "brand": brand,
                    "controllable": controllable, "connected": bool(kn and kn.get("paired")),
                    "services": dev_svc,
                    "live": dev["live"], "icon": _dev_icon(dev, kind, brand)})
    # GUARDADOS que ahora no responden (p.ej. la TV APAGADA): se listan igual,
    # marcados como apagados — con MAC la TV sigue siendo controlable (⏻ = WoL).
    seen_ips = {d.get("ip") for d in out if d.get("ip")}
    seen_macs = {(d.get("mac") or "").lower() for d in out if d.get("mac")}
    for kd in _known(ctx):
        k_ip, k_mac = kd.get("ip", ""), (kd.get("mac") or "")
        if not (k_ip or k_mac):
            continue
        if (k_ip and k_ip in seen_ips) or (k_mac and k_mac.lower() in seen_macs):
            continue
        blob = (str(kd.get("brand", "")) + " " + str(kd.get("name", ""))).lower()
        k_tv = bool(kd.get("is_tv")) or "tv" in blob
        k_brand = (kd.get("brand") or ("generic" if k_tv else "")).lower()
        out.append({"ip": k_ip, "mac": k_mac, "vendor": kd.get("brand", ""),
                    "name": kd.get("name") or ("TV" if k_tv else "Dispositivo guardado"),
                    "type": "Smart TV · apagada" if k_tv else "guardado · apagado",
                    "kind": "tv" if k_tv else "other", "brand": k_brand,
                    "controllable": k_tv, "connected": bool(kd.get("paired")),
                    "services": [], "live": False, "icon": "📺" if k_tv else "📟"})
    # Nombre REAL de las TVs de forma AGNÓSTICA (Tizen/Roku/Chromecast…), preguntando a
    # cada aparato por sus endpoints estándar. Va aquí porque es donde ya sabemos que es
    # una TV, aunque la MAC no delate la marca y aunque no conteste al ping: responde en
    # su puerto de control. Solo para las que tienen nombre genérico.
    tvs = [d for d in out if d.get("kind") == "tv" and d.get("ip")
           and _is_generic_name(d.get("name", ""), d.get("brand", ""))]
    if tvs:
        sem_s = asyncio.Semaphore(8)
        got = await asyncio.gather(*[_tv_probe_name(d["ip"], sem_s) for d in tvs],
                                   return_exceptions=True)
        for d, nm in zip(tvs, got):
            if isinstance(nm, str) and nm:
                d["name"] = nm
                for kd in known:
                    if kd.get("ip") == d["ip"]:
                        kd["name"] = nm
                        learned.append((d["ip"], nm))
                        break

    if learned:
        ctx["settings"].set("known_devices", known)     # los nombres reales perduran
        bus = ctx.get("bus")
        if bus:
            for lip, lfn in learned:
                await bus.emit("log", {"level": "info",
                    "msg": f"🏷️ Nombre real leído de {lip}: «{lfn}» (friendlyName UPnP)"})
    # rastro SIEMPRE del reparto de nombres de las TVs (para auditar en nexus.log)
    bus = ctx.get("bus")
    if bus:
        for d in out:
            if d.get("kind") == "tv":
                dv = devices.get(d.get("ip"), {})
                await bus.emit("log", {"level": "info",
                    "msg": (f"📺 {d.get('ip') or '¿?'} -> «{d.get('name')}» | "
                            f"friendly={dv.get('friendly')!r} live={dv.get('live')} "
                            f"vendor={dv.get('vendor')!r}")})
    out += await _ha_entities(ctx)
    return {"devices": out, "n_ha": scan["n_ha"],
            "counts": {"total": len(out),
                       "controllable": sum(1 for d in out if d.get("controllable"))}}


# Teclas de apagado, por marca. Roku tiene una orden absoluta (PowerOff) y la
# obedece. Tizen acepta KEY_POWEROFF y NO apaga: la única que apaga es KEY_POWER,
# que es un INTERRUPTOR y sobre una TV en reposo la enciende. Por eso la entrada
# «off» SOLO se usa desde `_tv_apagar`, y solo cuando la TV ha confirmado que
# está encendida.
_TV_KEYMAP = {
    "off": ("keypress/PowerOff", "KEY_POWER"),
    "mute": ("keypress/VolumeMute", "KEY_MUTE"),
    "vol_up": ("keypress/VolumeUp", "KEY_VOLUP"),
    "vol_down": ("keypress/VolumeDown", "KEY_VOLDOWN"),
    "ch_up": ("keypress/ChannelUp", "KEY_CHUP"),
    "ch_down": ("keypress/ChannelDown", "KEY_CHDOWN"),
    "pair": ("keypress/Home", "KEY_HOME"),   # provoca el aviso de permiso en Samsung
}
# La que se manda cuando NO se sabe si la TV está encendida o en reposo. Puede
# que no apague —Tizen la acepta y la ignora—, pero no puede encender nada, que
# es lo que la hace utilizable a ciegas.
_TECLA_APAGADO_SEGURA = ("keypress/PowerOff", "KEY_POWEROFF")
_TV_VERB = {"off": "Apagando", "mute": "Silenciando", "vol_up": "Subiendo el volumen",
            "vol_down": "Bajando el volumen", "ch_up": "Canal siguiente",
            "ch_down": "Canal anterior"}


async def control_api(ctx, payload: dict) -> dict:
    """Ejecuta la acción al PINCHAR un dispositivo del buscador. TV (Roku/Samsung) y
    entidades de Home Assistant. Devuelve {ok, reply}."""
    kind = (payload.get("kind") or "").lower()
    action = (payload.get("action") or "").lower()

    if kind == "ha":
        eid = payload.get("entity_id", "")
        dom = eid.split(".")[0]
        if not eid:
            return {"ok": False, "reply": "Falta la entidad de Home Assistant."}
        if dom == "cover":
            svc = "open_cover" if action in ("on", "open", "toggle") else "close_cover"
            ok = await _ha_call(ctx, "cover", svc, eid)
        elif dom in ("scene", "script"):
            ok = await _ha_call(ctx, dom, "turn_on", eid)   # activar
        else:
            svc = "turn_on" if action in ("on", "open") else "turn_off"
            ok = await _ha_call(ctx, "homeassistant", svc, eid)
        name = payload.get("name", eid)
        verb = {"on": "Encendido", "off": "Apagado", "open": "Abriendo",
                "toggle": "Hecho"}.get(action, "Hecho")
        estado = "on" if action in ("on", "open", "toggle") else "off"
        return {"ok": ok, "state": (estado if ok else None),
                "reply": f"{verb}: {name}." if ok
                else f"No pude actuar sobre «{name}» (¿Home Assistant accesible?)."}

    if kind == "tv":
        tv = {"ip": payload.get("ip", ""), "brand": (payload.get("brand") or "").lower(),
              "mac": payload.get("mac", ""), "name": payload.get("name", "la TV")}
        if not tv["ip"] and not tv["mac"]:
            return {"ok": False, "reply": "No tengo IP ni MAC de esa TV."}
        # Persistimos la TV en known_devices en cuanto se interactúa con ella desde el
        # buscador: las órdenes por voz resuelven la TV desde ahí. Si solo tenemos IP,
        # sacamos su MAC de la tabla ARP para que el WoL funcione en frío.
        if not tv["mac"] and tv["ip"]:
            mac = await asyncio.to_thread(_mac_for_ip, tv["ip"])
            if mac:
                tv["mac"] = mac
        # Solo la identidad (ip/mac/marca), NO el nombre que manda el frontend: un nombre
        # genérico guardado taparía el real que difunde la TV. El nombre de pantalla lo
        # decide el escaneo (friendlyName) o el que pongas en ⚙.
        _save_tv(ctx, {"ip": tv["ip"], "brand": tv["brand"], "mac": tv["mac"], "is_tv": True})
        name = tv["name"]
        if action == "on":
            return await _tv_power_on(ctx, tv)
        # Apagar NO pasa por el mapa de teclas a pelo: hay que leer el estado antes
        # (el interruptor solo es seguro sabiéndolo) y comprobarlo después.
        if action == "off":
            return await _tv_apagar(ctx, tv)
        if action in _TV_KEYMAP:
            rp, sk = _TV_KEYMAP[action]
            ok = await _tv_key(ctx, tv, rp, sk)
            if action == "pair":
                if ok:
                    _mark_paired(ctx, tv)     # queda «✓ Conectado» de forma permanente
                    return {"ok": True, "reply": f"{name} conectada. El permiso quedó aceptado y "
                            "guardado: a partir de ahora sale como conectada y responde directa."}
                return {"ok": False, "reply": f"Estoy conectando con {name}: ACEPTA el aviso de "
                        "permiso que sale en la pantalla de la TV (la primera vez). Si no aparece, "
                        "enciéndela y vuelve a pulsar Conectar."}
            return {"ok": bool(ok), "state": None,
                    "reply": f"{_TV_VERB[action]} en {name}." if ok else _tv_fail(tv)}
        return {"ok": False, "reply": "Acción de TV no reconocida."}

    return {"ok": False, "reply": "Tipo de dispositivo no soportado."}
