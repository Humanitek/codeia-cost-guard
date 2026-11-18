"""Tarifas públicas de Cloudflare (plan Workers Paid) y estimación del gasto del mes a partir del consumo.

Es una ESTIMACIÓN: la factura real la calcula Cloudflare (su API de facturación aún no publica importes).
Fuentes: developers.cloudflare.com/workers/platform/pricing, /kv/platform/pricing, /r2/pricing,
/d1/platform/pricing y /workers-ai/platform/pricing (consultadas en noviembre de 2026).

Sin dependencias: solo librería estándar."""
import calendar
import time

CUOTA_BASE_USD = 5.0            # suscripción mensual de Workers Paid
GB = 1e9

# clave -> (producto, concepto, incluido al mes, unidades que cubre el precio, precio en USD, unidad)
TARIFAS = {
    "workers_peticiones": ("Workers", "Peticiones", 10e6, 1e6, 0.30, "n"),
    "workers_cpu_ms": ("Workers", "Tiempo de CPU", 30e6, 1e6, 0.02, "ms"),
    "kv_lecturas": ("KV", "Lecturas", 10e6, 1e6, 0.50, "n"),
    "kv_escrituras": ("KV", "Escrituras", 1e6, 1e6, 5.00, "n"),
    "kv_borrados": ("KV", "Borrados", 1e6, 1e6, 5.00, "n"),
    "kv_listados": ("KV", "Listados", 1e6, 1e6, 5.00, "n"),
    "kv_bytes": ("KV", "Almacenado", 1 * GB, GB, 0.50, "bytes"),
    "r2_clase_a": ("R2", "Operaciones de escritura (clase A)", 1e6, 1e6, 4.50, "n"),
    "r2_clase_b": ("R2", "Operaciones de lectura (clase B)", 10e6, 1e6, 0.36, "n"),
    "r2_bytes": ("R2", "Almacenado", 10 * GB, GB, 0.015, "bytes"),
    "d1_filas_leidas": ("D1", "Filas leídas", 25e9, 1e6, 0.001, "n"),
    "d1_filas_escritas": ("D1", "Filas escritas", 50e6, 1e6, 1.00, "n"),
    "d1_bytes": ("D1", "Almacenado", 5 * GB, GB, 0.75, "bytes"),
}
# Workers AI no tiene cupo mensual: 10.000 neuronas gratis CADA DÍA y, a partir de ahí, 0,011 USD por 1.000
IA_GRATIS_DIA = 10_000
IA_USD_POR_MIL = 0.011
# lo que se acumula durante el mes se proyecta a fin de mes; lo almacenado es una foto y no se proyecta
NO_SE_PROYECTA = ("kv_bytes", "r2_bytes", "d1_bytes")
AVISO_PCT = 80                  # a partir de aquí la línea va en ámbar; con 100 % ya se paga de más


def _coste(usado, incluido, por, precio):
    return max(0.0, usado - incluido) / por * precio


def fraccion_del_mes(ahora=None):
    """Parte del mes natural ya transcurrida (0-1], para proyectar el consumo a fin de mes."""
    t = time.localtime(ahora or time.time())
    dias = calendar.monthrange(t.tm_year, t.tm_mon)[1]
    return max(1 / (dias * 24), ((t.tm_mday - 1) * 24 + t.tm_hour + 1) / (dias * 24))


def _estado(pct, pct_proyectado):
    """Rojo: el cupo ya se pasó (se está pagando de más). Ámbar: va por encima del 80 % o, a este ritmo, se pasará antes de fin de mes."""
    return "rojo" if pct >= 100 else "ambar" if pct >= AVISO_PCT or pct_proyectado >= 100 else "verde"


