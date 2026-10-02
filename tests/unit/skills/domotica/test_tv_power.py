"""Isolated TV power behavior checks; run this file directly from the repository root."""

import asyncio
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[4]
SKILL_PATH = ROOT / "skills" / "domotica" / "skill.py"
MAC = "AA:BB:CC:DD:EE:FF"
IP = "192.168.1.50"


class _Settings(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


def _ctx():
    return {"settings": _Settings({"wol_broadcast": ""}), "bus": None, "graph": None}


def _skill(viva, teclas, wol, estados):
    spec = importlib.util.spec_from_file_location("isolated_domotica_tv_power", SKILL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    unexpected_paths = []

    def _unexpected(*args, **kwargs):
        unexpected_paths.append((args, kwargs))
        raise AssertionError("Unexpected external TV/ARP/network/persistence path")

    module._unexpected_paths = unexpected_paths

    async def _ip_actual(ctx, tv):
        return tv["ip"], viva

    async def _mute(ip):
        if not viva:
            return _unexpected(ip)
        return "0"  # live, not confirmed standby

    async def _key(ctx, tv, roku, samsung):
        if not viva:
            return _unexpected(ctx, tv, roku, samsung)
        teclas.append((roku, samsung))
        return True

    def _wake(mac, ip, broadcast):
        if viva:
            return _unexpected(mac, ip, broadcast)
        wol.append(mac)
        return True

    module._tv_ip_actual = _ip_actual
    module._samsung_mute_upnp = _mute
    module._tv_key = _key
    module._wol_burst = _wake
    module._mac_for_ip = lambda ip: MAC
    module._save_tv = lambda ctx, tv: None
    module._save_estado = lambda ctx, tv, on: estados.append(on)
    # These are not part of either expected path; fail closed if routing changes.
    for seam in ("_tv_esta_viva", "_ip_for_mac", "_save_ip", "_tv_estado",
                 "_samsung_power_state", "wake_on_lan", "_arp_table"):
        setattr(module, seam, _unexpected)
    return module


class TvPowerTests(unittest.TestCase):
    def test_encender_una_tv_dormida_no_manda_tecla(self):
        """EL BUG: WoL + tecla a la vez = se enciende y se apaga."""
        teclas, wol, estados = [], [], []
        module = _skill(False, teclas, wol, estados)
        result = asyncio.run(module._tv_power_on(
            _ctx(), {"ip": IP, "brand": "samsung", "name": "TV salón"}))
        self.assertEqual(teclas, [], f"a una TV DORMIDA no se le manda ninguna tecla ({teclas})")
        self.assertEqual(wol, [MAC], "solo se la despierta por Wake-on-LAN")
        self.assertTrue(result["ok"] and result.get("state") == "on",
                        f"y se informa de que queda encendida ({result})")
        self.assertEqual(module._unexpected_paths, [], "no se toca ningún camino externo inesperado")

    def test_encender_una_tv_viva_manda_encender(self):
        teclas, wol, estados = [], [], []
        module = _skill(True, teclas, wol, estados)
        result = asyncio.run(module._tv_power_on(
            _ctx(), {"ip": IP, "brand": "samsung", "name": "TV salón"}))
        self.assertEqual(teclas, [("keypress/PowerOn", "KEY_POWERON")],
                         f"a una TV VIVA se le manda ENCENDER, no un interruptor ({teclas})")
        self.assertEqual(wol, [], "y no hace falta despertarla por red")
        self.assertTrue(result["ok"] and result.get("state") == "on", "queda encendida")
        self.assertEqual(module._unexpected_paths, [], "no se toca ningún camino externo inesperado")


if __name__ == "__main__":
    unittest.main()
