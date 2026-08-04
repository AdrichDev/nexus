# -*- coding: utf-8 -*-
"""Tests del enganche HERMES ↔ ENGRAM (memoria de proyecto por MCP nativo), pedido
por Adri: «tanto hermes como nexus tienen que estar enganchados a engram».

nexus usa Engram por HTTP (backend/core/engram_bridge.py, ya cubierto por
test_engram.py). A Hermes lo enganchamos por su vía NATIVA: nexus provisiona en
~/.hermes/config.yaml un servidor MCP 'engram' (stdio, «engram mcp --project
nexus»). Aquí se prueba esa provisión:

  * skills/hermes/skill.py::_yaml_add_mcp_engram — cirugía de texto PURA sobre el
    config.yaml (sin PyYAML): añade el servidor sin romper el resto, idempotente,
    ruta de Windows con comillas simples (no corrompe las barras), y respeta un
    mcp_servers inline no editable. Se VALIDA además que el YAML resultante parsea
    (con PyYAML si está en el entorno de test) y apunta a «engram mcp --project nexus».
  * _has_mcp_engram — detección de si ya está enganchado.
  * provision_engram_mcp — escribe el fichero (con backup .bak_nexus), es idempotente
    y NO hace nada si engram no está instalado.
  * ensure_up — llama a provision_engram_mcp aunque Hermes ya esté vivo (para dejar
    la config en disco de cara al próximo arranque).

Ejecutar:  python tests/test_hermes_engram.py    (desde la carpeta nexus)
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
_fail = []
_pass = 0


def check(cond, msg):
    global _pass
    if cond:
        _pass += 1
    else:
        _fail.append(msg)
        print("  FALLO:", msg)


def _stub(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda _n: types.SimpleNamespace()
    sys.modules[name] = m
    return m


def load_skill_module(folder):
    """Carga skills/<folder>/skill.py stubbeando dependencias ausentes."""
    path = os.path.join(ROOT, "skills", folder, "skill.py")
    for _ in range(20):
        spec = importlib.util.spec_from_file_location(f"_hetest_{folder}", path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            return mod
        except ModuleNotFoundError as e:
            _stub(e.name)
    raise RuntimeError(folder)


class _FakeSettings(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def secret(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value

    def set_secret(self, key, value):
        self[key] = value


def _yaml_parse(txt):
    """Parsea YAML si PyYAML está disponible en el entorno de test; si no, None
    (la aserción de parseo se salta, pero el resto de checks siguen valiendo)."""
    try:
        import yaml
        return yaml.safe_load(txt)
    except Exception:
        return None


EXE_WIN = r"C:\Users\usuario\go\bin\engram.exe"


# ══════════════════════ _yaml_add_mcp_engram (PURA) ══════════════════════

def test_yaml_add_mcp_engram_casos():
    hsk = load_skill_module("hermes")

    def assert_engram_ok(txt, extra=""):
        d = _yaml_parse(txt)
        if d is None:
            return  # sin PyYAML en el entorno de test: no podemos validar el parseo
        eng = (d or {}).get("mcp_servers", {}).get("engram")
        check(bool(eng), f"yaml add: mcp_servers.engram existe {extra}")
        check(eng and eng.get("command") == EXE_WIN,
              f"yaml add: command = ruta exacta (sin corromper backslashes) {extra} -> {eng.get('command') if eng else None!r}")
        check(eng and eng.get("args") == ["mcp", "--project", "nexus"],
              f"yaml add: args = [mcp, --project, nexus] {extra}")

    # 1) fichero vacío
    new, ch = hsk._yaml_add_mcp_engram("", EXE_WIN, "nexus")
    check(ch is True, "yaml add: fichero vacío -> cambió")
    assert_engram_ok(new, "(vacío)")

    # 2) bloque model existente: se conserva
    cfg2 = 'model:\n  default: "gpt-4o"\n  provider: "custom"\n'
    new, ch = hsk._yaml_add_mcp_engram(cfg2, EXE_WIN, "nexus")
    check(ch is True and "gpt-4o" in new and "model:" in new,
          "yaml add: conserva el bloque model existente")
    assert_engram_ok(new, "(con model)")

    # 3) mcp_servers con OTRO server: coexisten
    cfg3 = 'mcp_servers:\n  filesystem:\n    command: "npx"\n    args: ["-y", "srv", "/tmp"]\n'
    new, ch = hsk._yaml_add_mcp_engram(cfg3, EXE_WIN, "nexus")
    check(ch is True, "yaml add: mcp_servers con otro server -> cambió")
    d = _yaml_parse(new)
    if d is not None:
        check("filesystem" in d.get("mcp_servers", {}) and "engram" in d.get("mcp_servers", {}),
              "yaml add: engram coexiste con filesystem (no lo pisa)")
    assert_engram_ok(new, "(coexiste)")

    # 4) idempotente: si ya está, no cambia
    new2, ch2 = hsk._yaml_add_mcp_engram(new, EXE_WIN, "nexus")
    check(ch2 is False and new2 == new, "yaml add: idempotente (ya tenía engram -> sin cambios)")

    # 5) mcp_servers: {} vacío inline -> se convierte en bloque con engram
    cfg5 = "foo: 1\nmcp_servers: {}\nbar: 2\n"
    new, ch = hsk._yaml_add_mcp_engram(cfg5, EXE_WIN, "nexus")
    check(ch is True, "yaml add: mcp_servers vacío {} -> cambió")
    d = _yaml_parse(new)
    if d is not None:
        check(d.get("foo") == 1 and d.get("bar") == 2 and "engram" in d.get("mcp_servers", {}),
              "yaml add: mcp_servers {} -> bloque, conserva foo/bar")

    # 6) mcp_servers inline NO editable -> no toca nada (seguridad)
    cfg6 = "mcp_servers: {filesystem: {command: npx}}\n"
    new, ch = hsk._yaml_add_mcp_engram(cfg6, EXE_WIN, "nexus")
    check(ch is False and new == cfg6,
          "yaml add: mcp_servers inline no editable -> se respeta, no corrompe")

    # 7) proyecto configurable
    new, _ = hsk._yaml_add_mcp_engram("", EXE_WIN, "otro")
    d = _yaml_parse(new)
    if d is not None:
        check(d["mcp_servers"]["engram"]["args"] == ["mcp", "--project", "otro"],
              "yaml add: respeta el nombre de proyecto pasado")

    # ── regresiones encontradas en revisión adversarial (opus) ──

    # 8) mcp_servers con indentación de 4 espacios: NO debe absorber el server previo
    cfg8 = "mcp_servers:\n    filesystem:\n        command: \"npx\"\n        args: [\"-y\", \"srv\"]\n"
    new, ch = hsk._yaml_add_mcp_engram(cfg8, EXE_WIN, "nexus")
    check(ch is True, "yaml add: mcp_servers a 4 espacios -> cambió")
    d = _yaml_parse(new)
    if d is not None:
        ms = d.get("mcp_servers", {})
        check("filesystem" in ms and "engram" in ms,
              f"yaml add: con 4 espacios NO absorbe filesystem (servers={list(ms.keys())})")

    # 9) BOM UTF-8 inicial: NO debe duplicar la clave mcp_servers
    cfg9 = "﻿mcp_servers:\n  filesystem:\n    command: \"npx\"\n"
    new, ch = hsk._yaml_add_mcp_engram(cfg9, EXE_WIN, "nexus")
    check(ch is True and new.count("mcp_servers:") == 1,
          "yaml add: BOM -> un solo bloque mcp_servers (no lo duplica)")
    d = _yaml_parse(new)
    if d is not None:
        check("filesystem" in d.get("mcp_servers", {}) and "engram" in d.get("mcp_servers", {}),
              "yaml add: BOM -> conserva filesystem y añade engram")

    # 10) comentario en la línea 'mcp_servers:': SÍ debe añadir (y conservar el comentario)
    cfg10 = "mcp_servers:  # mis servidores\n  filesystem:\n    command: \"npx\"\n"
    new, ch = hsk._yaml_add_mcp_engram(cfg10, EXE_WIN, "nexus")
    check(ch is True and "# mis servidores" in new,
          "yaml add: comentario en cabecera -> añade y conserva el comentario")
    d = _yaml_parse(new)
    if d is not None:
        check("filesystem" in d.get("mcp_servers", {}) and "engram" in d.get("mcp_servers", {}),
              "yaml add: con comentario en cabecera coexisten filesystem y engram")

    # 11) idempotencia también con 4 espacios / BOM (los casos raros)
    for label, base in (("4esp", cfg8), ("bom", cfg9), ("coment", cfg10)):
        n1, _c1 = hsk._yaml_add_mcp_engram(base, EXE_WIN, "nexus")
        _n2, c2 = hsk._yaml_add_mcp_engram(n1, EXE_WIN, "nexus")
        check(c2 is False, f"yaml add: idempotente en el caso '{label}' (2ª pasada no cambia)")

    # 12) indentación con TABS (YAML inválido de origen): bail seguro, no toca nada
    cfg12 = "mcp_servers:\n\tfilesystem:\n\t\tcommand: x\n"
    new, ch = hsk._yaml_add_mcp_engram(cfg12, EXE_WIN, "nexus")
    check(ch is False and new == cfg12,
          "yaml add: mcp_servers con TABS -> no lo edita (no mezcla tabs/espacios)")

    # ── regresiones de la 2ª ronda (sonnet): comentarios en COLUMNA 0 dentro del bloque ──

    # 13) comentario suelto en col0 ENTRE servers a 2 esp: no debe cerrar el bloque
    cfg13 = ("mcp_servers:\n  filesystem:\n    command: \"npx\"\n"
             "# --- separador de sección ---\n  otro:\n    command: \"y\"\n")
    new, ch = hsk._yaml_add_mcp_engram(cfg13, EXE_WIN, "nexus")
    check(ch is True and new.count("engram:") == 1, "yaml add: comentario col0 entre servers -> añade una vez")
    d = _yaml_parse(new)
    if d is not None:
        ms = d.get("mcp_servers", {})
        check(all(k in ms for k in ("filesystem", "otro", "engram")),
              f"yaml add: comentario col0 no pierde servers (servers={list(ms.keys())})")

    # 14) comentario col0 justo tras 'mcp_servers:' con hijos a 4 esp: no rompe la detección
    cfg14 = "mcp_servers:\n# servers MCP\n    filesystem:\n        command: \"npx\"\n"
    new, ch = hsk._yaml_add_mcp_engram(cfg14, EXE_WIN, "nexus")
    d = _yaml_parse(new)
    if d is not None:
        ms = d.get("mcp_servers", {})
        check("filesystem" in ms and "engram" in ms,
              f"yaml add: comentario col0 + 4 esp no absorbe filesystem (servers={list(ms.keys())})")

    # 15) FALSO NEGATIVO de idempotencia: engram YA presente pero tras un comentario col0
    cfg15 = ("mcp_servers:\n  filesystem:\n    command: \"npx\"\n"
             "# sep\n  engram:\n    command: \"engram\"\n    args: [\"mcp\"]\n")
    check(hsk._has_mcp_engram(cfg15) is True,
          "_has_mcp_engram: detecta engram aunque haya un comentario col0 antes (no falso negativo)")
    _new, ch = hsk._yaml_add_mcp_engram(cfg15, EXE_WIN, "nexus")
    check(ch is False, "yaml add: engram tras comentario col0 -> idempotente (no duplica la clave)")


def test_has_mcp_engram_no_falso_positivo_anidado():
    """Regresión (opus): un «engram:» ANIDADO (p.ej. dentro del env: de otro server)
    NO debe contar como que ya está el server engram."""
    hsk = load_skill_module("hermes")
    anidado = ('mcp_servers:\n  otro:\n    command: "x"\n    env:\n      engram: "1"\n')
    check(hsk._has_mcp_engram(anidado) is False,
          "_has_mcp_engram: 'engram:' anidado en env NO es falso positivo")
    # y por tanto _yaml_add SÍ añade el server engram real, sin perder 'otro'
    new, ch = hsk._yaml_add_mcp_engram(anidado, EXE_WIN, "nexus")
    check(ch is True, "_yaml_add: con engram anidado, sí añade el server real")
    d = _yaml_parse(new)
    if d is not None:
        check("otro" in d.get("mcp_servers", {}) and "engram" in d.get("mcp_servers", {}),
              "_yaml_add: engram anidado -> añade engram real y conserva 'otro'")


def test_has_mcp_engram():
    hsk = load_skill_module("hermes")
    con = 'mcp_servers:\n  engram:\n    command: "engram"\n    args: ["mcp"]\n'
    sin = 'mcp_servers:\n  filesystem:\n    command: "npx"\n'
    check(hsk._has_mcp_engram(con) is True, "_has_mcp_engram: detecta engram presente")
    check(hsk._has_mcp_engram(sin) is False, "_has_mcp_engram: no lo inventa si solo hay otro server")
    check(hsk._has_mcp_engram("") is False, "_has_mcp_engram: fichero vacío -> False")
    check(hsk._has_mcp_engram("model:\n  default: x\n") is False,
          "_has_mcp_engram: sin mcp_servers -> False")


# ══════════════════════ provision_engram_mcp (I/O, mockeado) ══════════════════════

def test_provision_engram_mcp():
    hsk = load_skill_module("hermes")
    import backend.core.infraestructura.engram_bridge as eng

    tmp = Path(tempfile.mkdtemp())
    cfg_path = tmp / "config.yaml"
    exe = tmp / "engram.exe"
    exe.write_text("bin", encoding="utf-8")

    old_installed = eng.installed
    old_exe = eng._engram_exe
    old_cfgpath = hsk._hermes_config_path
    try:
        hsk._hermes_config_path = lambda: str(cfg_path)

        # a) engram NO instalado -> no escribe nada
        eng.installed = lambda _ctx: False
        ch, det = hsk.provision_engram_mcp({"settings": _FakeSettings({})})
        check(ch is False and not cfg_path.exists(),
              "provision: engram no instalado -> no crea config.yaml")

        # b) engram instalado -> escribe el server MCP
        eng.installed = lambda _ctx: True
        eng._engram_exe = lambda _ctx: str(exe)
        ch, det = hsk.provision_engram_mcp({"settings": _FakeSettings({})})
        check(ch is True and cfg_path.exists(), "provision: engram instalado -> escribe config.yaml")
        txt = cfg_path.read_text(encoding="utf-8")
        check(hsk._has_mcp_engram(txt), "provision: el config.yaml queda con el server engram")
        check(str(exe) in txt, "provision: apunta al binario detectado")
        d = _yaml_parse(txt)
        if d is not None:
            check(d["mcp_servers"]["engram"]["args"] == ["mcp", "--project", "nexus"],
                  "provision: args «mcp --project nexus»")

        # c) idempotente -> segunda vez no cambia
        ch2, det2 = hsk.provision_engram_mcp({"settings": _FakeSettings({})})
        check(ch2 is False, "provision: idempotente (ya estaba -> no re-escribe)")

        # d) si ya había un config.yaml con otras cosas, se respalda al tocarlo
        cfg_path.write_text('model:\n  default: "gpt-4o"\n', encoding="utf-8")
        ch3, _ = hsk.provision_engram_mcp({"settings": _FakeSettings({})})
        check(ch3 is True, "provision: config con model -> añade engram")
        check((tmp / "config.yaml.bak_nexus").exists(),
              "provision: hace backup .bak_nexus antes de tocar el config.yaml")
        txt3 = cfg_path.read_text(encoding="utf-8")
        check("gpt-4o" in txt3 and hsk._has_mcp_engram(txt3),
              "provision: conserva el model y añade engram")
    finally:
        eng.installed = old_installed
        eng._engram_exe = old_exe
        hsk._hermes_config_path = old_cfgpath


def test_provision_no_sobrescribe_si_no_puede_leer():
    """Regresión (sonnet): si el config.yaml EXISTE pero no se puede leer (lock de
    Windows, antivirus, permiso transitorio), provision NO debe sobrescribirlo a
    ciegas — perdería la config real de Hermes. Debe abortar sin tocar el fichero."""
    import io as _io
    hsk = load_skill_module("hermes")
    import backend.core.infraestructura.engram_bridge as eng

    tmp = Path(tempfile.mkdtemp())
    cfg_path = tmp / "config.yaml"
    exe = tmp / "engram.exe"
    exe.write_text("bin", encoding="utf-8")
    original = 'model:\n  default: "gpt-4o"\nmcp_servers:\n  filesystem:\n    command: "npx"\n'
    real_open = _io.open
    real_open(str(cfg_path), "w", encoding="utf-8").write(original)

    old_installed, old_exe, old_cfgpath = eng.installed, eng._engram_exe, hsk._hermes_config_path

    def failing_open(p, *a, **k):
        mode = k.get("mode") or (a[0] if a else "r")
        if str(p) == str(cfg_path) and "r" in mode and "w" not in mode and "a" not in mode:
            raise PermissionError("locked")
        return real_open(p, *a, **k)

    try:
        eng.installed = lambda _ctx: True
        eng._engram_exe = lambda _ctx: str(exe)
        hsk._hermes_config_path = lambda: str(cfg_path)
        _io.open = failing_open
        ch, det = hsk.provision_engram_mcp({"settings": _FakeSettings({})})
    finally:
        _io.open = real_open
        eng.installed = old_installed
        eng._engram_exe = old_exe
        hsk._hermes_config_path = old_cfgpath

    after = real_open(str(cfg_path), encoding="utf-8").read()
    check(ch is False, "provision: config ilegible -> no reporta cambio")
    check("gpt-4o" in after and "filesystem" in after,
          "provision: config ilegible -> NO se sobrescribe (model y filesystem intactos)")
    check(not (tmp / "config.yaml.bak_nexus").exists() or after == original,
          "provision: config ilegible -> el fichero original queda igual")


def test_provision_nunca_lanza():
    """Contrato: provision_engram_mcp NUNCA propaga una excepción (best-effort)."""
    hsk = load_skill_module("hermes")
    import backend.core.infraestructura.engram_bridge as eng
    old_installed = eng.installed
    try:
        # installed revienta -> provision debe tragárselo y devolver (False, str)
        def boom(_ctx):
            raise RuntimeError("kaboom")
        eng.installed = boom
        ch, det = hsk.provision_engram_mcp({"settings": _FakeSettings({})})
        check(ch is False and isinstance(det, str),
              "provision: si algo revienta -> (False, detalle) sin propagar")
    finally:
        eng.installed = old_installed


# ══════════════════════ ensure_up engancha Engram ══════════════════════

def test_ensure_up_provisiona_engram_aunque_hermes_este_vivo():
    """Aunque Hermes YA esté arrancado y con clave válida (early-return por salud),
    ensure_up debe haber intentado dejar la config MCP de Engram en disco."""
    hsk = load_skill_module("hermes")
    called = {"n": 0}

    async def fake_alive(url, hdr):
        return True

    async def fake_auth(url, hdr):
        return True

    def fake_provision(ctx):
        called["n"] += 1
        return (False, "ya estaba")   # ya estaba: no emite log, camino simple

    old_alive, old_auth, old_prov = hsk._alive, hsk._auth_ok, hsk.provision_engram_mcp

    async def run():
        hsk._alive = fake_alive
        hsk._auth_ok = fake_auth
        hsk.provision_engram_mcp = fake_provision
        ctx = {"settings": _FakeSettings({"hermes_url": "http://127.0.0.1:8642"})}
        ok = await hsk.ensure_up(ctx)
        check(ok is True, "ensure_up: Hermes vivo+auth -> True")
        check(called["n"] == 1,
              "ensure_up: llama a provision_engram_mcp aunque Hermes ya esté vivo")

    try:
        asyncio.run(run())
    finally:
        hsk._alive = old_alive
        hsk._auth_ok = old_auth
        hsk.provision_engram_mcp = old_prov


def test_diagnose_reporta_engram():
    """diagnose() debe incluir engram_installed / engram_mcp para que «diagnostica
    hermes» diga si Hermes está enganchado a Engram."""
    hsk = load_skill_module("hermes")
    import backend.core.infraestructura.engram_bridge as eng

    tmp = Path(tempfile.mkdtemp())
    cfg_path = tmp / "config.yaml"
    cfg_path.write_text('mcp_servers:\n  engram:\n    command: "engram"\n    args: ["mcp"]\n',
                        encoding="utf-8")

    old_installed = eng.installed
    old_cfgpath = hsk._hermes_config_path
    old_port, old_alive = hsk._port_open, hsk._alive
    old_readenv = hsk._read_env_file

    async def fake_port(url):
        return False

    async def fake_alive(url, hdr):
        return False

    async def run():
        eng.installed = lambda _ctx: True
        hsk._hermes_config_path = lambda: str(cfg_path)
        hsk._port_open = fake_port
        hsk._alive = fake_alive
        hsk._read_env_file = lambda _p: {}
        ctx = {"settings": _FakeSettings({"hermes_url": "http://127.0.0.1:8642"})}
        d = await hsk.diagnose(ctx)
        check(d.get("engram_installed") is True, "diagnose: engram_installed=True")
        check(d.get("engram_mcp") is True, "diagnose: engram_mcp=True (config lo tiene)")

    try:
        asyncio.run(run())
    finally:
        eng.installed = old_installed
        hsk._hermes_config_path = old_cfgpath
        hsk._port_open = old_port
        hsk._alive = old_alive
        hsk._read_env_file = old_readenv


if __name__ == "__main__":
    tests = [test_yaml_add_mcp_engram_casos, test_has_mcp_engram,
             test_has_mcp_engram_no_falso_positivo_anidado,
             test_provision_engram_mcp, test_provision_no_sobrescribe_si_no_puede_leer,
             test_provision_nunca_lanza,
             test_ensure_up_provisiona_engram_aunque_hermes_este_vivo,
             test_diagnose_reporta_engram]
    for t in tests:
        print(f"· {t.__name__}")
        try:
            t()
        except Exception as e:
            _fail.append(f"{t.__name__} EXCEPCIÓN: {type(e).__name__}: {e}")
            print("  EXCEPCIÓN:", type(e).__name__, e)
    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    sys.exit(1 if _fail else 0)
