# -*- coding: utf-8 -*-
"""Las doce skills pequeñas: ENRUTADO real y contrato del SKILL.md.

Cubre mcp_hands, engram, ai_media, n8n_flows, games, nucleo, billing, discord,
places, clima, dev_knowledge y devils_advocate.

Se enruta con el cargador de verdad (skills_loader.load_skills + route), no con
importlib, para que un ImportError o un choque con otra skill salga aquí.
Cada intent se prueba con varias formas de decir lo mismo: con tilde y sin ella,
con pronombre enclítico y sin él, singular y plural.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_fail = []; _pass = 0
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass


def check(c, m):
    global _pass
    if c: _pass += 1
    else: _fail.append(m); print("  FALLO:", m)


DOCE = ["ai_media", "billing", "clima", "dev_knowledge", "devils_advocate",
        "discord", "engram", "games", "mcp_hands", "n8n_flows", "nucleo", "places"]

# (frase, carpeta/intent al que TIENE que llegar)
DESTINOS = [
    # ---- mcp_hands
    ("qué manos tienes", "mcp_hands/list"),
    ("que manos tienes", "mcp_hands/list"),
    ("conectores mcp", "mcp_hands/list"),
    ("lístame los conectores", "mcp_hands/list"),
    ("listame los conectores", "mcp_hands/list"),
    ("muéstrame los conectores mcp", "mcp_hands/list"),
    ("enséñame los conectores mcp", "mcp_hands/list"),
    ("qué conectores tengo", "mcp_hands/list"),
    ("recarga los conectores", "mcp_hands/reload"),
    ("recárgame los conectores mcp", "mcp_hands/reload"),
    ("reconéctate a los mcp", "mcp_hands/reload"),
    ("usa filesystem read_file", "mcp_hands/call"),
    ("invoca github list_repos", "mcp_hands/call"),
    ("llama al conector filesystem read_file", "mcp_hands/call"),
    ("ejecuta el conector github list_repos", "mcp_hands/call"),
    # ---- engram
    ("está engram conectado", "engram/status"),
    ("esta engram conectado", "engram/status"),
    ("diagnostica engram", "engram/status"),
    ("qué tal va engram", "engram/status"),
    ("mis reglas", "engram/rules"),
    ("qué reglas tienes", "engram/rules"),
    ("memoria operativa", "engram/rules"),
    ("olvida la regla de no borrar sin preguntar", "engram/forget_rule"),
    ("recuerda en el proyecto que usamos sqlite", "engram/save"),
    ("apúntame en el proyecto que el puerto es 8177", "engram/save"),
    ("anótame en el proyecto que hay que probar", "engram/save"),
    ("guárdame en engram que el router es alfabético", "engram/save"),
    ("contexto del proyecto", "engram/context"),
    ("qué se decidió sobre el whatsapp", "engram/search"),
    # ---- ai_media
    ("genera una imagen de un dragón", "ai_media/gen_image"),
    ("diséñame un póster de verano", "ai_media/gen_image"),
    ("dibújame un logo para la marca", "ai_media/gen_image"),
    ("créame una ilustración de un bosque", "ai_media/gen_image"),
    ("analiza la imagen D:\\fotos\\logo.png", "ai_media/analyze_image"),
    ("analízame la imagen D:\\y.png", "ai_media/analyze_image"),
    ("descríbeme la foto D:\\a.jpg", "ai_media/analyze_image"),
    ("transcribe el audio D:\\notas\\r.mp3", "ai_media/transcribe"),
    ("pásame a texto la grabación D:\\c.wav", "ai_media/transcribe"),
    ("busca en internet quién ganó la liga", "ai_media/web_search"),
    ("googléame la receta de la paella", "ai_media/web_search"),
    # ---- n8n_flows
    ("envía un whatsapp a Ana diciendo que llego tarde", "n8n_flows/whatsapp"),
    ("dile a Marta por whatsapp que la reunión se mueve", "n8n_flows/whatsapp"),
    ("lanza el flujo backup diario", "n8n_flows/flow"),
    ("lánzame el flujo de backup", "n8n_flows/flow"),
    ("en n8n ejecuta el flujo scraping", "n8n_flows/flow"),
    # ---- games
    ("abre steam", "games/launcher"),
    ("ábreme steam", "games/launcher"),
    ("inicia la ea app", "games/launcher"),
    ("juega a Elden Ring", "games/play"),
    ("quiero jugar a Rust", "games/play"),
    ("instala Rust en steam", "games/install"),
    ("instálame Portal en steam", "games/install"),
    ("descárgame Doom en steam", "games/install"),
    ("actualiza el juego Valheim", "games/update"),
    ("actualízame el juego Terraria", "games/update"),
    ("valídame Rust en steam", "games/update"),
    # ---- nucleo
    ("qué modelo de IA usas", "nucleo/cual"),
    ("pero qué modelo de IA", "nucleo/cual"),
    ("qué núcleo de IA estás trabajando ahora", "nucleo/cual"),
    ("qué cerebro tienes", "nucleo/cual"),
    ("quién te mueve", "nucleo/cual"),
    # ---- billing
    ("hazle una factura a Acme por el diseño de 350 euros", "billing/invoice"),
    ("genérame una factura para Delta por la web de 1200 euros", "billing/invoice"),
    ("haz una factura al cliente Gamma por el mantenimiento", "billing/invoice"),
    ("factúrale a Acme por la mentoría de 90 euros", "billing/invoice"),
    ("ver facturas", "billing/list"),
    ("lístame las facturas", "billing/list"),
    # ---- discord
    ("abre discord", "discord/open"),
    ("ábreme el discord", "discord/open"),
    ("manda a discord: la build está lista", "discord/notify"),
    ("avísame por discord que ya está", "discord/notify"),
    ("mándale un mensaje a discord: hola", "discord/notify"),
    # ---- places
    ("abre google maps", "places/maps_open"),
    ("cómo llego a la estación", "places/route_to"),
    ("llévame hasta Toledo", "places/route_to"),
    ("ruta de Madrid a Toledo", "places/route_ab"),
    ("dónde hay una gasolinera", "places/place_search"),
    ("busca vuelos a París", "places/flights"),
    ("búscame hoteles en Roma", "places/hotels"),
    ("busca vídeos de gatos", "places/videos"),
    # ---- clima
    ("qué tiempo hace en Madrid", "clima/weather"),
    ("que tiempo hace", "clima/weather"),
    ("el tiempo", "clima/weather"),
    ("clima", "clima/weather"),
    ("temperatura en Barcelona", "clima/weather"),
    ("va a llover", "clima/weather"),
    ("hace frío", "clima/weather"),
    ("necesito paraguas", "clima/weather"),
    ("el tiempo en Sevilla mañana", "clima/weather"),
    # ---- dev_knowledge
    ("qué skills de desarrollo tienes", "dev_knowledge/list"),
    ("aplica la skill sdd-spec a mi sistema de login", "dev_knowledge/apply"),
    ("aplícame la skill sdd-spec a mi login", "dev_knowledge/apply"),
    ("cómo hago un pr", "dev_knowledge/auto"),
    ("créame una spec sdd", "dev_knowledge/auto"),
    # ---- devils_advocate
    ("activa el modo abogado del diablo", "devils_advocate/on"),
    ("actívame el modo crítico", "devils_advocate/on"),
    ("sé más crítico conmigo", "devils_advocate/on"),
    ("desactiva el modo abogado del diablo", "devils_advocate/off"),
    ("desactívame el modo abogado del diablo", "devils_advocate/off"),
    ("quítame el modo crítico", "devils_advocate/off"),
    ("modo crítico off", "devils_advocate/off"),
    ("abogado del diablo: quiero invertir todo en cripto", "devils_advocate/critique"),
    ("critica mi plan de lanzar la web en una semana", "devils_advocate/critique"),
    ("cuestióname esta idea de vender más barato", "devils_advocate/critique"),
    ("búscale pegas a mi propuesta de precios", "devils_advocate/critique"),
]

# Frases que NO son de estas skills: el fallo típico es una regex sin \b que
# casa dentro de otra palabra («pa-usa», «contra-tiempo», «des-activa»).
NO_TOCAR = [
    ("pausa la música", "mcp_hands"),
    ("pausa la guía de estilo", "dev_knowledge"),
    ("usa el navegador para abrir la web", "mcp_hands"),
    ("llama a 612345678", "mcp_hands"),
    ("contratiempo en la reunión de mañana", "clima"),
    ("pasatiempo para el finde", "clima"),
    ("cuánto tiempo de espera hay en el médico", "clima"),
    ("llegué a tiempo de verlo", "clima"),
    ("temperatura de la cpu", "clima"),
    ("temperatura de la gráfica", "clima"),
    ("enciende el aire que hace calor", "clima"),
    ("mueve la tarea enviar la factura a completadas", "billing"),
    ("cuál es el núcleo del problema", "nucleo"),
    ("qué modelo de negocio tenemos", "nucleo"),
    ("cuál es el modelo de datos", "nucleo"),
    ("busca X en google maps", "ai_media"),
    ("haz una foto con la webcam", "ai_media"),
    ("apaga el ordenador", "games"),
]


def main():
    from backend.core.aplicacion import skills_loader as sl
    reg = sl.load_skills()

    print("· las doce cargan con el cargador REAL, sin error de import")
    for f in DOCE:
        check(f in reg, f"{f} está registrada")
        check(reg.get(f) and reg[f].status != "error",
              f"{f} carga bien ({reg[f].description[:90] if f in reg else 'ausente'})")

    print("· cada intent se activa con varias formas naturales de decirlo")
    for frase, destino in DESTINOS:
        r = sl.route(frase)
        got = f"{r[0].folder}/{r[1]}" if r else "SIN RUTA (se lo come el cerebro)"
        check(got == destino, f"«{frase}» → {destino} (llegó a {got})")

    print("· no se roban frases ajenas (regex sin \\b dentro de otra palabra)")
    for frase, prohibida in NO_TOCAR:
        r = sl.route(frase)
        got = r[0].folder if r else ""
        check(got != prohibida, f"«{frase}» NO es de {prohibida} (fue a {got or 'ningún sitio'})")

    print("· todo intent declarado está atendido en handle()")
    for f in DOCE:
        src = (ROOT / "skills" / f / "skill.py").read_text(encoding="utf-8")
        for intent in reg[f].patterns:
            check(f'"{intent}"' in src or f"'{intent}'" in src,
                  f"{f}: handle() contempla el intent «{intent}»")

    print("· todas tienen SKILL.md, y dice qué NO hacen")
    for f in DOCE:
        doc_p = ROOT / "skills" / f / "SKILL.md"
        check(doc_p.is_file(), f"{f}/SKILL.md existe")
        if doc_p.is_file():
            doc = doc_p.read_text(encoding="utf-8")
            check("NO hace" in doc or "NO toca" in doc,
                  f"{f}/SKILL.md tiene la sección de lo que NO hace")

    print("· son agnósticas: ni el nombre del usuario ni sus rutas ni sus cuentas")
    for f in DOCE:
        textos = [(ROOT / "skills" / f / "skill.py").read_text(encoding="utf-8")]
        doc_p = ROOT / "skills" / f / "SKILL.md"
        if doc_p.is_file():
            textos.append(doc_p.read_text(encoding="utf-8"))
        for t in textos:
            for prohibido in ("Adri", "achoz", "D:\\Adrian", "C:\\Users\\", "@gmail", "hotmail"):
                check(prohibido not in t, f"{f} no lleva «{prohibido}»")

    print(f"\n{'='*50}\n{_pass} pasados, {len(_fail)} fallados")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
