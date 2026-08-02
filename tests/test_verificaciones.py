# -*- coding: utf-8 -*-
"""Tests de las 3 verificaciones que pidió Adri, contra el CÓDIGO REAL:
  1) Móvil: la voz muteada (🔇 IA) avisa y NO habla, y solo habla lo del móvil.
  2) Planificador: frases retorcidas llegan a la capa de razonamiento (no se
     filtran como charla ni las secuestra una skill equivocada).
  3) Memoria: «recuerda que X» y «qué sabes de mí» enrutan bien; la memoria
     tiene los métodos de guardar/listar (+ roundtrip real si hay DB accesible).
"""
import asyncio
import importlib
import importlib.util
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_fail, _pass, _skip = [], 0, 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


class _U:
    def __call__(self, *a, **k):
        return _U()
    def __getattr__(self, _n):
        return _U()
    def __getitem__(self, _k):
        return _U()
    def __iter__(self):
        return iter(())


def _stub(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda _n: _U()
    sys.modules[name] = m


def _import_retry(loader):
    for _ in range(25):
        try:
            return loader()
        except ModuleNotFoundError as e:
            _stub(e.name)
    return loader()


def load_skill(folder):
    path = os.path.join(ROOT, "skills", folder, "skill.py")
    return _import_retry(lambda: _exec_skill(path, folder))


def _exec_skill(path, folder):
    spec = importlib.util.spec_from_file_location(f"_vsk_{folder}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pats(mod):
    return {k: re.compile(v, re.IGNORECASE) for k, v in mod.SKILL["patterns"].items()}


def route_local(p, text):
    for it, rx in p.items():
        if rx.search(text):
            return it
    return None


def load_core(name):
    return _import_retry(lambda: importlib.import_module(f"backend.core.{name}"))


# ============ 1) MÓVIL: voz muteada ============
def test_movil_voz_muteada():
    html = open(os.path.join(ROOT, "frontend", "mobile.html"), encoding="utf-8").read()
    m = re.search(r"async function speak\(text\)\s*\{(.*?)\n  \}", html, re.S)
    check(m is not None, "móvil: existe speak()")
    body = m.group(1) if m else ""
    # con muteAI debe cortar ANTES de intentar hablar y avisar en el hint
    check("if (muteAI)" in body, "móvil: speak() tiene guarda de muteAI")
    check("silenciada" in body.lower(), "móvil: avisa 'silenciada' cuando está muteado")
    # showReply solo habla lo del canal móvil (no lo del PC)
    sr = re.search(r"function showReply\(text, channel\)\s*\{(.*?)\n  \}", html, re.S)
    check(sr and "channel === 'mobile'" in sr.group(1), "móvil: showReply habla solo canal móvil")
    # el toggle 🔇/🔊 IA existe
    check("nexus_m_ai" in html and "mute-ai" in html, "móvil: botón IA (mute) presente")


# ============ 2) PLANIFICADOR: frases retorcidas ============
def test_planificador_frases():
    brain = load_core("brain")
    st, meta = brain._SMALLTALK_RX, brain._META_RX
    folders = ["media", "google_workspace", "hermes", "memory_graph", "telefono", "domotica"]
    P = {f: pats(load_skill(f)) for f in folders}

    def route_global(t):
        return {f for f in folders if route_local(P[f], t)}

    # (frase, skills PERMITIDAS: la correcta o ninguna -> planificador; NUNCA otra)
    casos = [
        ("quita el ruido ese de la tele que molesta", {"domotica"}),
        ("me apetece algo de música tranquila", {"media"}),
        ("apúntame que tengo que llamar al gestor mañana", {"memory_graph", "telefono", "google_workspace"}),
        ("échale un ojo a mis correos a ver qué hay", {"google_workspace"}),
        ("bájale al volumen que está muy alto", {"domotica"}),
    ]
    for t, permit in casos:
        check(not st.match(t), f"planif: '{t}' NO es charla (llega al planificador)")
        check(not meta.search(t), f"planif: '{t}' NO es meta")
        hits = route_global(t)
        check(hits.issubset(permit), f"planif: '{t}' no lo secuestra otra skill (casó {hits}, permitido {permit} o ninguna)")


# ============ 3) MEMORIA ============
def test_memoria_patrones():
    p = pats(load_skill("memory_graph"))
    # «recuerda que X» -> intent remember + extrae el hecho
    rx = p["remember"]
    m = rx.search("recuerda que el prototipo se entrega el jueves")
    check(m is not None, "memoria: 'recuerda que...' casa remember")
    check(m and "prototipo" in (m.groupdict().get("fact") or ""), "memoria: remember extrae el hecho")
    # «qué sabes de mí» -> list_knowledge
    check(route_local(p, "qué sabes de mí") == "list_knowledge", "memoria: 'qué sabes de mí' -> list_knowledge")
    check(route_local(p, "qué recuerdas de Ana") == "recall", "memoria: 'qué recuerdas de X' -> recall")


def test_memoria_backend():
    mem = load_core("memory")
    check("all_knowledge" in dir(mem.PgMemory), "memoria: pg.all_knowledge existe")
    check("remember" in dir(mem.PgMemory), "memoria: pg.remember existe")
    ddl = " ".join(mem.PgMemory._DDL).lower()
    check("memories" in ddl and "vector" in ddl, "memoria: DDL crea memories + vector")
    rag = load_core("rag")
    check(callable(getattr(rag, "list_knowledge", None)), "memoria: rag.list_knowledge existe")


def test_memoria_roundtrip_real():
    """Integración REAL contra la DB de Adri (localhost:5433) SI está accesible.
    Se SALTA (no falla) si no hay psycopg2 o la DB no responde."""
    global _skip
    try:
        import psycopg2  # noqa
    except Exception:
        _skip += 1
        print("  (saltado: sin psycopg2 en este entorno)")
        return
    # Sin contraseña escrita aquí: si no hay NEXUS_DB_URL, se salta.
    dsn = os.environ.get("NEXUS_DB_URL", "").strip()
    if not dsn:
        _skip += 1
        print("  (saltado: sin NEXUS_DB_URL en el entorno)")
        return
    try:
        import psycopg2
        c = psycopg2.connect(dsn, connect_timeout=2)
        c.autocommit = True
    except Exception:
        _skip += 1
        print("  (saltado: DB de memoria no accesible ahora)")
        return
    import time
    marca = f"test_nexus_{int(time.time())}"
    with c.cursor() as cur:
        cur.execute("INSERT INTO memories (kind, content) VALUES ('fact', %s)", (marca,))
        cur.execute("SELECT content FROM memories WHERE content = %s", (marca,))
        got = cur.fetchone()
        check(got and got[0] == marca, "memoria roundtrip: guardar + recuperar en la DB real")
        cur.execute("DELETE FROM memories WHERE content = %s", (marca,))  # limpieza
    c.close()


# ============ 4) TV: se REGISTRA al controlarla y la VOZ la encuentra ============
class _FakeSettings:
    """Sustituto en memoria del objeto settings (get/set) para tests sin disco/red."""
    def __init__(self, data=None):
        self._d = dict(data or {})

    def get(self, key, default=None):
        return self._d.get(key, default)

    def set(self, key, value):
        self._d[key] = value


def _fake_ctx(known=None):
    return {"settings": _FakeSettings({"known_devices": list(known or [])}),
            "bus": _U(), "channel": "test"}


def test_tv_save_persistencia():
    """_save_tv guarda la TV en known_devices con is_tv=True y NO duplica por IP."""
    dom = load_skill("domotica")
    ctx = _fake_ctx()
    dom._save_tv(ctx, {"ip": "192.168.1.50", "brand": "samsung", "name": "Samsung TV",
                       "mac": "AA:BB:CC:DD:EE:FF"})
    devs = ctx["settings"].get("known_devices")
    check(len(devs) == 1, "tv: _save_tv añade la TV a known_devices")
    check(devs[0].get("is_tv") is True, "tv: la TV guardada queda marcada is_tv=True")
    # segunda vez con la MISMA IP -> actualiza, NO duplica
    dom._save_tv(ctx, {"ip": "192.168.1.50", "brand": "samsung", "name": "Salón",
                       "mac": "AA:BB:CC:DD:EE:FF"})
    devs = ctx["settings"].get("known_devices")
    check(len(devs) == 1, "tv: _save_tv NO duplica la misma TV (dedupe por IP)")


def test_tv_control_api_registra():
    """control_api(kind=tv) PERSISTE la TV al controlarla desde el buscador: sin esto
    las órdenes por voz decían 'no encuentro TV' y entraban en bucle."""
    # el código fuente del branch tv DEBE invocar _save_tv
    src = open(os.path.join(ROOT, "skills", "domotica", "skill.py"), encoding="utf-8").read()
    branch = src.split('if kind == "tv":', 1)[-1].split("return {\"ok\": False, \"reply\": \"Tipo")[0]
    check("_save_tv(" in branch, "tv: control_api(kind=tv) llama a _save_tv")

    dom = load_skill("domotica")
    orig_key, orig_mac = dom._tv_key, dom._mac_for_ip

    async def _fake_key(*a, **k):
        return True

    dom._tv_key = _fake_key
    dom._mac_for_ip = lambda ip: "11:22:33:44:55:66"
    try:
        ctx = _fake_ctx()
        res = asyncio.run(dom.control_api(ctx, {
            "kind": "tv", "action": "mute", "ip": "192.168.1.50",
            "brand": "samsung", "name": "Samsung del salón"}))
        devs = ctx["settings"].get("known_devices")
        check(any(d.get("ip") == "192.168.1.50" and d.get("is_tv") for d in devs),
              "tv: tras control_api la TV queda en known_devices (is_tv)")
        check(any((d.get("mac") or "").endswith("55:66") for d in devs),
              "tv: control_api rellena la MAC (para Wake-on-LAN en frío)")
    finally:
        dom._tv_key, dom._mac_for_ip = orig_key, orig_mac


def test_tv_resolve_fallback_buscador():
    """_resolve_tv, si el SSDP rápido no ve la TV, cae al MISMO descubrimiento completo
    que el buscador visual (mDNS/puertos/marca) y la encuentra + persiste."""
    src = open(os.path.join(ROOT, "skills", "domotica", "skill.py"), encoding="utf-8").read()
    resolve = src.split("async def _resolve_tv(", 1)[-1].split("\nasync def ", 1)[0]
    check("_discover_all(" in resolve, "tv: _resolve_tv tiene el respaldo con _discover_all")

    dom = load_skill("domotica")
    orig_ssdp, orig_disc, orig_mac = dom._ssdp_discover, dom._discover_all, dom._mac_for_ip
    dom._TV_CACHE.update(tv=None, ts=0.0)

    dom._ssdp_discover = lambda timeout=2.5: {}          # el SSDP rápido NO la ve

    async def _fake_discover(_ctx):
        return {"devices": {"192.168.1.51": {
            "ip": "192.168.1.51", "mac": "11:22:33:44:55:66", "vendor": "Samsung",
            "ssdp_type": "", "port_type": "", "services": set(), "live": True}},
            "n_ha": 0}

    dom._discover_all = _fake_discover
    dom._mac_for_ip = lambda ip: "11:22:33:44:55:66"
    try:
        ctx = _fake_ctx()                                # known_devices vacío
        tv = asyncio.run(dom._resolve_tv(ctx))
        check(tv is not None, "tv: _resolve_tv ENCUENTRA la TV vía respaldo del buscador")
        check(tv and tv.get("ip") == "192.168.1.51", "tv: respaldo devuelve la IP correcta")
        check(tv and tv.get("brand") == "samsung", "tv: respaldo deduce la marca (samsung)")
        devs = ctx["settings"].get("known_devices")
        check(any(d.get("ip") == "192.168.1.51" and d.get("is_tv") for d in devs),
              "tv: la TV del respaldo queda PERSISTIDA (siguientes órdenes instantáneas)")
    finally:
        dom._ssdp_discover, dom._discover_all, dom._mac_for_ip = orig_ssdp, orig_disc, orig_mac
        dom._TV_CACHE.update(tv=None, ts=0.0)


def test_tv_samsung_token_por_tv():
    """Con DOS Samsung en casa (salón + habitación), el token de emparejamiento Tizen se
    guarda POR TV (clave con su MAC/IP), no en una clave global que se pisa. Antes la 2ª
    TV volvía a pedir permiso en pantalla cada vez porque su token machacaba al de la 1ª."""
    src = open(os.path.join(ROOT, "skills", "domotica", "skill.py"), encoding="utf-8").read()
    sam = src.split("async def _samsung(", 1)[-1].split("\nasync def ", 1)[0]
    check("samsung_tv_token_" in sam, "tv: _samsung deriva la clave del token POR TV (samsung_tv_token_<id>)")
    check(".secret(tok_key)" in sam, "tv: _samsung LEE el token con la clave por-TV")
    check(".set_secret(tok_key" in sam, "tv: _samsung GUARDA el token con la clave por-TV")
    check('.set_secret("samsung_tv_token"' not in sam,
          "tv: ya NO se guarda el token en la clave GLOBAL que se pisaba")
    tk = src.split("async def _tv_key(", 1)[-1].split("\nasync def ", 1)[0]
    check("_samsung(ctx, ip, samsung_key, tvid" in tk, "tv: _tv_key pasa el id por-TV a _samsung")
    check('tvid = tv.get("mac")' in tk, "tv: el id por-TV sale de la MAC de la TV (estable)")


def test_tv_nombre_real_no_tapado_por_autoguardado():
    """REGRESIÓN del bug REAL que veía Adri: al controlar la TV se guardaba «TV Samsung»
    en known_devices y ese nombre tapaba al que difunde la tele -> en la app salía siempre
    «TV Samsung». Este test reproduce la interacción (control_api + _pick_name), justo lo
    que los tests de antes NO cubrían. Debe fallar con el código viejo y pasar con el nuevo."""
    dom = load_skill("domotica")
    orig_key, orig_mac = dom._tv_key, dom._mac_for_ip

    async def _fake_key(*a, **k):
        return True

    dom._tv_key = _fake_key
    dom._mac_for_ip = lambda ip: "11:22:33:44:55:66"
    try:
        ctx = _fake_ctx()
        asyncio.run(dom.control_api(ctx, {
            "kind": "tv", "action": "mute", "ip": "192.168.1.52",
            "brand": "samsung", "name": "TV Samsung"}))
        kn = ctx["settings"].get("known_devices")[0]
        # 1) controlar la TV NO debe dejar un nombre de pantalla que tape el real
        check(not (kn.get("name") or "").strip(),
              "tv: control_api NO guarda un nombre genérico que tape el real")
        # 2) con el friendlyName en vivo, el nombre mostrado es el REAL, no 'TV Samsung'
        dev = {"friendly": "TV habitación Norte", "names": set()}
        check(dom._pick_name(dev, kn, "TV Samsung") == "TV habitación Norte",
              "tv: el nombre real ya NO queda tapado por el autoguardado")
        # 3) si TÚ le pones nombre en ⚙, ese manda sobre el friendlyName
        kn_user = {"name": "La del cuarto", "ip": "192.168.1.52"}
        check(dom._pick_name(dev, kn_user, "TV Samsung") == "La del cuarto",
              "tv: tu nombre manual (⚙) gana al friendlyName")
        # 4) EL BUG REAL: aunque en settings.json quedara guardado «TV Samsung» (genérico),
        #    NO debe tapar el nombre real. Esto es lo que le pasaba a Adri.
        kn_gen = {"name": "TV Samsung", "brand": "samsung", "ip": "192.168.1.52"}
        check(dom._pick_name(dev, kn_gen, "TV Samsung") == "TV habitación Norte",
              "tv: un «TV Samsung» guardado NO tapa el nombre real (el bug de verdad)")
        check(dom._is_generic_name("TV Samsung", "samsung") is True, "tv: «TV Samsung» es genérico")
        check(dom._is_generic_name("TV habitación Norte", "samsung") is False,
              "tv: un nombre propio NO es genérico")
    finally:
        dom._tv_key, dom._mac_for_ip = orig_key, orig_mac


def test_tv_friendlyname_upnp():
    """El escáner lee el nombre REAL que difunde la TV (friendlyName UPnP) y lo muestra
    SIEMPRE, en vez de un tipo genérico. Antes «TV Samsung»; ahora «TV habitación Norte»."""
    dom = load_skill("domotica")
    xml = ('<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
           '<friendlyName>[TV] TV habitación Norte</friendlyName>'
           '<modelName>UE50TU8005</modelName></device></root>')
    got = dom._upnp_name_from_xml(xml)
    check(got.get("friendly") == "[TV] TV habitación Norte", "upnp: extrae el friendlyName real de la TV")
    check(got.get("model") == "UE50TU8005", "upnp: extrae el modelo")
    check(dom._upnp_name_from_xml("") == {}, "upnp: XML vacío -> sin nombre (no rompe)")
    # _pick_name muestra el nombre real por encima de la etiqueta genérica...
    dev = {"friendly": "TV habitación Norte", "names": set(), "ssdp_type": "TV Samsung"}
    check(dom._pick_name(dev, None, "TV Samsung") == "TV habitación Norte",
          "upnp: _pick_name muestra el nombre real, no 'TV Samsung'")
    # ...pero TU nombre manual (known_devices) manda sobre el del fabricante
    check(dom._pick_name(dev, {"name": "La del cuarto"}, "TV Samsung") == "La del cuarto",
          "upnp: tu nombre manual gana al friendlyName")
    src = open(os.path.join(ROOT, "skills", "domotica", "skill.py"), encoding="utf-8").read()
    da = src.split("async def _discover_all(", 1)[-1].split("\nasync def ", 1)[0]
    check("_upnp_friendly(" in da, "upnp: _discover_all lee el friendlyName UPnP en el escaneo")
    # AGNÓSTICO: el sondeo de nombre de TVs prueba varios protocolos, sin decidir por marca
    pn = src.split("async def _tv_probe_name(", 1)[-1].split("\nasync def ", 1)[0]
    check("_samsung_tv_name(" in pn and "_roku_name(" in pn and "_cast_name(" in pn,
          "nombres: _tv_probe_name prueba Tizen + Roku + Chromecast (agnóstico)")
    sa = src.split("async def scan_api(", 1)[-1].split("\nasync def ", 1)[0]
    check("_tv_probe_name(" in sa, "nombres: scan_api resuelve el nombre de las TVs por sondeo agnóstico")
    check('d.get("brand") == "samsung"' not in sa, "nombres: scan_api NO filtra el nombre por marca")


def test_tv_conectada_persiste():
    """Al emparejar (aceptar el permiso en la TV) queda CONECTADA de forma PERMANENTE:
    se guarda paired=True en known_devices y el escáner marca connected=True. Agnóstico."""
    dom = load_skill("domotica")
    ctx = _fake_ctx()
    dom._mark_paired(ctx, {"ip": "192.168.1.53", "mac": "11:22:33:44:55:66", "brand": "samsung"})
    kd = ctx["settings"].get("known_devices")
    check(any(d.get("ip") == "192.168.1.53" and d.get("paired") for d in kd),
          "conectar: _mark_paired guarda paired=True (persiste al reiniciar/reescanear)")
    src = open(os.path.join(ROOT, "skills", "domotica", "skill.py"), encoding="utf-8").read()
    ca = src.split('if kind == "tv":', 1)[-1].split('"Tipo de dispositivo', 1)[0]
    check("_mark_paired(" in ca, "conectar: al emparejar con éxito se marca conectada")
    sa = src.split("async def scan_api(", 1)[-1].split("\nasync def ", 1)[0]
    check('kn.get("paired")' in sa and 'kd.get("paired")' in sa,
          "conectar: el escáner refleja connected desde el paired guardado")


# ============ 5) PLANIFICADOR: deja RASTRO en el log (verificable) ============
def test_planner_deja_rastro_en_log():
    """brain.py debe registrar el resultado del planificador SIEMPRE (acierto, plan sin
    ruta y sin acción) para poder AUDITAR en nexus.log que deduce las órdenes."""
    src = open(os.path.join(ROOT, "backend", "core", "brain.py"), encoding="utf-8").read()
    blk = src.split("plan = await llm.plan_action(", 1)[-1].split("# RESPALDO", 1)[0]
    check("plan_action error" in blk, "planif: se loguea el ERROR de plan_action")
    check("plan sin ruta valida" in blk, "planif: se loguea el plan SIN ruta válida")
    check("no dio accion" in blk, "planif: se loguea cuando NO hay acción (sigue cascada)")
    check("Entendido ->" in blk, "planif: se loguea el ACIERTO del planificador")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXC: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*54}\n{_pass} pasados, {len(_fail)} fallados, {_skip} saltados")
    if _fail:
        for f in _fail:
            print("  -", f)
    sys.exit(1 if _fail else 0)
