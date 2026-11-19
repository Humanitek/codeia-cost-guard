"""Cloudflare: estimación del gasto con las tarifas públicas, lectura por producto (cada uno falla por separado),
ajustes y el bloque del desplegable. Sin red: las respuestas de la API van simuladas.

Arrancar con:  python3 -m unittest discover tests
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aislamiento  # noqa: E402,F401  (HOME y rutas temporales: antes que costbar)
from infobar import ajustes, claves, cloudflare_api, cloudflare_tarifas, cloudflare_uso, desplegable_cloudflare, rutas  # noqa: E402

FIN_DE_MES = time.mktime((2026, 11, 30, 23, 0, 0, 0, 0, -1))
CUENTA = "a" * 32
# filas que devuelve cada conjunto de datos de la analítica
DATOS = {
    "workersInvocationsAdaptive": [{"sum": {"requests": 9_000_000, "errors": 90, "subrequests": 5, "cpuTimeUs": 63_000_000_000}, "dimensions": {"scriptName": "api", "date": "2026-11-29"}},
                                   {"sum": {"requests": 4_000_000, "errors": 0, "subrequests": 0, "cpuTimeUs": 22_000_000_000}, "dimensions": {"scriptName": "web", "date": "2026-11-29"}},
                                   {"sum": {"requests": 2_000_000, "errors": 0, "subrequests": 0, "cpuTimeUs": 20_000_000_000}, "dimensions": {"scriptName": "web", "date": "2026-11-30"}}],
    "kvOperationsAdaptiveGroups": [{"sum": {"requests": 2_000_000}, "dimensions": {"actionType": "read", "namespaceId": "n1"}},
                                   {"sum": {"requests": 1_200_000}, "dimensions": {"actionType": "write", "namespaceId": "n1"}},
                                   {"sum": {"requests": 300_000}, "dimensions": {"actionType": "write", "namespaceId": "n2"}}],
    "kvStorageAdaptiveGroups": [{"max": {"byteCount": 100, "keyCount": 1}, "dimensions": {"namespaceId": "n1", "date": "2026-11-01"}},
                                {"max": {"byteCount": 300, "keyCount": 3}, "dimensions": {"namespaceId": "n1", "date": "2026-11-02"}},
                                {"max": {"byteCount": 50, "keyCount": 2}, "dimensions": {"namespaceId": "n2", "date": "2026-11-02"}}],
    "r2OperationsAdaptiveGroups": [{"sum": {"requests": 10}, "dimensions": {"actionType": "PutObject", "bucketName": "b"}},
                                   {"sum": {"requests": 40}, "dimensions": {"actionType": "GetObject", "bucketName": "b"}},
                                   {"sum": {"requests": 99}, "dimensions": {"actionType": "DeleteObject", "bucketName": "b"}}],
    "r2StorageAdaptiveGroups": [{"max": {"payloadSize": 2_000_000_000, "metadataSize": 1000, "objectCount": 7}, "dimensions": {"bucketName": "b", "datetime": "2026-11-02T00:00:00Z"}}],
    "d1AnalyticsAdaptiveGroups": [{"sum": {"rowsRead": 1000, "rowsWritten": 20, "readQueries": 5, "writeQueries": 1}, "dimensions": {"databaseId": "d"}}],
    "d1StorageAdaptiveGroups": [{"max": {"databaseSizeBytes": 4096}, "dimensions": {"databaseId": "d", "date": "2026-11-02"}}],
}
# Workers AI: el día 29 se pasan las 10.000 neuronas gratis (30.000: 20.000 de más = 0,22 $), casi todo por un modelo de imagen
IA = {"date modelId": [{"count": 4, "sum": {"totalNeurons": 27_000, "totalInputTokens": 0, "totalOutputTokens": 0}, "dimensions": {"date": "2026-11-29", "modelId": "@cf/imagen"}},
                       {"count": 9, "sum": {"totalNeurons": 3_000, "totalInputTokens": 500, "totalOutputTokens": 90}, "dimensions": {"date": "2026-11-29", "modelId": "@cf/texto"}},
                       {"count": 2, "sum": {"totalNeurons": 5_000, "totalInputTokens": 100, "totalOutputTokens": 10}, "dimensions": {"date": "2026-11-30", "modelId": "@cf/texto"}}],
      "requestSource": [{"count": 4, "sum": {"totalNeurons": 27_000}, "dimensions": {"requestSource": "rest api"}},
                        {"count": 11, "sum": {"totalNeurons": 8_000}, "dimensions": {"requestSource": "unknown"}}]}


def api(falla=()):
    """Sustituto de cloudflare_api._pide: responde cada conjunto con DATOS e IA; los de `falla` dan error de GraphQL."""
    def pide(token, ruta, cuerpo=None):
        if ruta.startswith("/accounts"):
            return {"result": [{"id": CUENTA, "name": "mía"}]}
        q = cuerpo["query"]
        conjunto = next((k for k in (*DATOS, "aiInferenceAdaptiveGroups") if k + "(" in q), None)
        if conjunto is None or conjunto in falla:
            return {"data": None, "errors": [{"message": "unknown field"}]}
        filas = DATOS[conjunto] if conjunto in DATOS else IA["requestSource" if "requestSource" in q else "date modelId"]
        return {"data": {"viewer": {"accounts": [{conjunto: filas}]}}}
    return pide


class Tarifas(unittest.TestCase):
    def test_coincide_con_el_ejemplo_de_la_documentacion(self):
        # 15 M de peticiones a 7 ms de CPU cada una: 1,50 $ de peticiones + 1,50 $ de CPU sobre los 5 $ del plan
        e = cloudflare_tarifas.estimar({"workers_peticiones": 15e6, "workers_cpu_ms": 105e6}, ahora=FIN_DE_MES)
        self.assertEqual((e["extra"], e["total"], e["estado"]), (3.0, 8.0, "rojo"))

    def test_dentro_del_cupo_no_cuesta_y_avisa_si_el_ritmo_lo_pasara(self):
        mitad = time.mktime((2026, 11, 15, 23, 0, 0, 0, 0, -1))
        e = cloudflare_tarifas.estimar({"workers_peticiones": 6e6, "kv_bytes": 0.5e9}, ahora=mitad)
        peticiones, kv = e["lineas"]
        self.assertEqual((e["extra"], peticiones["pct"]), (0.0, 60.0))
        self.assertEqual(peticiones["estado"], "ambar")             # 6 M a mitad de mes: acabará en 12 M, por encima de los 10 M
        self.assertGreater(e["extra_proyectado"], 0)
        self.assertEqual((kv["estado"], kv["pct_proyectado"]), ("verde", 50.0))      # lo almacenado no se proyecta

    def test_workers_ai_tiene_cupo_diario(self):
        e = cloudflare_tarifas.estimar({}, {"2026-11-29": 30_000, "2026-11-30": 5_000}, ahora=FIN_DE_MES)
        self.assertEqual(e["extra"], 0.22)                          # solo las 20.000 neuronas que pasan de las 10.000 del día 29
        self.assertEqual(e["lineas"][0]["pct"], 50.0)


class Lectura(unittest.TestCase):
    def setUp(self):
        cloudflare_uso.invalidar()
        self.addCleanup(cloudflare_uso.invalidar)
        for p in (mock.patch.object(claves, "leer_clave", return_value="token-de-prueba"), mock.patch.object(cloudflare_uso, "cfg", return_value={})):
            p.start()
            self.addCleanup(p.stop)

    def test_lee_cada_producto_y_estima_el_gasto(self):
        with mock.patch.object(cloudflare_api, "_pide", api(falla=("aiInferenceAdaptiveGroups",))):
            d = cloudflare_uso.leer(FIN_DE_MES)
        self.assertTrue(d["configurado"])
        u = d["uso"]
        self.assertEqual((u["workers"]["peticiones"], u["workers"]["cpu_ms"]), (15_000_000, 105_000_000))
        self.assertEqual({k: v for k, v in u["kv"].items() if k != "espacios"}, {"lecturas": 2_000_000, "escrituras": 1_500_000, "borrados": 0, "listados": 0, "bytes": 350})
        self.assertEqual({k: v for k, v in u["r2"].items() if k != "cubos"}, {"clase_a": 10, "clase_b": 40, "bytes": 2_000_001_000})      # borrar es gratis en R2
        self.assertEqual({k: v for k, v in u["d1"].items() if k != "bases"}, {"filas_leidas": 1000, "filas_escritas": 20, "bytes": 4096})
        self.assertEqual(list(d["errores"]), ["ia"])                # Workers AI no respondió: el resto sale igual
        self.assertEqual(d["estimacion"]["total"], 10.5)            # 5 + 1,50 + 1,50 de Workers + 2,50 de escrituras de KV
        self.assertNotIn("token-de-prueba", str(d))

    def test_el_detalle_dice_que_worker_cubo_base_y_espacio_consume(self):
        with mock.patch.object(cloudflare_api, "_pide", api()):
            u = cloudflare_uso.leer(FIN_DE_MES)["uso"]
        self.assertEqual([(s["nombre"], s["peticiones"], s["cpu_ms"]) for s in u["workers"]["scripts"]], [("api", 9_000_000, 63_000_000), ("web", 6_000_000, 42_000_000)])
        self.assertEqual(u["workers"]["por_dia"]["2026-11-29"], {"peticiones": 13_000_000, "cpu_ms": 85_000_000})
        self.assertEqual(u["kv"]["espacios"][0], {"id": "n1", "lecturas": 2_000_000, "escrituras": 1_200_000, "bytes": 300, "claves": 3, "borrados": 0, "listados": 0})
        self.assertEqual(u["r2"]["cubos"], [{"nombre": "b", "clase_a": 10, "clase_b": 40, "bytes": 2_000_001_000, "objetos": 7}])
        self.assertEqual(u["d1"]["bases"], [{"id": "d", "filas_leidas": 1000, "filas_escritas": 20, "consultas": 6, "bytes": 4096}])
        self.assertEqual([(m["modelo"], m["neuronas"], m["peticiones"], m["sobrecoste"]) for m in u["ia"]["modelos"]], [("@cf/imagen", 27_000, 4, 0.2), ("@cf/texto", 8_000, 11, 0.02)])
        self.assertEqual(u["ia"]["origenes"][0], {"origen": "rest api", "neuronas": 27_000, "peticiones": 4})
        self.assertNotIn("dia_modelo", u["ia"])

    def test_el_gasto_extra_se_reparte_entre_quien_lo_genera(self):
        with mock.patch.object(cloudflare_api, "_pide", api()):
            e = cloudflare_uso.leer(FIN_DE_MES)["estimacion"]
        reparto = {(f["concepto"], f["recurso"]): f["coste"] for f in e["sobrecoste"]}
        self.assertEqual(reparto[("Peticiones", "api")], 0.9)                       # 9 de los 15 M de peticiones: 60 % de 1,50 $
        self.assertEqual(reparto[("Peticiones", "web")], 0.6)
        self.assertEqual(reparto[("Escrituras", "n1")], 2.0)                        # 1,2 de 1,5 M de escrituras: 80 % de 2,50 $
        self.assertEqual(reparto[("Neuronas por encima del cupo diario", "@cf/imagen")], 0.2)
        self.assertEqual(e["sobrecoste"][0]["recurso"], "n1")                       # de mayor a menor
        self.assertAlmostEqual(sum(reparto.values()), e["extra"], delta=0.03)

    def test_el_reparto_usa_el_total_completo_aunque_el_detalle_venga_recortado(self):
        # la lista del detalle se recorta a 50 filas: el porcentaje se mide sobre TODO el consumo del mes
        uso = {"workers": {"scripts": [{"nombre": "api", "peticiones": 9e6}]}}
        e = cloudflare_tarifas.estimar({"workers_peticiones": 15e6}, ahora=FIN_DE_MES)
        reparto = cloudflare_tarifas.desglose(uso, e)
        self.assertEqual(reparto[0]["nota"], "60 % de lo consumido")              # 9 de 15 M, no 100 % de 9 M
        self.assertEqual(reparto[0]["coste"], 0.9)                                # 60 % de 1,50 $

    def test_sin_id_de_cuenta_el_fallo_dice_que_falta_el_id(self):
        # token de solo analitica sin ID en Ajustes: Cloudflare contesta 403 al listar cuentas
        for codigo, esperado in ((403, "falta el ID de cuenta en Ajustes"), (401, "Cloudflare rechaza el token")):
            with mock.patch.object(cloudflare_api, "_pide", side_effect=cloudflare_api.Fallo("Cloudflare rechaza el token (caducado, borrado o sin permiso)", codigo)):
                with self.assertRaises(cloudflare_api.Fallo) as fallo:
                    cloudflare_api.cuenta_del_token("token-de-prueba")
            self.assertIn(esperado, str(fallo.exception))

    def test_la_cache_evita_la_red_y_un_fallo_conserva_lo_ultimo(self):
        with mock.patch.object(cloudflare_api, "_pide", api()):
            cloudflare_uso.leer(FIN_DE_MES)
        with mock.patch.object(cloudflare_api, "_pide", side_effect=AssertionError("no deberia llamar")):
            self.assertEqual(cloudflare_uso.leer(FIN_DE_MES + 60)["estimacion"]["total"], 10.72)
        with mock.patch.object(cloudflare_api, "_pide", side_effect=cloudflare_api.Fallo("Cloudflare rechaza el token")):
            d = cloudflare_uso.leer(FIN_DE_MES + 3000)
        self.assertEqual((d["error"], d["estimacion"]["total"]), ("Cloudflare rechaza el token", 10.72))

    def test_sin_cpu_sumada_salen_las_peticiones(self):
        def sin_cpu(token, ruta, cuerpo=None):
            if cuerpo and "cpuTimeUs" in cuerpo["query"]:
                return {"errors": [{"message": "unknown field cpuTimeUs"}]}
            return api()(token, ruta, cuerpo)
        with mock.patch.object(cloudflare_api, "_pide", sin_cpu):
            d = cloudflare_uso.leer(FIN_DE_MES)
        self.assertEqual((d["uso"]["workers"]["peticiones"], d["uso"]["workers"]["cpu_ms"]), (15_000_000, None))
        self.assertNotIn("workers_cpu_ms", [x["clave"] for x in d["estimacion"]["lineas"]])

    def test_sin_token_o_apagado_no_hay_red(self):
        with mock.patch.object(claves, "leer_clave", return_value=""), mock.patch.object(cloudflare_api, "_pide", side_effect=AssertionError("no deberia llamar")):
            self.assertFalse(cloudflare_uso.leer(FIN_DE_MES)["configurado"])
        cloudflare_uso.invalidar()
        with mock.patch.object(cloudflare_uso, "cfg", return_value={"cloudflare": {"activo": False}}), \
                mock.patch.object(cloudflare_api, "_pide", side_effect=AssertionError("no deberia llamar")):
            self.assertTrue(cloudflare_uso.leer(FIN_DE_MES)["apagado"])
            self.assertEqual(cloudflare_uso.en_cache(), {})

    def test_el_desplegable_tiene_su_pestana_con_gasto_extra_cupos_y_proyectos(self):
        with mock.patch.object(cloudflare_api, "_pide", api()):
            d = cloudflare_uso.leer(FIN_DE_MES)
        html = desplegable_cloudflare.documento(True, datos=d)
        for trozo in ('<span class="on">Cloudflare</span>', "$10,72", "Quién genera el gasto extra", "n1 · KV", "150 %", "15,0 M de 10,0 M",
                      "KV · Escrituras", "Proyectos", "9,0 M · 63,0 M ms", "Ver detalle"):
            self.assertIn(trozo, html)
        self.assertIn("Todavía sin datos", desplegable_cloudflare.documento(True, datos={"configurado": True}))

    def test_la_pestana_solo_se_dibuja_con_cloudflare_configurado(self):
        from infobar import desplegable_comun, geometria_desplegable as G
        self.assertEqual(desplegable_comun.pestanas_visibles(), ("agentes", "servidores"))
        with mock.patch.object(cloudflare_api, "_pide", api()):
            cloudflare_uso.leer(FIN_DE_MES)
        self.assertEqual(desplegable_comun.pestanas_visibles(), ("agentes", "servidores", "cloudflare"))
        self.assertEqual(desplegable_comun.pestanas("agentes").count("<span"), 3)
        # con tres pestañas el ancho se reparte en tercios; con dos, en mitades como siempre
        y = 600 - (G.PESTANAS_Y + 10)
        tres = ("agentes", "servidores", "cloudflare")
        self.assertEqual([G.zona_en(x, y, 600, 2, False, tres) for x in (60, 190, 320)], ["pestana:agentes", "pestana:servidores", "pestana:cloudflare"])
        self.assertEqual([G.zona_en(x, y, 600, 2, False) for x in (60, 180, 320)], ["pestana:agentes", "pestana:agentes", "pestana:servidores"])


class Ajustes(unittest.TestCase):
    BASE = {"proveedores": [], "aliases": {}}

    def test_guarda_la_cuenta_y_el_apagado_y_rechaza_un_id_raro(self):
        out = ajustes.normalizar(dict(self.BASE, cloudflare={"activo": False, "cuenta": CUENTA.upper()}), {})
        self.assertEqual(out["cloudflare"], {"cuenta": CUENTA, "activo": False})
        self.assertNotIn("cloudflare", ajustes.normalizar(dict(self.BASE, cloudflare={"activo": True, "cuenta": ""}), {}))
        with self.assertRaises(ValueError):
            ajustes.normalizar(dict(self.BASE, cloudflare={"cuenta": "no-es-un-id"}), {})

    def test_el_token_tiene_su_cuenta_en_el_llavero(self):
        self.assertTrue(claves.cuenta_valida(cloudflare_uso.CUENTA_LLAVERO))


if __name__ == "__main__":
    unittest.main()
