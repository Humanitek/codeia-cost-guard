"""Un plan apagado en Ajustes (suscripción cancelada) no sale en planes ni en cuotas, y al encenderlo vuelve.

Arrancar con:  python3 -m unittest discover tests
"""
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aislamiento  # noqa: E402,F401  (HOME y rutas temporales: antes que costbar)
from infobar import agregacion, planes_y_tarifas  # noqa: E402


def config(activo_nan):
    nan = {"nombre": "NaN", "modelos": ["glm"], "cuotas_mes": {"glm5.3-flash": 1000}}
    if not activo_nan:
        nan["activo"] = False
    return {"proveedores": [{"nombre": "Claude (Max)", "modelos": ["claude"]}, nan], "aliases": {}}


def vistos():
    hoy = time.strftime("%Y-%m-%d")
    return {"a": {"dia": {hoy: {"claude-sonnet-5": [10, 0, 0, 0]}}, "turnos": {hoy: 1}, "horas": {}, "proyecto": "p", "plan": "Claude (Max)"},
            "b": {"dia": {hoy: {"glm5.3-flash": [40, 0, 0, 0]}}, "turnos": {hoy: 1}, "horas": {}, "proyecto": "p", "plan": None}}


class PlanApagado(unittest.TestCase):
    def informe(self, activo_nan, v=None):
        c = config(activo_nan)
        with mock.patch.object(agregacion, "cfg", lambda: c), mock.patch.object(planes_y_tarifas, "cfg", lambda: c):
            return agregacion.agregar(v or vistos(), 0, 7)

    def test_encendido_sale_con_su_cuota(self):
        r = self.informe(True)
        self.assertEqual(set(r["proveedores"]), {"Claude (Max)", "NaN"})
        self.assertEqual(r["proveedores"]["NaN"]["modelos_cuota"][0]["mes"], 40)

    def test_apagado_no_sale_ni_en_planes_ni_en_cuotas(self):
        r = self.informe(False)
        self.assertEqual(set(r["proveedores"]), {"Claude (Max)"})
        self.assertFalse(any(x.get("modelos_cuota") for x in r["proveedores"].values()))

    def test_apagado_sus_modelos_no_reaparecen_como_plan_suelto(self):
        # el plan apagado sigue reconociendo sus modelos: no se cuelan como una familia «glm» automática
        r = self.informe(False)
        self.assertNotIn("glm", r["proveedores"])
        self.assertIn("glm5.3-flash", r["cruce"]["NaN"])        # y Ajustes puede seguir listando lo que usó

    def test_apagado_no_se_nombra_en_la_ventana_de_5h(self):
        # las familias de la ventana de 5 h llevan nombre de plan: apagado no se nombra, pero su consumo sigue sumando
        v = vistos()
        v["b"]["horas"] = {int(time.time()): {"tok": 50, "usd": 0.0, "mod": {"glm5.3-flash": 50}}}
        self.assertEqual(self.informe(True, v)["cinco_h"]["fam"], {"NaN": 50})
        r = self.informe(False, v)
        self.assertNotIn("NaN", r["cinco_h"]["fam"])
        self.assertEqual(r["cinco_h"]["tok"], 50)

    def test_apagado_no_consulta_la_api_del_proveedor(self):
        c = config(False)
        c["proveedores"][1]["uso_api"] = "nan"
        with mock.patch.object(agregacion, "cfg", lambda: c), mock.patch.object(planes_y_tarifas, "cfg", lambda: c), \
                mock.patch.object(agregacion, "uso_nan") as uso:
            r = agregacion.agregar(vistos(), 0, 7)
        uso.assert_not_called()
        self.assertNotIn("NaN", r["proveedores"])


if __name__ == "__main__":
    unittest.main()
