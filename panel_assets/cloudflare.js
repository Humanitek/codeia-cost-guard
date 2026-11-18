/* Pestaña Cloudflare: consumo del mes de Workers, KV, R2, D1 y Workers AI frente al cupo de Workers Paid, el gasto ESTIMADO con las
   tarifas públicas (la factura real la calcula Cloudflare), quién genera el gasto extra y el detalle por worker, modelo, cubo, base y espacio.
   Todo se construye con nodos del DOM: los nombres de workers, modelos y cubos vienen de la cuenta. */
(function(){
  const {h, fmt} = window.CG;
  const $ = id => document.getElementById(id);
  const usd = v => "$" + (Number(v) || 0).toFixed(2).replace(".", ",");
  const gb = v => !v ? "0" : v < 1e5 ? (v / 1e3).toFixed(1).replace(".", ",") + " KB" : v < 1e8 ? (v / 1e6).toFixed(1).replace(".", ",") + " MB" : (v / 1e9).toFixed(2).replace(".", ",") + " GB";
  const cantidad = (v, unidad) => unidad === "bytes" ? gb(v) : unidad === "ms" ? fmt(Math.round(v)) + " ms" : fmt(Math.round(v));
  const pct = v => (v >= 10 ? Math.round(v) : (Math.round(v * 10) / 10).toString().replace(".", ",")) + " %";
  const corto = (t, n) => t.length > n ? t.slice(0, n - 1) + "…" : t;
  const PRODUCTO = {workers: "Workers", kv: "KV", r2: "R2", d1: "D1", ia: "Workers AI"};
  const ESTADO = {verde: ["sv-ok", "dentro del cupo"], ambar: ["sv-aviso", "cerca del cupo"], rojo: ["sv-mal", "cupo superado"], gris: ["sv-neutro", "sin dato"]};
  const ORIGEN = {"rest api": "API REST (con un token de API)", "unknown": "Origen no indicado por Cloudflare"};
  let temporizador = null, peticion = 0;

  const nombre = (t, n) => h("span", {class: "sv-nombre", title: t}, corto(t, n || 46));
  const tabla = (cab, filas, nota) => h("div", {class: "sv-tabla"}, h("table", {class: "sv"}, h("thead", {}, h("tr", {}, ...cab.map(t => h("th", {}, t)))), h("tbody", {}, ...filas)),
    nota ? h("p", {class: "ayuda"}, nota) : null);
  const fila = (...celdas) => h("tr", {}, ...celdas.map(c => h("td", {}, c)));
  // barra de reparto: qué parte del total se lleva esta fila
  const parte = (v, total, estado) => { const p = total ? 100 * v / total : 0;
    return h("span", {class: "cf-parte"}, h("span", {class: "prog"}, h("i", {class: estado || "", style: "width:" + Math.min(100, p).toFixed(1) + "%"})), h("span", {}, pct(p))); };

  function gastoExtra(e){
    if (!e.sobrecoste.length) return h("p", {class: "vacio"}, "Nada pasa del cupo incluido: este mes solo pagas los $5,00 de Workers Paid.");
    return tabla(["Quién lo genera", "Producto", "Por qué", "Parte del gasto extra", "Coste"],
      e.sobrecoste.map(f => fila(nombre(f.recurso), f.producto, h("span", {}, f.concepto, h("span", {class: "sv-suave"}, " · " + f.nota)), parte(f.coste, e.extra, "rojo"), usd(f.coste))),
      "El gasto extra de cada concepto se reparte entre sus recursos en proporción a lo que consumió cada uno. Workers AI no dice qué proyecto hizo cada petición: se ve el modelo y el origen.");
  }

  function tablaCupos(e, sv){
    return tabla(["Concepto", "Usado este mes", "", "% del cupo", "Estado", "Sobrecoste"], e.lineas.map(l => {
      const [cl, tx] = ESTADO[l.estado] || ESTADO.gris;
      const barra = h("div", {class: "prog", style: "min-width:90px;margin:0"}, h("i", {class: l.estado === "rojo" ? "rojo" : l.estado === "ambar" ? "ambar" : "", style: "width:" + Math.min(100, l.pct).toFixed(1) + "%"}));
      return fila(h("span", {class: "sv-nombre"}, l.producto + " · " + l.concepto), cantidad(l.usado, l.unidad) + " de " + cantidad(l.incluido, l.unidad), barra, pct(l.pct),
        sv.insignia(cl, l.estado === "ambar" && l.pct < 80 ? "a este ritmo se pasa antes de fin de mes" : tx), l.coste ? usd(l.coste) : "—");
    }), "El cupo es lo que incluye Workers Paid cada mes; solo se paga lo que lo supera. Lo almacenado es una foto de ahora. Workers AI tiene cupo diario (10.000 neuronas al día).");
  }

  // columnas por día: `valor(d)` de cada fecha; `tope` dibuja en rojo los días que lo superan (cupo diario de Workers AI)
  function porDia(dias, valor, unidad, tope){
    const fechas = Object.keys(dias).sort(), max = Math.max(1, ...fechas.map(f => valor(dias[f])));
    if (!fechas.length) return h("p", {class: "vacio"}, "Sin actividad este mes.");
    return h("div", {class: "cf-dias"}, ...fechas.map(f => { const v = valor(dias[f]);
      return h("div", {class: "cf-dia", title: f + ": " + cantidad(v, unidad)}, h("i", {class: tope && v > tope ? "rojo" : "", style: "height:" + Math.max(2, 100 * v / max).toFixed(1) + "%"}), h("span", {}, f.slice(8))); }));
  }

  function tablaWorkers(w){
    if (!w.scripts.length) return h("p", {class: "vacio"}, "Ningún worker ha recibido peticiones este mes.");
    const cpu = w.cpu_ms || 0;
    return tabla(["Proyecto (worker)", "Peticiones", "Parte de las peticiones", "Errores", "CPU total", "Parte de la CPU", "CPU por petición", "Subpeticiones"], w.scripts.map(s =>
      fila(nombre(s.nombre), fmt(s.peticiones), parte(s.peticiones, w.peticiones), s.errores ? fmt(s.errores) + " (" + pct(100 * s.errores / Math.max(1, s.peticiones)) + ")" : "0",
        s.cpu_ms == null ? "—" : fmt(Math.round(s.cpu_ms)) + " ms", s.cpu_ms == null ? "—" : parte(s.cpu_ms, cpu),
        s.cpu_ms == null || !s.peticiones ? "—" : (s.cpu_ms / s.peticiones).toFixed(1).replace(".", ",") + " ms", fmt(s.subpeticiones || 0))));
  }

  function bloquesIA(ia, sv){
    if (!ia.modelos.length) return [];
    return [sv.bloque("Workers AI · modelos", fmt(Math.round(ia.neuronas)) + " neuronas este mes",
      tabla(["Modelo", "Peticiones", "Neuronas", "Parte de las neuronas", "Tokens de entrada", "Tokens de salida", "Gasto extra"], ia.modelos.map(m =>
        fila(nombre(m.modelo.replace(/^@[a-z-]+\//, "")), fmt(m.peticiones), fmt(Math.round(m.neuronas)), parte(m.neuronas, ia.neuronas),
          m.tokens_entrada ? fmt(m.tokens_entrada) : "—", m.tokens_salida ? fmt(m.tokens_salida) : "—", m.sobrecoste ? usd(m.sobrecoste) : "—")),
        "Una neurona es la unidad con la que Cloudflare mide la inferencia. Cada día hay 10.000 gratis; lo que las supera cuesta $0,011 por cada 1.000.")),
      h("div", {class: "rej"},
        h("div", {class: "c7 col-f"}, sv.titulo("Workers AI · neuronas por día", "en rojo, los días que pasan de las 10.000 gratis"), h("div", {class: "tj"}, porDia(ia.por_dia, v => v, "n", 10000))),
        h("div", {class: "c5 col-f"}, sv.titulo("Workers AI · de dónde llegan las peticiones", ""), h("div", {class: "tj"}, ia.origenes.length
          ? tabla(["Origen", "Peticiones", "Neuronas"], ia.origenes.map(o => fila(ORIGEN[o.origen] || o.origen, fmt(o.peticiones), fmt(Math.round(o.neuronas)))))
          : h("p", {class: "vacio"}, "Cloudflare no dio el origen de las peticiones."))))];
  }

  function bloquesAlmacen(u, sv){
    const id = t => nombre(t, 14), out = [];
    if (u.r2 && u.r2.cubos.length) out.push(sv.bloque("R2 · cubos", gb(u.r2.bytes) + " almacenados",
      tabla(["Cubo", "Almacenado", "Parte", "Objetos", "Escrituras (clase A)", "Lecturas (clase B)"], u.r2.cubos.map(c =>
        fila(nombre(c.nombre), gb(c.bytes), parte(c.bytes, u.r2.bytes), fmt(c.objetos), fmt(c.clase_a), fmt(c.clase_b))))));
    if (u.d1 && u.d1.bases.length) out.push(sv.bloque("D1 · bases de datos", fmt(u.d1.filas_leidas) + " filas leídas este mes",
      tabla(["Base (identificador)", "Filas leídas", "Parte de las lecturas", "Filas escritas", "Consultas", "Tamaño"], u.d1.bases.map(b =>
        fila(id(b.id), fmt(b.filas_leidas), parte(b.filas_leidas, u.d1.filas_leidas), fmt(b.filas_escritas), fmt(b.consultas), gb(b.bytes))),
        "Con el permiso de solo lectura de analítica Cloudflare da el identificador de la base, no su nombre.")));
    if (u.kv && u.kv.espacios.length) out.push(sv.bloque("KV · espacios de nombres", gb(u.kv.bytes) + " almacenados",
      tabla(["Espacio (identificador)", "Lecturas", "Escrituras", "Borrados", "Listados", "Claves", "Tamaño"], u.kv.espacios.map(e =>
        fila(id(e.id), fmt(e.lecturas), fmt(e.escrituras), fmt(e.borrados), fmt(e.listados), fmt(e.claves), gb(e.bytes))))));
    return out;
  }

  function mensaje(txt){ $("vista-cloudflare").replaceChildren(h("div", {class: "tj"}, h("p", {class: "vacio"}, txt))); }

  function pinta(d){
    const sv = window.CG.sv;
    if (!d.configurado) return mensaje(d.apagado ? "Cloudflare está apagado en Ajustes." : "Falta el token de Cloudflare: guárdalo en Ajustes → Cloudflare.");
    const e = d.estimacion, u = d.uso || {};
    if (!e) return mensaje(d.error || "Todavía sin datos de Cloudflare.");
    const linea = k => e.lineas.find(l => l.clave === k);
    const tj = (k, ic, rot) => { const l = linea(k); return l ? sv.tarjeta(ic, rot, pct(l.pct), cantidad(l.usado, l.unidad) + " de " + cantidad(l.incluido, l.unidad) + " incluidas", l.estado, l.pct) : null; };
    const [cl, tx] = ESTADO[e.estado] || ESTADO.gris;
    const edad = d.ok_en ? "leído a las " + new Date(d.ok_en * 1000).toLocaleTimeString("es-ES", {hour: "2-digit", minute: "2-digit"}) : "";
    const cabecera = h("div", {class: "filtros"}, h("div", {class: "grupo"}, h("span", {class: "etq"}, "Mes en curso"), h("span", {class: "sv-suave"}, "desde el " + (d.desde || "día 1"))),
      h("button", {class: "vidrio", onclick: () => carga(true)}, "Actualizar"),
      h("p", {class: "sv-estado", style: "margin:0 0 0 auto"}, sv.insignia(cl, tx), " ", h("span", {class: "sv-suave"}, edad + (d.error ? " · última lectura fallida: " + d.error : ""))));
    const fallos = Object.entries(d.errores || {}).map(([p, m]) => h("p", {class: "ayuda"}, (PRODUCTO[p] || p) + " no disponible: " + m));
    $("vista-cloudflare").replaceChildren(...[cabecera,
      h("div", {class: "rej"},
        sv.tarjeta("moneda", "Gasto estimado del mes", usd(e.total), "$5,00 de Workers Paid" + (e.extra ? " + " + usd(e.extra) + " de gasto extra" : " · sin gasto extra"), e.extra ? "ambar" : "verde"),
        sv.tarjeta("cal", "A fin de mes, a este ritmo", usd(e.total_proyectado), e.extra_proyectado ? usd(e.extra_proyectado) + " de gasto extra previsto" : "dentro de lo incluido", e.extra_proyectado ? "ambar" : "verde"),
        tj("workers_peticiones", "web", "Peticiones a Workers"), tj("workers_cpu_ms", "cpu", "Tiempo de CPU")),
      sv.bloque("Quién genera el gasto extra", e.extra ? usd(e.extra) + " por encima de los $5,00 del plan" : "sobre los $5,00 del plan", gastoExtra(e)),
      sv.bloque("Cupos del plan", "estimación con tarifas públicas", tablaCupos(e, sv), ...fallos),
      u.workers ? sv.bloque("Workers · proyectos", fmt(u.workers.peticiones) + " peticiones este mes", tablaWorkers(u.workers)) : null,
      u.workers ? h("div", {class: "rej"},
        h("div", {class: "c6 col-f"}, sv.titulo("Workers · peticiones por día", ""), h("div", {class: "tj"}, porDia(u.workers.por_dia, v => v.peticiones, "n"))),
        h("div", {class: "c6 col-f"}, sv.titulo("Workers · CPU por día", ""), h("div", {class: "tj"}, porDia(u.workers.por_dia, v => v.cpu_ms, "ms")))) : null,
      ...(u.ia ? bloquesIA(u.ia, sv) : []), ...bloquesAlmacen(u, sv)].filter(Boolean));
  }

  function carga(forzar){
    const mio = ++peticion;
    fetch("/cloudflare" + (forzar ? "?fresco=1" : "")).then(r => { if (r.status === 401) throw new Error("sesion"); if (!r.ok) throw new Error("http"); return r.json(); })
      .then(d => { if (mio === peticion) pinta(d); })
      .catch(e => { if (mio === peticion) mensaje(e.message === "sesion" ? "La sesión ha caducado: abre el panel desde el icono de la barra de menús." : "No se pudo leer Cloudflare ahora; vuelve a intentarlo."); });
  }

  window.cargarCloudflare = function(){
    if (!$("vista-cloudflare").children.length) mensaje("Cargando…");
    carga();
    clearInterval(temporizador);
    temporizador = setInterval(() => { if (!$("vista-cloudflare").hidden && document.visibilityState === "visible") carga(); else if ($("vista-cloudflare").hidden) clearInterval(temporizador); }, 120000);
  };
  if (location.protocol !== "file:" && location.hash === "#cloudflare") window.vista("cloudflare");
})();
