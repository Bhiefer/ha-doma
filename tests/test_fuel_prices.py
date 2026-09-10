"""Ceny paliv: skutečné šablony, chybějící vstupy a smlouva s exportérem."""

import json
import math
import shutil
import subprocess
import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from test_checks import ROOT, check

# Klíče ověřené v listech zdrojové tabulky 10. 9. 2026, nezávisle na YAML.
SOURCE_KEYS = {
    "evans", "a1_royal", "kohutovy_mm_royal", "cdp_pfeifer", "a1_rettenmeier",
    "waldera", "biomac_top_a1", "premium_pellets_jenikov", "lysuvky_royal",
    "topiva_strom_mt", "evans_ruf_mosaic", "mosaic_ruf_direct", "topiva_strom_ruf",
    "evans_tmave_hard", "a1_tmave_hard", "biomac_energo_hard",
}


class FuelPriceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rest = check.load_yaml(ROOT / "ceny_paliv_rest.yaml")[0]
        cls.sensors = cls.rest["sensor"][1:]
        cls.dashboard = check.load_yaml(ROOT / "ceny_paliv_dashboard.yaml")
        cls.env = NativeEnvironment(undefined=StrictUndefined)
        cls.env.globals["is_number"] = lambda value: (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value)
        )

    def render(self, sensor, field, payload):
        context = {} if payload is ... else {"value_json": payload}
        return self.env.from_string(sensor[field]).render(**context)

    def test_real_prices_null_delta_and_stock_status(self):
        # Nedostupné zboží má stále doloženou cenu. Prázdná změna není nula.
        for sensor in self.sensors:
            key = sensor["unique_id"].removeprefix("ceny_paliv_")
            for status in ("SKLADEM", "NEDOSTUPNÉ", "NEPOTVRZENO PRO BAŠKU"):
                payload = {"ok": True, "items": {key: {
                    "price_per_kg": 12.18095238095238,
                    "change_10d_per_kg": None, "status": status,
                }}}
                with self.subTest(key=key, status=status):
                    self.assertIs(self.render(sensor, "availability", payload), True)
                    self.assertAlmostEqual(self.render(sensor, "value_template", payload),
                                           12.18095238095238)
                    self.assertIn("change_10d_per_kg", sensor["json_attributes"])
                    self.assertEqual(sensor["json_attributes_path"], "$.items." + key)

    def test_bad_responses_and_prices_never_become_zero(self):
        for sensor in self.sensors:
            key = sensor["unique_id"].removeprefix("ceny_paliv_")
            payloads = [..., None, [], "html", {}, {"ok": False, "error": "unauthorized"},
                        {"ok": True}, {"ok": True, "items": []},
                        {"ok": True, "items": {key: None}},
                        {"ok": True, "items": {key: {}}}]
            for price in (None, "", "unknown", "unavailable", True, False,
                          "12 Kč/kg", float("nan"), float("inf")):
                payloads.append({"ok": True, "items": {key: {"price_per_kg": price}}})
            # I odpověď s cenou se při chybovém ok:false musí odmítnout.
            payloads.append({"ok": False, "items": {key: {"price_per_kg": 10}}})
            for payload in payloads:
                with self.subTest(key=key, payload=payload):
                    self.assertIs(self.render(sensor, "availability", payload), False)
                    self.assertIsNone(self.render(sensor, "value_template", payload))

    def test_api_sensor_rejects_error_and_non_json(self):
        sensor = self.rest["sensor"][0]
        for payload in (..., None, [], {}, {"ok": False}, {"ok": True, "items": {}}):
            with self.subTest(payload=payload):
                self.assertIs(self.render(sensor, "availability", payload), False)
        payload = {"ok": True, "generated_at": "2026-09-09T08:00:00Z", "items": {}}
        self.assertIs(self.render(sensor, "availability", payload), True)

    def test_wiring_and_dashboard_actions(self):
        config = check.load_yaml(ROOT / "configuration.yaml")
        self.assertEqual(config["rest"], check.Reference("!include", "ceny_paliv_rest.yaml"))
        self.assertEqual(config["lovelace"]["dashboards"]["ceny-paliv"]["filename"],
                         "ceny_paliv_dashboard.yaml")
        self.assertEqual(self.rest["resource"], check.Reference("!secret", "fuel_prices_api_url"))
        self.assertEqual(self.rest["scan_interval"], 21600)
        cards = [card for view in self.dashboard["views"] for card in view["cards"]
                 if card["type"] == "custom:bubble-card"]
        self.assertEqual(len(cards), 16)
        self.assertEqual({s["unique_id"].removeprefix("ceny_paliv_")
                          for s in self.sensors}, SOURCE_KEYS)
        self.assertEqual({card["entity"] for card in cards},
                         {"sensor." + sensor["unique_id"] for sensor in self.sensors})
        self.assertEqual(len({s["unique_id"] for s in self.rest["sensor"]}), 17)
        for card in cards:
            for action in (card["tap_action"], card["button_action"]["tap_action"],
                           *[sub["tap_action"] for sub in card["sub_button"]]):
                self.assertEqual(action, {"action": "more-info"})

    def test_actual_exporter_and_dashboard_javascript(self):
        # Node vykonává skutečný zdroj; Google služby jsou pouze místní náhrady.
        node = shutil.which("node")
        self.assertIsNotNone(node, "Pro test exportéru je potřeba Node.js 18+ v PATH.")
        keys = [sensor["unique_id"].removeprefix("ceny_paliv_") for sensor in self.sensors]
        styles = self.dashboard["views"][0]["cards"][1]["styles"]
        result = subprocess.run(
            [node, str(ROOT / "tests" / "test_fuel_prices_api.cjs")],
            input=json.dumps({"keys": keys, "styles": styles}),
            text=True, capture_output=True, cwd=ROOT, encoding="utf-8", timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
