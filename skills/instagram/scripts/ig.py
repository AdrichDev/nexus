#!/usr/bin/env python3
"""CLI para descargar reels, comentarios e insights de Instagram vía Graph API.

Solo stdlib. El script SOLO baja datos crudos (de forma robusta: paginación
completa con replies anidados, throttling y backoff ante rate limits). El
análisis (temas, sentimiento, FAQs, leads, ideas de contenido) lo hace Claude
leyendo el JSON que este script produce.

Credenciales: se leen de ../.env (copia .env.example a .env). Nunca se imprimen.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# Palabras que disparan automatizaciones de DM (ManyChat y similares). Un
# comentario que las contiene se marca is_trigger=true: es RUIDO para
# sentimiento pero es la SEÑAL de lead/intención de compra. Se puede
# sobreescribir con IG_TRIGGERS (lista separada por comas) en el .env.
DEFAULT_TRIGGERS = [
    "info", "precio", "precios", "cuanto", "cuánto", "cuesta", "costo",
    "comprar", "compro", "quiero", "me interesa", "interesa", "interesado",
    "interesada", "link", "enlace", "guia", "guía", "curso", "gratis",
    "plantilla", "template", "dispo", "disponible", "mas info", "más info",
    "como lo compro", "cómo lo compro",
    # verbos-imán típicos de lead magnet ("comenta X y te lo mando al DM").
    # Añade TUS palabras-CTA propias vía IG_TRIGGERS en el .env.
    "dame", "envia", "envía", "mandame", "mándame",
]


def load_env():
    # nexus: las credenciales llegan por VARIABLES DE ENTORNO desde el minion
    # (skills/instagram/skill.py), que las saca de config/secrets.json. Así no
    # hay un .env con el token dentro de la carpeta de la skill ni aparecen en
    # la linea de comandos del proceso. El .env sigue funcionando como respaldo
    # para quien use este script suelto.
    if os.environ.get("INSTAGRAM_ACCESS_TOKEN"):
        cfg = {k: os.environ[k] for k in
               ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ACCOUNT_ID",
                "IG_API_VERSION", "IG_TRIGGERS") if os.environ.get(k)}
        return cfg
    if not ENV_PATH.exists():
        sys.exit(f"falta {ENV_PATH}. Copia .env.example a .env y rellena las credenciales.")
    cfg = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ACCOUNT_ID"):
        if not cfg.get(k):
            sys.exit(f"falta {k} en {ENV_PATH}")
    cfg.setdefault("IG_API_VERSION", "v21.0")
    return cfg


def triggers_from(cfg):
    raw = cfg.get("IG_TRIGGERS", "")
    if raw.strip():
        return [t.strip().lower() for t in raw.split(",") if t.strip()]
    return list(DEFAULT_TRIGGERS)


def redact(text, token):
    """Nunca dejar que el token aparezca en logs/errores."""
    if token and token in text:
        text = text.replace(token, "<TOKEN>")
    return text


# ---------------------------------------------------------------------------
# HTTP con throttling + backoff ante rate limits
# ---------------------------------------------------------------------------
# Códigos de error de rate limit de la Graph API (dentro del JSON de error).
RATE_LIMIT_CODES = {4, 17, 32, 613, 80004}


# Un reel con 40 comentarios y uno con 4.000 no se pueden bajar al mismo ritmo:
# el segundo hace cientos de llamadas seguidas y acaba comiéndose el rate limit.
# Por eso el ritmo SUBE solo cuando el volumen lo pide, y vuelve a bajar si la
# API deja de quejarse. Es preferible tardar 30 s más que perder la descarga a
# medias y tener que empezar de cero.
THROTTLE_BASE = 0.4          # ritmo normal
THROTTLE_ALTO = 0.6          # a partir de MUCHAS llamadas seguidas
THROTTLE_TECHO = 1.5         # si la API ya nos ha frenado
LLAMADAS_VOLUMEN_ALTO = 40   # a partir de aquí se considera alto volumen


class GraphClient:
    def __init__(self, cfg, throttle=THROTTLE_BASE, max_retries=5, verbose=True):
        self.token = cfg["INSTAGRAM_ACCESS_TOKEN"]
        self.base = f"https://graph.facebook.com/{cfg['IG_API_VERSION']}"
        self.throttle_base = throttle
        self.throttle = throttle
        self.max_retries = max_retries
        self.verbose = verbose
        self._last_call = 0.0
        self._llamadas = 0

    def _ajusta_ritmo(self, frenados=False):
        """Sube el ritmo si hay volumen o si la API nos ha frenado.

        Devuelve el ritmo nuevo. Se llama en cada peticion, asi que el ajuste es
        continuo: no hace falta saber de antemano cuantos comentarios hay."""
        if frenados:
            self.throttle = min(THROTTLE_TECHO, max(self.throttle, THROTTLE_ALTO) * 1.5)
        elif self._llamadas >= LLAMADAS_VOLUMEN_ALTO:
            self.throttle = max(self.throttle, THROTTLE_ALTO)
        else:
            self.throttle = self.throttle_base
        return self.throttle

    def log(self, msg):
        if self.verbose:
            print(redact(msg, self.token), file=sys.stderr)

    def _sleep_throttle(self):
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.throttle:
            time.sleep(self.throttle - elapsed)

    def get(self, path=None, params=None, full_url=None):
        """GET a un endpoint (path+params) o a una URL completa (paginación).

        Reintenta con backoff exponencial cuando la Graph API responde con un
        código de rate limit o un 429/500.
        """
        if full_url:
            url = full_url
            # el cursor `next` ya trae access_token embebido
        else:
            p = dict(params or {})
            p["access_token"] = self.token
            url = f"{self.base}/{path}?{urllib.parse.urlencode(p)}"

        attempt = 0
        while True:
            self._ajusta_ritmo()
            self._sleep_throttle()
            self._last_call = time.monotonic()
            self._llamadas += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "ig-reels-analysis/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                try:
                    err = json.loads(body).get("error", {})
                except Exception:
                    err = {}
                code = err.get("code")
                is_rate = e.code == 429 or code in RATE_LIMIT_CODES
                is_transient = e.code in (500, 502, 503, 504)
                if (is_rate or is_transient) and attempt < self.max_retries:
                    attempt += 1
                    wait = min(60, 2 ** attempt) + (attempt * 0.5)
                    if is_rate:
                        self._ajusta_ritmo(frenados=True)
                        self.log(f"[throttle] la API nos frena: subo a {self.throttle:.2f}s "
                                 f"entre llamadas")
                    self.log(f"[backoff] {'rate-limit' if is_rate else 'transient'} "
                             f"(HTTP {e.code}, code {code}) — reintento {attempt}/{self.max_retries} en {wait:.0f}s")
                    time.sleep(wait)
                    continue
                msg = err.get("message", body)
                sys.exit(redact(f"Graph API error (HTTP {e.code}, code {code}): {msg}", self.token))
            except urllib.error.URLError as e:
                if attempt < self.max_retries:
                    attempt += 1
                    wait = min(30, 2 ** attempt)
                    self.log(f"[backoff] red ({e.reason}) — reintento {attempt}/{self.max_retries} en {wait:.0f}s")
                    time.sleep(wait)
                    continue
                sys.exit(f"error de red: {e.reason}")
            except (TimeoutError, ConnectionError, OSError) as e:
                # socket timeout / conexión caída: NO son subclase de URLError,
                # así que si no se atrapan aquí matan todo el bundle a mitad.
                if attempt < self.max_retries:
                    attempt += 1
                    wait = min(30, 2 ** attempt)
                    self.log(f"[backoff] timeout/conexión ({e}) — reintento {attempt}/{self.max_retries} en {wait:.0f}s")
                    time.sleep(wait)
                    continue
                sys.exit(f"error de red (timeout/conexión): {e}")

    def paginate(self, path, params):
        """Itera todas las páginas de un edge, devolviendo cada item."""
        p = dict(params)
        data = self.get(path=path, params=p)
        while True:
            for item in data.get("data", []):
                yield item
            nxt = data.get("paging", {}).get("next")
            if not nxt:
                break
            data = self.get(full_url=nxt)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def account_username(client, ig_id):
    try:
        return client.get(path=ig_id, params={"fields": "username"}).get("username", "")
    except SystemExit:
        return ""


def list_media(client, ig_id, limit=25):
    fields = ("id,caption,media_type,media_product_type,permalink,timestamp,"
              "like_count,comments_count")
    out = []
    for m in client.paginate(ig_id + "/media", {"fields": fields, "limit": 50}):
        out.append(m)
        if len(out) >= limit:
            break
    return out


def fetch_comment_replies(client, comment_id):
    """Trae TODAS las respuestas anidadas de un comentario (paginadas)."""
    fields = "id,text,username,timestamp,like_count"
    return list(client.paginate(comment_id + "/replies", {"fields": fields, "limit": 50}))


def tag_comment(c, owner_username, triggers):
    text = (c.get("text") or "")
    low = text.lower()
    matched = next((t for t in triggers if t in low), None)
    c["is_trigger"] = matched is not None
    c["matched_trigger"] = matched
    c["is_from_owner"] = bool(owner_username) and (c.get("username", "").lower() == owner_username.lower())
    return c


def fetch_comments(client, media_id, owner_username, triggers, deep_replies=True):
    """Todos los comentarios top-level + replies, cada uno tagueado."""
    fields = ("id,text,username,timestamp,like_count,"
              "replies{id,text,username,timestamp,like_count}")
    comments = []
    for c in client.paginate(media_id + "/comments", {"fields": fields, "limit": 50}):
        tag_comment(c, owner_username, triggers)
        replies = c.get("replies", {}).get("data", [])
        # si el edge de replies pagina (más de los devueltos inline), completar
        if deep_replies and c.get("replies", {}).get("paging", {}).get("next"):
            replies = fetch_comment_replies(client, c["id"])
        for r in replies:
            tag_comment(r, owner_username, triggers)
        c["replies"] = replies
        c["reply_count"] = len(replies)
        comments.append(c)
    return comments


# Sets de métricas de reels (de más completo a mínimo seguro). La Graph API
# rechaza toda la petición si una métrica no existe en la versión actual, así
# que probamos de más a menos hasta que una funcione.
# De más completo a más básico: se prueba en orden y se usa el primero que la
# versión de la API acepte. Las de perfil (follows, profile_visits) alimentan el
# bloque de DISTRIBUCION, que hasta ahora salía siempre vacío porque nadie las
# pedía: el motor las buscaba y el script no las traía.
INSIGHT_SETS = [
    "reach,likes,comments,saved,shares,total_interactions,follows,profile_visits,"
    "profile_activity,ig_reels_avg_watch_time,ig_reels_video_view_total_time,"
    "clips_replays_count",
    "reach,likes,comments,saved,shares,total_interactions,follows,profile_visits,"
    "ig_reels_avg_watch_time,ig_reels_video_view_total_time,clips_replays_count",
    "reach,likes,comments,saved,shares,total_interactions,ig_reels_avg_watch_time,ig_reels_video_view_total_time,clips_replays_count",
    "reach,likes,comments,saved,shares,total_interactions,follows,profile_visits",
    "reach,likes,comments,saved,shares,total_interactions",
    "reach,likes,comments,saved,shares",
    "reach",
]


def fetch_insights(client, media_id, metrics=None):
    candidates = [metrics] if metrics else INSIGHT_SETS
    last = None
    for metric_set in candidates:
        try:
            data = client.get(path=media_id + "/insights", params={"metric": metric_set})
        except SystemExit as e:
            last = str(e)
            continue
        result = {}
        for item in data.get("data", []):
            vals = item.get("values", [])
            result[item["name"]] = vals[0].get("value") if vals else None
        result["_metrics_requested"] = metric_set
        return result
    return {"_error": "no se pudieron obtener insights (todas las métricas rechazadas)",
            "_last": last}


# ---------------------------------------------------------------------------
# CUENTAS DE OTROS (competencia) — business_discovery
# ---------------------------------------------------------------------------
# Esta es la UNICA via oficial para mirar una cuenta que no administras, y solo
# funciona con cuentas PROFESIONALES (Business/Creator) y publicas. Da lo publico
# y nada mas: seguidores, publicaciones, reproducciones, likes y el NUMERO de
# comentarios.
#
# Lo que NO da, por mucho que se pida: el TEXTO de los comentarios, los
# compartidos, los guardados y el alcance. Eso son datos privados de esa cuenta y
# la API no los expone a terceros. Aqui no se estiman ni se sacan por otra via:
# se declara que no constan. Bajarlos por scraping violaria los terminos de
# Instagram y pondria en riesgo el token.
# `media_url`/`thumbnail_url` son la PORTADA del reel. Sin ella no se puede
# analizar que sale en el video, que es media decision editorial.
CAMPOS_MEDIA_AJENA = [
    "id,caption,media_type,media_product_type,permalink,timestamp,"
    "like_count,comments_count,view_count,media_url,thumbnail_url",
    "id,caption,media_type,media_product_type,permalink,timestamp,"
    "like_count,comments_count,view_count",
    "id,caption,media_type,media_product_type,permalink,timestamp,"
    "like_count,comments_count",
    "id,caption,media_type,permalink,timestamp,like_count,comments_count",
]
CAMPOS_PERFIL_AJENO = [
    "username,name,biography,website,followers_count,follows_count,"
    "media_count,profile_picture_url",
    "username,followers_count,media_count",
]


def business_discovery(client, mi_id, usuario, limite=25):
    """Los datos publicos de UNA cuenta ajena, o el motivo por el que no salen.

    Se prueban juegos de campos de mas a menos: si la version de la API no
    conoce `view_count`, rechaza la peticion ENTERA, asi que hay que reintentar
    con menos campos en vez de quedarse sin nada."""
    usuario = (usuario or "").lstrip("@").strip()
    if not usuario:
        return {"error": "sin usuario"}
    ultimo = None
    for perfil in CAMPOS_PERFIL_AJENO:
        for medios in CAMPOS_MEDIA_AJENA:
            campos = (f"business_discovery.username({usuario})"
                      f"{{{perfil},media.limit({int(limite)}){{{medios}}}}}")
            try:
                data = client.get(path=mi_id, params={"fields": campos})
            except SystemExit as e:
                ultimo = str(e)
                continue
            bd = (data or {}).get("business_discovery")
            if not bd:
                ultimo = "la respuesta no trae business_discovery"
                continue
            media = (bd.pop("media", {}) or {}).get("data", []) or []
            bd["media"] = media
            bd["_campos"] = {"perfil": perfil, "media": medios}
            bd["_tiene_reproducciones"] = "view_count" in medios
            return bd
    return {"error": "no se ha podido consultar esa cuenta",
            "detalle": ultimo,
            "motivos": ["la cuenta no es Business/Creator (una cuenta personal "
                        "no se puede consultar por la API)",
                        "el nombre de usuario esta mal escrito",
                        "la cuenta es privada o tiene restriccion de edad",
                        "tu token no tiene el permiso instagram_basic"]}


def mi_perfil_publico(client, mi_id, limite=25):
    """TU cuenta medida con la MISMA vara que las ajenas.

    Se piden los mismos campos publicos que para ellas. Comparar tu engagement
    sobre alcance contra el suyo sobre seguidores no compara nada: el alcance
    ajeno no se ve, asi que la comparacion se hace toda sobre seguidores."""
    for perfil in CAMPOS_PERFIL_AJENO:
        for medios in CAMPOS_MEDIA_AJENA:
            try:
                data = client.get(path=mi_id,
                                  params={"fields": f"{perfil},media.limit({int(limite)}){{{medios}}}"})
            except SystemExit:
                continue
            media = (data.pop("media", {}) or {}).get("data", []) or []
            data["media"] = media
            return data
    return {"error": "no se han podido leer los datos publicos de tu propia cuenta"}


def cmd_competencia(client, cfg, args):
    cuentas = []
    for u in args.usuarios:
        for parte in str(u).split(","):
            parte = parte.strip()
            if parte:
                cuentas.append(parte)
    salida = {"cuentas": [], "limites": LIMITES_CUENTAS_AJENAS,
              "propia": mi_perfil_publico(client, cfg["INSTAGRAM_BUSINESS_ACCOUNT_ID"],
                                          args.recent)}
    for u in cuentas:
        client.log(f"[competencia] consultando @{u.lstrip('@')}")
        salida["cuentas"].append({"usuario": u.lstrip("@"),
                                  "datos": business_discovery(client, cfg["INSTAGRAM_BUSINESS_ACCOUNT_ID"],
                                                              u, args.recent)})
    _emit(salida, args.out)


# Lo que la API oficial NO da de una cuenta ajena. Va en la salida para que el
# informe lo diga con todas las letras en vez de dejar huecos sin explicar.
LIMITES_CUENTAS_AJENAS = [
    {"que": "El texto de los comentarios",
     "por_que": "la API solo da el NUMERO de comentarios de cuentas ajenas, no lo "
                "que dicen. Sin texto no hay sentimiento posible.",
     "donde": "se leen a mano en la publicacion"},
    {"que": "Compartidos", "por_que": "es una metrica privada de esa cuenta",
     "donde": "solo lo ve quien administra la cuenta"},
    {"que": "Guardados", "por_que": "es una metrica privada de esa cuenta",
     "donde": "solo lo ve quien administra la cuenta"},
    {"que": "Alcance e impresiones", "por_que": "son metricas privadas de esa cuenta",
     "donde": "solo lo ve quien administra la cuenta"},
]


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------
def cmd_perfil(client, cfg, args):
    """Tus propios datos publicos + tus ultimas publicaciones con sus captions.

    Es lo que hace falta para deducir de que va tu cuenta sin gastar cuota en
    insights que aqui no se usan."""
    _emit(mi_perfil_publico(client, cfg["INSTAGRAM_BUSINESS_ACCOUNT_ID"], args.recent),
          args.out)


def cmd_list(client, cfg, args):
    media = list_media(client, cfg["INSTAGRAM_BUSINESS_ACCOUNT_ID"], args.limit)
    if args.json:
        print(json.dumps(media, ensure_ascii=False, indent=2))
        return
    for m in media:
        cap = (m.get("caption") or "").replace("\n", " ")[:70]
        print(f"{m['id']}  {m.get('media_product_type','?'):8}  "
              f"❤{m.get('like_count',0):>5}  💬{m.get('comments_count',0):>4}  "
              f"{m.get('timestamp','')[:10]}  {cap}")


def cmd_comments(client, cfg, args):
    triggers = triggers_from(cfg)
    owner = account_username(client, cfg["INSTAGRAM_BUSINESS_ACCOUNT_ID"])
    comments = fetch_comments(client, args.media_id, owner, triggers)
    payload = _summarize_comments(args.media_id, owner, comments)
    _emit(payload, args.out)


def cmd_insights(client, cfg, args):
    ins = fetch_insights(client, args.media_id, args.metrics)
    _emit({"media_id": args.media_id, "insights": ins}, args.out)


def cmd_bundle(client, cfg, args):
    ig_id = cfg["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
    triggers = triggers_from(cfg)
    owner = account_username(client, ig_id)

    if args.recent:
        media_list = list_media(client, ig_id, args.recent)
    else:
        # traer meta de cada media id dado
        media_list = []
        for mid in args.media_ids:
            fields = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"
            media_list.append(client.get(path=mid, params={"fields": fields}))

    outdir = Path(args.out or ".")
    outdir.mkdir(parents=True, exist_ok=True)
    index = []
    for m in media_list:
        mid = m["id"]
        client.log(f"[bundle] {mid} — comentarios + insights…")
        comments = fetch_comments(client, mid, owner, triggers)
        summary = _summarize_comments(mid, owner, comments)
        insights = fetch_insights(client, mid)
        bundle = {"media": m, "insights": insights, **summary}
        fpath = outdir / f"{mid}.json"
        fpath.write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
        index.append({
            "media_id": mid,
            "permalink": m.get("permalink"),
            "timestamp": m.get("timestamp"),
            "comments_total": summary["counts"]["total_comments"],
            "leads": summary["counts"]["lead_candidates"],
            "file": str(fpath),
        })
    (outdir / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2))
    print(json.dumps({"account": owner, "reels": len(index), "outdir": str(outdir),
                      "index": index}, ensure_ascii=False, indent=2))


def _summarize_comments(media_id, owner, comments):
    """Aplana replies y precalcula conteos que el análisis va a necesitar."""
    flat = []
    for c in comments:
        flat.append({k: c[k] for k in c if k != "replies"})
        for r in c.get("replies", []):
            r2 = dict(r)
            r2["parent_id"] = c["id"]
            flat.append(r2)
    non_owner = [c for c in flat if not c.get("is_from_owner")]
    triggers = [c for c in non_owner if c.get("is_trigger")]
    return {
        "media_id": media_id,
        "owner_username": owner,
        "counts": {
            "total_comments": len(flat),
            "from_owner": len(flat) - len(non_owner),
            "real_comments": len(non_owner),  # ruido ManyChat/dueño fuera
            "lead_candidates": len(triggers),  # pool de leads (triggers)
        },
        "comments": comments,
        "flat": flat,
    }


def _emit(payload, out):
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if out:
        Path(out).write_text(text)
        print(f"escrito: {out}", file=sys.stderr)
    else:
        print(text)


def main():
    # flags comunes: aceptadas tanto antes como después del subcomando
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--throttle", type=float, default=0.4, help="segundos mínimos entre llamadas (default 0.4)")
    common.add_argument("--retries", type=int, default=5, help="reintentos ante rate limit (default 5)")
    common.add_argument("-q", "--quiet", action="store_true", help="sin logs de progreso a stderr")

    ap = argparse.ArgumentParser(prog="ig", parents=[common],
                                 description="Descarga reels/comentarios/insights de IG (Graph API)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", parents=[common], help="listar media reciente de la cuenta")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("comments", parents=[common], help="todos los comentarios+replies de un media")
    p.add_argument("media_id")
    p.add_argument("--out", help="archivo de salida (default stdout)")

    p = sub.add_parser("insights", parents=[common], help="insights de un reel")
    p.add_argument("media_id")
    p.add_argument("--metrics", help="lista de métricas separada por comas (default: autodetecta)")
    p.add_argument("--out")

    p = sub.add_parser("perfil", parents=[common],
                       help="tus datos publicos y tus ultimas publicaciones")
    p.add_argument("--recent", type=int, default=25)
    p.add_argument("--out")

    p = sub.add_parser("competencia", parents=[common],
                       help="datos publicos de cuentas ajenas (business_discovery)")
    p.add_argument("usuarios", nargs="+", help="uno o mas @usuario (o separados por comas)")
    p.add_argument("--recent", type=int, default=25, help="cuantas publicaciones por cuenta")
    p.add_argument("--out")

    p = sub.add_parser("bundle", parents=[common], help="baja media+comentarios+insights de varios reels a una carpeta")
    p.add_argument("media_ids", nargs="*", help="uno o más media IDs")
    p.add_argument("--recent", type=int, help="en vez de IDs, los N reels más recientes")
    p.add_argument("--out", help="carpeta de salida (default: .)")

    args = ap.parse_args()
    cfg = load_env()
    client = GraphClient(cfg, throttle=args.throttle, max_retries=args.retries, verbose=not args.quiet)

    if args.cmd == "list":
        cmd_list(client, cfg, args)
    elif args.cmd == "comments":
        cmd_comments(client, cfg, args)
    elif args.cmd == "insights":
        cmd_insights(client, cfg, args)
    elif args.cmd == "perfil":
        cmd_perfil(client, cfg, args)
    elif args.cmd == "competencia":
        cmd_competencia(client, cfg, args)
    elif args.cmd == "bundle":
        if not args.media_ids and not args.recent:
            sys.exit("da uno o más media_id, o usa --recent N")
        cmd_bundle(client, cfg, args)


if __name__ == "__main__":
    main()
