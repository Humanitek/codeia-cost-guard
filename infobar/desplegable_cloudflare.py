"""Pestaña Cloudflare del desplegable: gasto estimado del mes, quién genera el gasto extra, los cupos de Workers
y los proyectos que más piden. Solo pinta lo último que guardó cloudflare_uso (sin red ni Llavero): el detalle
completo está en la pestaña Cloudflare del panel."""
import time

from . import cloudflare_uso
from .desplegable_comun import cabecera, esc, pagina, pestanas, pie, tarjeta

BOTONES = [("panel", "Ver detalle")]
MAX_EXTRA, MAX_WORKERS = 4, 5
DETALLE = {"verde": "Dentro de lo incluido", "ambar": "Cerca del cupo", "rojo": "Cupo superado", "gris": "Sin datos todavía"}


def _usd(v):
    return "$" + f"{float(v or 0):.2f}".replace(".", ",")


def _corto(v, unidad="n"):
    v = float(v or 0)
    for tope, sufijo in ((1e9, " B"), (1e6, " M"), (1e3, " K")):
        if v >= tope:
            return f"{v / tope:.1f}".replace(".", ",") + sufijo + (" ms" if unidad == "ms" else "")
    return f"{v:.0f}" + (" ms" if unidad == "ms" else "")


def _fila(texto, valor, estado=None):
    punto = f'<i class="p {esc(estado)}"></i> ' if estado else ""
    return f'<div class="f"><span>{punto}{esc(texto)}</span><span>{esc(valor)}</span></div>'


def cuerpo(d):
    """HTML del contenido para una lectura `d` de cloudflare_uso."""
    e, u = d.get("estimacion"), d.get("uso") or {}
    if not e:
        return ('<div class="aviso" style="background:var(--tarjeta);border-color:var(--borde);margin-top:12px">'
                + esc(d.get("error") or "Todavía sin datos: la primera lectura llega en unos segundos.") + '</div>')
    h = []
    if d.get("error"):
        h.append(f'<div class="aviso">Última lectura fallida: {esc(d["error"])}</div>')
    extra = e.get("extra") or 0
    h.append('<div class="rejilla" style="margin-top:12px">'
             + tarjeta("caja", "Gasto estimado", _usd(e.get("total")), f"$5,00 del plan + {_usd(extra)} extra" if extra else "solo los $5,00 del plan", "ambar" if extra else "verde")
             + tarjeta("pulso", "A fin de mes", _usd(e.get("total_proyectado")), "a este ritmo", "ambar" if e.get("extra_proyectado") else "verde") + '</div>')
    quien = e.get("sobrecoste") or []
    if quien:
        filas = "".join(_fila(f'{str(f["recurso"]).split("/")[-1]} · {f["producto"]}', _usd(f["coste"]), "rojo") for f in quien[:MAX_EXTRA])
        mas = f'<div class="nota" style="padding:4px 0">+{len(quien) - MAX_EXTRA} más</div>' if len(quien) > MAX_EXTRA else ""
        h.append(f'<div class="sec"><span>Quién genera el gasto extra</span><span class="nota">{esc(_usd(extra))}</span></div><div class="lista">{filas}{mas}</div>')
    lineas = {x["clave"]: x for x in e.get("lineas") or []}
    tj = [tarjeta(ic, rotulo, f'{x["pct"]:.0f} %', f'{_corto(x["usado"], x["unidad"])} de {_corto(x["incluido"], x["unidad"])}', x["estado"])
          for clave, ic, rotulo in (("workers_peticiones", "web", "Peticiones"), ("workers_cpu_ms", "cpu", "CPU de Workers")) if (x := lineas.get(clave))]
    ia = lineas.get("ia_neuronas")
    if ia:
        tj.append(tarjeta("cpu", "Workers AI hoy", f'{ia["pct"]:.0f} %', f'{_corto(ia["usado"])} de 10 K neuronas', ia["estado"]))
    cerca = [x for k, x in lineas.items() if k not in ("workers_peticiones", "workers_cpu_ms", "ia_neuronas") and x["estado"] in ("ambar", "rojo")]
    if tj:
        h.append(f'<div class="sec"><span>Cupos del plan</span></div><div class="rejilla">{"".join(tj)}</div>')
    if cerca:
        h.append('<div class="lista" style="margin-top:8px">' + "".join(_fila(f'{x["producto"]} · {x["concepto"]}', f'{x["pct"]:.0f} %', x["estado"]) for x in cerca[:4]) + '</div>')
    scripts = (u.get("workers") or {}).get("scripts") or []
    if scripts:
        filas = "".join(_fila(s["nombre"], f'{_corto(s["peticiones"])} · {_corto(s["cpu_ms"], "ms")}' if s.get("cpu_ms") is not None else _corto(s["peticiones"]))
                        for s in scripts[:MAX_WORKERS])
        mas = f'<div class="nota" style="padding:4px 0">+{len(scripts) - MAX_WORKERS} más en el panel</div>' if len(scripts) > MAX_WORKERS else ""
        h.append(f'<div class="sec"><span>Proyectos</span><span class="nota">peticiones · CPU</span></div><div class="lista">{filas}{mas}</div>')
    return "".join(h)


def documento(oscuro, ahora=None, datos=None):
    """HTML de la pestaña Cloudflare del desplegable."""
    d = cloudflare_uso.en_cache() if datos is None else datos
    estado = (d.get("estimacion") or {}).get("estado") or "gris"
    medido = time.strftime("%H:%M", time.localtime(d["ok_en"])) if d.get("ok_en") else "—"
    return pagina(cabecera("Cloudflare", estado, DETALLE[estado]) + pestanas("cloudflare") + cuerpo(d)
                  + pie(BOTONES, f"Medido a las {medido}"), oscuro)
