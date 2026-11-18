"""Lectores del consumo del mes de cada producto de Cloudflare, con su detalle: por worker, por modelo de IA,
por cubo de R2, por base de D1 y por espacio de KV. Cada lector devuelve un dict y falla por separado (Fallo).

Los campos están comprobados contra el esquema de la API de analítica (noviembre de 2026)."""
from .cloudflare_api import Fallo, dim, grupos, n

# operaciones de R2 por clase de cobro (developers.cloudflare.com/r2/pricing); lo que no esté aquí cuenta como lectura
R2_CLASE_A = {"ListBuckets", "PutBucket", "ListObjects", "PutObject", "CopyObject", "CompleteMultipartUpload", "CreateMultipartUpload",
              "LifecycleStorageTierTransition", "ListMultipartUploads", "UploadPart", "UploadPartCopy", "ListParts", "PutBucketEncryption",
              "PutBucketCors", "PutBucketLifecycleConfiguration"}
R2_GRATIS = {"DeleteObject", "DeleteBucket", "AbortMultipartUpload"}
MAX_FILAS = 50


def _acumula(tabla, clave, **valores):
    fila = tabla.setdefault(clave, {})
    for k, v in valores.items():
        fila[k] = fila.get(k, 0) + v


def _lista(tabla, nombre, orden):
    return sorted(({nombre: k, **v} for k, v in tabla.items()), key=lambda f: -f.get(orden, 0))[:MAX_FILAS]


def _ultimos(filas, dimension, campos):
    """{recurso: {campo: valor más reciente}}: las filas de almacenamiento llegan una por día."""
    ultimo = {}
    for x in filas:
        k, fecha = dim(x, dimension), dim(x, "date") or dim(x, "datetime")
        if k not in ultimo or fecha > ultimo[k][0]:
            ultimo[k] = (fecha, {c: n(x, "max", c) for c in campos})
    return {k: v for k, (_, v) in ultimo.items()}


def workers(token, cuenta, t0, t1, d0, d1):
    f = f'datetime_geq:"{t0}",datetime_leq:"{t1}"'
    try:        # el tiempo de CPU sumado es lo que se cobra; si la cuenta no publica ese campo, salen al menos las peticiones
        filas, con_cpu = grupos(token, cuenta, "workersInvocationsAdaptive", f, "sum{requests errors subrequests cpuTimeUs} dimensions{scriptName date}"), True
    except Fallo:
        filas, con_cpu = grupos(token, cuenta, "workersInvocationsAdaptive", f, "sum{requests errors subrequests} dimensions{scriptName date}"), False
    por_script, por_dia = {}, {}
    for x in filas:
        v = {"peticiones": n(x, "sum", "requests"), "errores": n(x, "sum", "errors"), "subpeticiones": n(x, "sum", "subrequests"),
             "cpu_ms": n(x, "sum", "cpuTimeUs") / 1000 if con_cpu else 0}
        _acumula(por_script, dim(x, "scriptName") or "?", **v)
        _acumula(por_dia, dim(x, "date"), peticiones=v["peticiones"], cpu_ms=v["cpu_ms"])
    scripts = _lista(por_script, "nombre", "peticiones")
    if not con_cpu:
        for s in scripts:
            s["cpu_ms"] = None
    return {"peticiones": sum(s["peticiones"] for s in por_script.values()), "errores": sum(s["errores"] for s in por_script.values()),
            "cpu_ms": sum(s["cpu_ms"] for s in por_script.values()) if con_cpu else None, "scripts": scripts, "por_dia": por_dia}


def kv(token, cuenta, t0, t1, d0, d1):
    f = f'date_geq:"{d0}",date_leq:"{d1}"'
    accion = {"read": "lecturas", "write": "escrituras", "delete": "borrados", "list": "listados"}
    espacios = {}
    for x in grupos(token, cuenta, "kvOperationsAdaptiveGroups", f, "sum{requests} dimensions{actionType namespaceId}"):
        if dim(x, "actionType") in accion:
            _acumula(espacios, dim(x, "namespaceId"), **{accion[dim(x, "actionType")]: n(x, "sum", "requests")})
    for k, v in _ultimos(grupos(token, cuenta, "kvStorageAdaptiveGroups", f, "max{byteCount keyCount} dimensions{namespaceId date}"),
                         "namespaceId", ("byteCount", "keyCount")).items():
        espacios.setdefault(k, {}).update(bytes=v["byteCount"], claves=v["keyCount"])
    for e in espacios.values():
        for c in (*accion.values(), "bytes", "claves"):
            e.setdefault(c, 0)
    return {**{c: sum(e[c] for e in espacios.values()) for c in (*accion.values(), "bytes")}, "espacios": _lista(espacios, "id", "lecturas")}