def estimar(valores, ia_por_dia=None, ahora=None):
    """`valores`: {clave de TARIFAS: consumo del mes}; las claves que falten (producto sin leer) no salen.
    `ia_por_dia`: {fecha: neuronas}. Devuelve las líneas con su % del cupo, el sobrecoste y la proyección a fin de mes."""
    frac = fraccion_del_mes(ahora)
    lineas, extra, extra_proy = [], 0.0, 0.0
    for clave, (producto, concepto, incluido, por, precio, unidad) in TARIFAS.items():
        if valores.get(clave) is None:
            continue
        usado = float(valores[clave])
        proyectado = usado if clave in NO_SE_PROYECTA else usado / frac
        coste, coste_proy = _coste(usado, incluido, por, precio), _coste(proyectado, incluido, por, precio)
        pct = 100.0 * usado / incluido
        lineas.append({"clave": clave, "producto": producto, "concepto": concepto, "unidad": unidad, "usado": usado, "incluido": incluido,
                       "pct": round(pct, 1), "pct_proyectado": round(100.0 * proyectado / incluido, 1),
                       "coste": round(coste, 2), "coste_proyectado": round(coste_proy, 2),
                       "estado": _estado(pct, 100.0 * proyectado / incluido)})
        extra += coste
        extra_proy += coste_proy
    if ia_por_dia is not None:
        total = sum(ia_por_dia.values())
        coste = sum(max(0, n - IA_GRATIS_DIA) for n in ia_por_dia.values()) / 1000 * IA_USD_POR_MIL
        hoy = ia_por_dia.get(time.strftime("%Y-%m-%d", time.localtime(ahora or time.time())), 0)
        pct = 100.0 * hoy / IA_GRATIS_DIA
        lineas.append({"clave": "ia_neuronas", "producto": "Workers AI", "concepto": "Neuronas de hoy (cupo diario)", "unidad": "n", "usado": float(hoy),
                       "incluido": float(IA_GRATIS_DIA), "pct": round(pct, 1), "pct_proyectado": round(pct, 1), "coste": round(coste, 2),
                       "coste_proyectado": round(coste / frac, 2), "estado": _estado(pct, pct), "total_mes": float(total)})
        extra += coste
        extra_proy += coste / frac
    peor = "rojo" if any(x["estado"] == "rojo" for x in lineas) else "ambar" if any(x["estado"] == "ambar" for x in lineas) else "verde"
    return {"lineas": lineas, "base": CUOTA_BASE_USD, "extra": round(extra, 2), "total": round(CUOTA_BASE_USD + extra, 2),
            "extra_proyectado": round(extra_proy, 2), "total_proyectado": round(CUOTA_BASE_USD + extra_proy, 2),
            "estado": peor if lineas else "gris", "fraccion_mes": round(frac, 4)}


# de qué lista de recursos sale cada tarifa: clave -> (producto, lista, campo del nombre, campo del consumo)
RECURSOS = {"workers_peticiones": ("workers", "scripts", "nombre", "peticiones"), "workers_cpu_ms": ("workers", "scripts", "nombre", "cpu_ms"),
            "kv_lecturas": ("kv", "espacios", "id", "lecturas"), "kv_escrituras": ("kv", "espacios", "id", "escrituras"),
            "kv_borrados": ("kv", "espacios", "id", "borrados"), "kv_listados": ("kv", "espacios", "id", "listados"), "kv_bytes": ("kv", "espacios", "id", "bytes"),
            "r2_clase_a": ("r2", "cubos", "nombre", "clase_a"), "r2_clase_b": ("r2", "cubos", "nombre", "clase_b"), "r2_bytes": ("r2", "cubos", "nombre", "bytes"),
            "d1_filas_leidas": ("d1", "bases", "id", "filas_leidas"), "d1_filas_escritas": ("d1", "bases", "id", "filas_escritas"), "d1_bytes": ("d1", "bases", "id", "bytes")}


def sobrecoste_ia(dia_modelo):
    """{modelo: {"coste", "dias", "peor_dia"}}: lo que pasa de las 10.000 neuronas de cada día, repartido entre los modelos de ese día."""
    out = {}
    for fecha, modelos in (dia_modelo or {}).items():
        total = sum(modelos.values())
        if total <= IA_GRATIS_DIA:
            continue
        coste_dia = (total - IA_GRATIS_DIA) / 1000 * IA_USD_POR_MIL
        for modelo, neuronas in modelos.items():
            m = out.setdefault(modelo, {"coste": 0.0, "dias": 0, "peor_dia": fecha, "_peor": 0.0})
            parte = coste_dia * neuronas / total
            m["coste"] += parte
            m["dias"] += 1
            if parte > m["_peor"]:
                m["_peor"], m["peor_dia"] = parte, fecha
    return {k: {"coste": v["coste"], "dias": v["dias"], "peor_dia": v["peor_dia"]} for k, v in out.items()}


def desglose(uso, estimacion):
    """Quién genera el gasto por encima de la cuota del plan: [{producto, concepto, recurso, coste, nota}], de mayor a menor.
    El sobrecoste de cada concepto se reparte entre sus recursos en proporción a lo que consumió cada uno."""
    filas = []
    for linea in estimacion.get("lineas") or []:
        if not linea["coste"] or linea["clave"] not in RECURSOS:
            continue
        producto, lista, nombre, campo = RECURSOS[linea["clave"]]
        recursos = [r for r in (uso.get(producto) or {}).get(lista) or [] if r.get(campo)]
        total = sum(r[campo] for r in recursos)
        for r in recursos:
            filas.append({"producto": linea["producto"], "concepto": linea["concepto"], "recurso": r[nombre],
                          "coste": linea["coste"] * r[campo] / total, "nota": f"{100 * r[campo] / total:.0f} % de lo consumido"})
    for modelo, v in sobrecoste_ia((uso.get("ia") or {}).get("dia_modelo")).items():
        filas.append({"producto": "Workers AI", "concepto": "Neuronas por encima del cupo diario", "recurso": modelo, "coste": v["coste"],
                      "nota": f'{v["dias"]} día{"s" if v["dias"] != 1 else ""} por encima del cupo; el mayor, el {v["peor_dia"]}'})
    return [dict(f, coste=round(f["coste"], 2)) for f in sorted(filas, key=lambda f: -f["coste"]) if f["coste"] >= 0.005]
