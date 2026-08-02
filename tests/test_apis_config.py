# -*- coding: utf-8 -*-
"""APARTADO «APIS» — todas las claves en un solo sitio de la configuración."""
import re, sys
from pathlib import Path
from _frontend_js import js_hud  # el HUD entero, no solo command.js
ROOT = Path(__file__).resolve().parents[1]
_fail = []; _pass = 0
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
def check(c, m):
    global _pass
    if c: _pass += 1
    else: _fail.append(m); print("  FALLO:", m)

def main():
    js = js_hud()
    css = (ROOT / "frontend" / "css" / "command.css").read_text(encoding="utf-8")
    cfg = (ROOT / "backend" / "core" / "config.py").read_text(encoding="utf-8")

    print("· existe el apartado y se llama APIS")
    check("APIS · CLAVES DE ACCESO" in js, "la configuración tiene un apartado APIS")
    i_ap, i_pro = js.find("APIS · CLAVES DE ACCESO"), js.find("PROACTIVIDAD · PROJECT MANAGER")
    check(0 < i_ap < i_pro, "y va arriba del todo, no escondido al final")

    print("· TODAS las claves están dentro")
    tabla = js[js.find("const APIS = ["):js.find("function apisHTML")]
    secretos = re.findall(r'"([a-z_]+)"', re.search(r"SECRET_KEYS = \((.*?)\)\n", cfg, re.S).group(1))
    # Se excluyen los que NO se pegan a mano:
    #   link_token        → lo genera nexus para el QR
    #   samsung_tv_token  → lo entrega la propia tele al emparejar (uno por TV)
    #   db_url/db_password→ no son APIs, son la memoria local
    esperadas = [k for k in secretos if k not in ("link_token", "samsung_tv_token",
                                                 "db_url", "db_password")]
    for k in esperadas:
        check(f"'{k}'" in tabla, f"la clave «{k}» está en el apartado APIS")
    check("ig_business_account_id" in tabla, "y el ID de cuenta de Instagram")
    # Antes había DOS campos para el mismo número («ig_business_account_id» para
    # el análisis e «ig_user_id» para Content OS): quien rellenaba uno se quedaba
    # sin el otro. Ahora es uno solo y lo leen los dos sitios.
    check("ig_user_id" not in tabla,
          "y NO hay un segundo campo para el mismo ID: eso confundía y dejaba "
          "media herramienta sin configurar")

    print("· ya no están sueltas por otras secciones")
    for viejo in ("m-gid", "m-gsec", "m-igtok", "m-tg", "m-n8nkey", "m-dcwh",
                  "m-spid", "m-spsec", "m-hatok", "m-iguser"):
        check(f"#{viejo}'" not in js and f'id="{viejo}"' not in js,
              f"el campo suelto «{viejo}» ha desaparecido")
    # Las secciones que YA NO tienen el campo de la clave tienen que decir dónde
    # está ahora, o el usuario se queda mirando una sección sin saber qué le falta.
    # Lo que importa es que EL AVISO SIGA AHÍ y remita al apartado de claves; el
    # rótulo y el color son cosa del diseño (01/08/2026: el apartado pasó a
    # llamarse «CLAVES API» y se pinta con el color de su sección, no con el cian
    # de antes). Se comprueba la intención, no la cadena literal.
    avisos = re.findall(r"apartado <b style=\"color:[^\"]+\">([^<]+)</b>", js)
    check(len(avisos) >= 2,
          "las secciones antiguas remiten al apartado de claves")
    check(all(re.fullmatch(r"(APIS|CLAVES API)", a) for a in avisos),
          "y lo nombran igual que el apartado, no con un nombre inventado")

    print("· se pinta y se guarda solo, desde la tabla")
    check("function apisHTML" in js, "la pantalla se genera desde la tabla")
    check("APIS.forEach" in js, "y el guardado también recorre la tabla")
    check("'/api/secrets'" in js, "los secretos van a /api/secrets")
    check("tipo: 'ajuste'" in js, "los identificadores se distinguen de las claves")
    check("el.value !== ''" in js, "un campo vacío NO borra la clave ya guardada")

    print("· no se enseña ninguna clave")
    bloque = js[js.find("function apisHTML"):js.find("const acModelOpts")]
    check("'has_' + a.k" in bloque, "solo se mira el indicador has_*, nunca el valor")
    check("value=\"${esc(c[a.k]" in bloque and "type=\"password\"" in bloque,
          "las claves salen como password y solo los identificadores muestran valor")
    check(".api-grupo" in css and ".api-estado" in css, "tiene su estilo propio")


    print("\u00b7 el cat\u00e1logo de modelos es coherente (no hay «mini» sin su modelo base)")
    listas = {}
    for prov in ("openai", "anthropic", "gemini", "openrouter"):
        m = re.search(prov + r":\s*\[(.*?)\]", js, re.S)
        check(bool(m), "hay lista de modelos para " + prov)
        listas[prov] = re.findall(r"'([^']+)'", m.group(1)) if m else []
    for prov, mods in listas.items():
        check(len(mods) > 0, "la lista de " + prov + " no est\u00e1 vac\u00eda")
        check(len(mods) == len(set(mods)), "la lista de " + prov + " no repite modelos")
    # Esto es EL fallo que hubo: sal\u00eda «gpt-5.4-mini» pero no «gpt-5.4».
    # Si ofreces la versi\u00f3n peque\u00f1a de una familia, tienes que ofrecer la normal.
    for m in listas["openai"]:
        for suf in ("-mini", "-nano", "-pro"):
            if m.endswith(suf):
                base = m[: -len(suf)]
                check(base in listas["openai"],
                      "si est\u00e1 «" + m + "» tambi\u00e9n tiene que estar «" + base + "»")
    for exigido in ("gpt-5.6-sol", "gpt-5.5", "gpt-5.4", "gpt-5"):
        check(exigido in listas["openai"], "OpenAI: falta el modelo «" + exigido + "»")
    check("claude-opus-5" in listas["anthropic"], "Anthropic: est\u00e1 claude-opus-5")
    check("claude-opus-4-8" not in listas["anthropic"],
          "Anthropic: ya no se ofrece claude-opus-4-8 (qued\u00f3 atr\u00e1s)")
    # Aunque la lista se quede vieja, nunca te deja tirado:
    check('<option value="__custom__">' in js,
          "siempre puedes escribir un modelo a mano («otro (escribir)»)")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0

if __name__ == "__main__":
    sys.exit(main())
