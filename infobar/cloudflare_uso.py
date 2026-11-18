"""Consumo del mes en Cloudflare (Workers, KV, R2, D1 y Workers AI), SOLO lectura, con cache en disco.

Los datos salen de la API de analítica (GraphQL) con un token de solo lectura guardado en el Llavero
(cuenta "cloudflare"). Cada producto se pide por separado: si uno falla (permiso que falta, producto
sin usar) los demás siguen saliendo. El gasto se estima con las tarifas públicas (cloudflare_tarifas).
"""
import json, os, time

from . import claves, rutas
from .cloudflare_api import ID_CUENTA, Fallo, cuenta_del_token
from .cloudflare_productos import PRODUCTOS
from .cloudflare_tarifas import desglose, estimar, sobrecoste_ia
from .config_y_estado import cfg, log

CUENTA_LLAVERO = "cloudflare"
TTL = 600                   # la analítica de Cloudflare llega con minutos de retraso: cada 10 min sobra
REINTENTO = 120             # tras un fallo general (token, red) no se insiste en cada refresco
# de cada producto leído, qué campo alimenta qué tarifa
A_TARIFA = {"workers": {"peticiones": "workers_peticiones", "cpu_ms": "workers_cpu_ms"},
            "kv": {"lecturas": "kv_lecturas", "escrituras": "kv_escrituras", "borrados": "kv_borrados", "listados": "kv_listados", "bytes": "kv_bytes"},
            "r2": {"clase_a": "r2_clase_a", "clase_b": "r2_clase_b", "bytes": "r2_bytes"},
            "d1": {"filas_leidas": "d1_filas_leidas", "filas_escritas": "d1_filas_escritas", "bytes": "d1_bytes"}}


def config():
    """(activo, id de cuenta) según config.json: {"cloudflare": {"activo": bool, "cuenta": "<32 hex>"}}."""
    c = cfg().get("cloudflare")
    c = c if isinstance(c, dict) else {}
    cuenta = str(c.get("cuenta") or "").strip().lower()
    return c.get("activo") is not False, (cuenta if ID_CUENTA.fullmatch(cuenta) else "")


def _consulta(token, cuenta, ahora):
    t = time.gmtime(ahora)
    d0, d1 = time.strftime("%Y-%m-01", t), time.strftime("%Y-%m-%d", t)
    t0, t1 = d0 + "T00:00:00Z", time.strftime("%Y-%m-%dT%H:%M:%SZ", t)
    uso, errores = {}, {}
    for nombre, lector in PRODUCTOS:
        try:
            uso[nombre] = lector(token, cuenta, t0, t1, d0, d1)
        except Fallo as e:
            errores[nombre] = str(e)
    if not uso:                 # ni un producto: es el token o la red, no un permiso suelto
        raise Fallo(next(iter(errores.values())))
    valores = {tarifa: uso[p][campo] for p, mapa in A_TARIFA.items() if p in uso for campo, tarifa in mapa.items()}
    est = estimar(valores, (uso.get("ia") or {}).get("por_dia"), ahora)
    est["sobrecoste"] = desglose(uso, est)
    if "ia" in uso:             # cada modelo con lo que cuesta de más; el cruce día×modelo ya no hace falta fuera
        extra = sobrecoste_ia(uso["ia"].pop("dia_modelo", None))
        for m in uso["ia"]["modelos"]:
            m["sobrecoste"] = round((extra.get(m["modelo"]) or {}).get("coste", 0.0), 2)
    return {"uso": uso, "errores": errores, "estimacion": est, "desde": d0, "hasta_dia": d1}


def _cache():
    try:
        with open(rutas.CLOUDFLARE_CACHE, encoding="utf-8") as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except Exception:
        return {}


def invalidar():
    try:
        os.remove(rutas.CLOUDFLARE_CACHE)
    except OSError:
        pass


def en_cache():
    """Lo último leído, sin red ni Llavero (para pintar el desplegable): {} si aún no hay nada."""
    activo, _ = config()
    return _cache() if activo else {}


def leer(ahora=None):
    """Consumo y gasto estimado del mes: {"configurado", "ok_en", "error", "mes", "uso", "errores", "estimacion"}.

    Con la cache fresca no toca ni la red ni el Llavero. Si la lectura falla se conserva la última buena y se anota el error."""
    ahora = ahora or time.time()
    activo, cuenta = config()
    if not activo:
        return {"configurado": False, "apagado": True}
    cache = _cache()
    mes = time.strftime("%Y-%m", time.gmtime(ahora))
    if cache.get("cuenta_cfg") == cuenta and ahora < (cache.get("hasta") or 0):
        return cache
    token = claves.leer_clave(CUENTA_LLAVERO)
    if not token:
        nuevo = {"configurado": False, "cuenta_cfg": cuenta, "hasta": ahora + TTL}      # guardar el token invalida esta cache
    else:
        previo = cache if cache.get("mes") == mes and cache.get("uso") else {}
        try:
            real = cuenta or cache.get("cuenta") or cuenta_del_token(token)
            nuevo = dict(_consulta(token, real, ahora), configurado=True, cuenta=real, cuenta_cfg=cuenta, mes=mes, ok_en=ahora, error=None, hasta=ahora + TTL)
        except Fallo as e:
            log(f"cloudflare: {e}")
            nuevo = dict(previo, configurado=True, cuenta_cfg=cuenta, mes=mes, error=str(e), hasta=ahora + REINTENTO)
    try:
        os.makedirs(os.path.dirname(rutas.CLOUDFLARE_CACHE), exist_ok=True)
        tmp = f"{rutas.CLOUDFLARE_CACHE}.{os.getpid()}.tmp"        # atómico: el panel puede leerla a la vez
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(nuevo, f)
        os.replace(tmp, rutas.CLOUDFLARE_CACHE)
    except Exception:
        pass
    return nuevo