def r2(token, cuenta, t0, t1, d0, d1):
    f = f'datetime_geq:"{t0}",datetime_leq:"{t1}"'
    cubos = {}
    for x in grupos(token, cuenta, "r2OperationsAdaptiveGroups", f, "sum{requests} dimensions{actionType bucketName}"):
        op = dim(x, "actionType")
        if op not in R2_GRATIS:
            _acumula(cubos, dim(x, "bucketName"), **{"clase_a" if op in R2_CLASE_A else "clase_b": n(x, "sum", "requests")})
    for k, v in _ultimos(grupos(token, cuenta, "r2StorageAdaptiveGroups", f, "max{payloadSize metadataSize objectCount} dimensions{bucketName datetime}"),
                         "bucketName", ("payloadSize", "metadataSize", "objectCount")).items():
        cubos.setdefault(k, {}).update(bytes=v["payloadSize"] + v["metadataSize"], objetos=v["objectCount"])
    for c in cubos.values():
        for campo in ("clase_a", "clase_b", "bytes", "objetos"):
            c.setdefault(campo, 0)
    return {**{c: sum(x[c] for x in cubos.values()) for c in ("clase_a", "clase_b", "bytes")}, "cubos": _lista(cubos, "nombre", "bytes")}


def d1(token, cuenta, t0, t1, d0, d1_):
    f = f'date_geq:"{d0}",date_leq:"{d1_}"'
    bases = {}
    for x in grupos(token, cuenta, "d1AnalyticsAdaptiveGroups", f, "sum{rowsRead rowsWritten readQueries writeQueries} dimensions{databaseId}"):
        _acumula(bases, dim(x, "databaseId"), filas_leidas=n(x, "sum", "rowsRead"), filas_escritas=n(x, "sum", "rowsWritten"),
                 consultas=n(x, "sum", "readQueries") + n(x, "sum", "writeQueries"))
    for k, v in _ultimos(grupos(token, cuenta, "d1StorageAdaptiveGroups", f, "max{databaseSizeBytes} dimensions{databaseId date}"),
                         "databaseId", ("databaseSizeBytes",)).items():
        bases.setdefault(k, {}).update(bytes=v["databaseSizeBytes"])
    for b in bases.values():
        for campo in ("filas_leidas", "filas_escritas", "consultas", "bytes"):
            b.setdefault(campo, 0)
    return {**{c: sum(b[c] for b in bases.values()) for c in ("filas_leidas", "filas_escritas", "bytes")}, "bases": _lista(bases, "id", "filas_leidas")}


def ia(token, cuenta, t0, t1, d0, d1):
    f = f'date_geq:"{d0}",date_leq:"{d1}"'
    modelos, por_dia, dia_modelo = {}, {}, {}
    for x in grupos(token, cuenta, "aiInferenceAdaptiveGroups", f, "count sum{totalNeurons totalInputTokens totalOutputTokens} dimensions{date modelId}"):
        neuronas, modelo, fecha = n(x, "sum", "totalNeurons"), dim(x, "modelId") or "?", dim(x, "date")
        _acumula(modelos, modelo, neuronas=neuronas, peticiones=x.get("count") or 0, tokens_entrada=n(x, "sum", "totalInputTokens"),
                 tokens_salida=n(x, "sum", "totalOutputTokens"))
        por_dia[fecha] = por_dia.get(fecha, 0) + neuronas
        dia_modelo.setdefault(fecha, {})[modelo] = dia_modelo.get(fecha, {}).get(modelo, 0) + neuronas
    origenes = {}
    try:        # de dónde llegan las peticiones (un Worker con binding o la API REST con un token): si no se puede leer, se omite
        for x in grupos(token, cuenta, "aiInferenceAdaptiveGroups", f, "count sum{totalNeurons} dimensions{requestSource}"):
            _acumula(origenes, dim(x, "requestSource") or "unknown", neuronas=n(x, "sum", "totalNeurons"), peticiones=x.get("count") or 0)
    except Fallo:
        pass
    return {"neuronas": sum(por_dia.values()), "por_dia": por_dia, "dia_modelo": dia_modelo,
            "modelos": _lista(modelos, "modelo", "neuronas"), "origenes": _lista(origenes, "origen", "neuronas")}


PRODUCTOS = (("workers", workers), ("kv", kv), ("r2", r2), ("d1", d1), ("ia", ia))
