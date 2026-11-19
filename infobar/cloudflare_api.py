"""Peticiones a la API de Cloudflare (SOLO lectura): REST y analítica GraphQL. Los fallos salen con un texto
que se puede enseñar tal cual y que nunca lleva el token."""
import json, re, urllib.error, urllib.request

from .certificados import contexto_ssl

API = "https://api.cloudflare.com/client/v4"
ID_CUENTA = re.compile(r"[0-9a-f]{32}")


class Fallo(Exception):
    """Un fallo con un texto que se puede enseñar tal cual (nunca lleva el token)."""


def _pide(token, ruta, cuerpo=None):
    req = urllib.request.Request(API + ruta, data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "Accept": "application/json", "User-Agent": "CostBar/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=contexto_ssl()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise Fallo("Cloudflare rechaza el token (caducado, borrado o sin permiso)" if e.code in (401, 403) else f"Cloudflare respondió {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Fallo(f"no se pudo hablar con Cloudflare ({type(e).__name__})")


def cuenta_del_token(token):
    """Si en Ajustes no se indicó la cuenta y el token deja listar cuentas y solo ve una, es esa.
    Un token con solo «Account Analytics: Read» no puede listarlas: entonces hace falta el ID en Ajustes."""
    filas = [f for f in (_pide(token, "/accounts?per_page=50").get("result") or []) if isinstance(f, dict) and ID_CUENTA.fullmatch(str(f.get("id") or ""))]
    if len(filas) == 1:
        return filas[0]["id"]
    raise Fallo("el token ve varias cuentas: indica el ID de cuenta en Ajustes" if filas
                else "falta el ID de cuenta en Ajustes (este token no puede averiguarlo solo)")


def grupos(token, cuenta, conjunto, filtro, campos):
    """Filas de un conjunto de datos de la cuenta. Los valores van escritos en la consulta: son nuestros (id validado y fechas propias)."""
    q = f'{{viewer{{accounts(filter:{{accountTag:"{cuenta}"}}){{{conjunto}(limit:10000,filter:{{{filtro}}}){{{campos}}}}}}}}}'
    r = _pide(token, "/graphql", {"query": q})
    if r.get("errors"):
        raise Fallo("Cloudflare no dio este dato: " + str((r["errors"][0] or {}).get("message") or "error")[:140])
    cuentas = ((r.get("data") or {}).get("viewer") or {}).get("accounts") or []
    return (cuentas[0].get(conjunto) or []) if cuentas else []


def n(fila, grupo, campo):
    v = (fila.get(grupo) or {}).get(campo)
    return v if isinstance(v, (int, float)) else 0


def dim(fila, campo, tope=80):
    return str((fila.get("dimensions") or {}).get(campo) or "")[:tope]
