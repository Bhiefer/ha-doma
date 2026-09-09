"""Regrese parseru a doložených podmínek vybíjení baterie."""

import importlib.util
import itertools
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ha_check", ROOT / "tools" / "check.py")
check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check
spec.loader.exec_module(check)


class YAMLValidationTests(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        for text in ("template: []\ntemplate: []", "a:\n  state: on\n  state: off"):
            with self.subTest(text=text), self.assertRaises(yaml.YAMLError):
                yaml.load(text, Loader=check.HALoader)

    def test_invalid_syntax_rejected(self):
        with self.assertRaises(yaml.YAMLError):
            yaml.load("sensor: [", Loader=check.HALoader)

    def test_ha_tags_preserved_without_reading_secrets(self):
        for tag in check.HA_TAGS:
            with self.subTest(tag=tag):
                self.assertEqual(yaml.load(f"{tag} example", Loader=check.HALoader),
                                 check.Reference(tag, "example"))

    def test_unknown_tag_rejected(self):
        with self.assertRaises(yaml.YAMLError):
            yaml.load("value: !unexpected data", Loader=check.HALoader)

    def test_yaml_merge_override_allowed(self):
        data = yaml.load("base: &base {a: 1}\nnext: {<<: *base, a: 2}", Loader=check.HALoader)
        self.assertEqual(data["next"], {"a": 2})

    def test_file_selection_excludes_secrets_and_other_worktrees(self):
        names = "configuration.yaml\0new.yml\0secrets.yaml\0.worktrees/other/a.yaml\0.venv/a.yaml\0tools/check.py\0"
        with patch.object(check.subprocess, "check_output", return_value=names.encode()), \
                patch.object(Path, "is_file", return_value=True):
            self.assertEqual(check.yaml_paths(ROOT), [ROOT / "configuration.yaml", ROOT / "new.yml"])


class BatteryDischargeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = check.load_yaml(ROOT / "fve" / "fve.yaml")
        cls.entities = [entity for block in cls.package["template"]
                        for entity in block.get("binary_sensor", [])
                        if entity.get("default_entity_id") == "binary_sensor.fve_vybijeni_baterie"]

    def test_single_modern_definition(self):
        self.assertEqual(len(self.entities), 1)
        self.assertEqual(self.entities[0]["name"], "fve_vybijeni_baterie")
        for block in self.package.get("binary_sensor", []):
            self.assertNotIn("fve_vybijeni_baterie", block.get("sensors", {}))

    def test_package_connected(self):
        config = check.load_yaml(ROOT / "configuration.yaml")
        self.assertEqual(config["homeassistant"]["packages"]["fve"],
                         check.Reference("!include", "fve/fve.yaml"))

    def test_discharge_conditions_64_combinations(self):
        # Tabulka vychází z původní podmínky: nabíjení ze sítě blokuje vybíjení;
        # levné topení jej blokuje při vypnutém helperu topení na baterii.
        # Zachováváme i původní chování is_state při unknown/unavailable.
        expected = {
            (False, False, False): "True", (False, False, True): "True",
            (False, True, False): "True", (False, True, True): "False",
            (True, False, False): "False", (True, False, True): "False",
            (True, True, False): "False", (True, True, True): "False",
        }
        inputs = ("binary_sensor.fve_nabijeni_ze_site",
                  "binary_sensor.spot_podprumerna_cena_topeni",
                  "input_boolean.fve_topeni_na_baterii")
        template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(self.entities[0]["state"])
        for values in itertools.product(("on", "off", "unknown", "unavailable"), repeat=3):
            states = dict(zip(inputs, values))
            with self.subTest(states=values):
                result = template.render(is_state=lambda entity, value: states[entity] == value)
                self.assertEqual(result, expected[values[0] == "on", values[1] == "on", values[2] == "off"])


def legacy_entity_paths(value, path="root"):
    # Template triggery automatizací zůstávají platné; hlídáme platformy entit.
    domains = {"sensor", "binary_sensor", "switch", "cover", "light", "fan",
               "lock", "vacuum", "weather", "alarm_control_panel"}
    if isinstance(value, dict):
        for key, child in value.items():
            if key in domains and isinstance(child, list):
                for block in child:
                    if isinstance(block, dict) and block.get("platform") == "template":
                        yield f"{path}.{key}"
            yield from legacy_entity_paths(child, f"{path}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from legacy_entity_paths(child, f"{path}[{i}]")


class TemplateMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {p: check.load_yaml(p) for p in check.yaml_paths(ROOT)}
        cls.entities = [e for d in cls.docs.values() if isinstance(d, dict)
                        for block in d.get("template", [])
                        for domain in ("sensor", "binary_sensor", "switch")
                        for e in block.get(domain, [])]
        cls.by_id = {e["default_entity_id"]: e for e in cls.entities if "default_entity_id" in e}
        cls.env = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def render(self, entity_id, field="state", **context):
        return self.env.from_string(self.by_id[entity_id][field]).render(**context).strip()

    def test_no_legacy_entity_platforms_in_any_yaml(self):
        for path, data in self.docs.items():
            with self.subTest(file=path.name):
                self.assertEqual(list(legacy_entity_paths(data)), [])

    def test_legacy_detection_preserves_template_triggers(self):
        self.assertEqual(list(legacy_entity_paths({"automation": [{"trigger": [
            {"platform": "template", "value_template": "{{ true }}"}]}]})), [])
        for domain in ("sensor", "binary_sensor", "switch", "cover", "light", "fan",
                       "lock", "vacuum", "weather", "alarm_control_panel"):
            with self.subTest(domain=domain):
                self.assertTrue(list(legacy_entity_paths({"package": {
                    domain: [{"platform": "template"}]}})))

    def test_all_38_migrated_ids_preserved_once(self):
        # Seznam pochází z inventury před migrací; chrání vazby dashboardů a řízení.
        expected = {
            "binary_sensor": """fve_dostatecne_nabito fve_nabijeni_ze_site fve_vybijeni_baterie
                spot_nejdrazsi_hodina spot_nejlevnejsi_hodina spot_nizky_tarif
                spot_podprumerna_cena_auto spot_podprumerna_cena_fve spot_podprumerna_cena_topeni""",
            "sensor": """fve_baterie_nabito fve_baterie_stav fve_car_power_available
                fve_celkova_spotreba_prumerna_vikend fve_celkova_spotreba_prumerna_vsedni_den
                fve_denni_spotreba_prumerna fve_dnes_k_nabiti goodwe_baterie_stav
                goodwe_baterie_vykon goodwe_mod_nabijeni kino_trv2_battery kino_trv_battery
                kino_trv_heat marek_trv_battery spot_cena_dynamicka_auto spot_cena_elektriny_distribuce
                spot_cena_elektriny_prumerna_24h_predikce spot_cena_limit_auto spot_cena_limit_fve
                spot_cena_limit_topeni spot_koeficient_ze_site_auto zkusebna_trv_heat""",
            "switch": """kino_termostat_spinac kuchyn_termostat_spinac m_detsky_termostat_spinac
                m_kuchyn_termostat_spinac m_loznice_termostat_spinac m_obyvak_termostat_spinac
                zkusebna_termostat_spinac""",
        }
        actual = [e.get("default_entity_id") for e in self.entities]
        for domain, names in expected.items():
            for name in names.split():
                with self.subTest(entity=f"{domain}.{name}"):
                    self.assertEqual(actual.count(f"{domain}.{name}"), 1)

    def test_modern_template_syntax(self):
        # Parsování ověřuje syntaxi všech moderních šablon, neexistenci entit nikoli.
        for entity in self.entities:
            with self.subTest(entity=entity.get("default_entity_id", entity.get("name"))):
                self.assertFalse({"value_template", "availability_template", "friendly_name"} & entity.keys())
                for field in ("state", "availability", "name"):
                    if isinstance(entity.get(field), str):
                        self.env.parse(entity[field])

    def test_thermostat_actions_unchanged(self):
        # Akce pouze porovnáváme jako data; žádné služby ani skripty nespouštíme.
        for room in ("kino", "kuchyn", "m_obyvak", "m_loznice", "m_detsky"):
            entity = self.by_id[f"switch.{room}_termostat_spinac"]
            for action, script in (("turn_on", "zapnout_trv"), ("turn_off", "vypnout_trv")):
                expected = {"action": f"script.{script}", "data": {"trv": f"climate.{room}_trv"}}
                if room == "kino":
                    expected = [expected, {"action": f"script.{script}", "data": {"trv": "climate.kino_trv2"}}]
                with self.subTest(room=room, action=action):
                    self.assertEqual(entity[action], expected)
        for room in ("zkusebna", "m_kuchyn"):
            entity = self.by_id[f"switch.{room}_termostat_spinac"]
            for action, service in (("turn_on", "switch.turn_off"), ("turn_off", "switch.turn_on")):
                self.assertEqual(entity[action], {"action": service, "data": {
                    "entity_id": [f"switch.{room}_trv_eco_mode"]}})

    def test_thermostat_states_and_unavailable_inputs(self):
        for room in ("zkusebna", "m_kuchyn"):
            for state, expected in (("off", "on"), ("on", "off"), ("unknown", "off"), ("unavailable", "off")):
                with self.subTest(room=room, state=state):
                    self.assertEqual(self.render(f"switch.{room}_termostat_spinac",
                        is_state=lambda e, s: e == f"switch.{room}_trv_eco_mode" and state == s), expected)
        for room in ("kuchyn", "m_obyvak", "m_loznice", "m_detsky"):
            for state in ("heating", "idle", None):
                with self.subTest(room=room, state=state):
                    self.assertEqual(self.render(f"switch.{room}_termostat_spinac",
                        is_state_attr=lambda e, a, s: e == f"climate.{room}_trv" and a == "hvac_action" and state == s),
                        "on" if state == "heating" else "off")
        for first, second, expected in (("heating", "heating", "on"), ("heating", "idle", "off"),
                                        ("idle", "heating", "off"), (None, None, "off")):
            states = {"climate.kino_trv": first, "climate.kino_trv2": second}
            self.assertEqual(self.render("switch.kino_termostat_spinac",
                is_state_attr=lambda e, a, s: a == "hvac_action" and states[e] == s), expected)

    def test_battery_reserve_and_availability(self):
        # Kapacita helperu je ve Wh; původní výpočet ponechává rezervu 20 %.
        def is_number(value):
            try:
                return math.isfinite(float(value))
            except (TypeError, ValueError):
                return False
        for soc, capacity, available, energy in (
            (0, 10000, "True", "0.0"), (20, 10000, "True", "0.0"),
            (21, 10000, "True", "0.1"), (100, 10000, "True", "8.0"),
            (-1, 10000, "False", "None"), (101, 10000, "False", "None"),
            (50, 0, "False", "None"), (50, -1, "False", "None"),
            ("unknown", 10000, "False", "None"), ("unavailable", 10000, "False", "None"),
            (50, "unknown", "False", "None"), (50, "unavailable", "False", "None"),
        ):
            states = {"sensor.goodwe_battery_state_of_charge": str(soc),
                      "input_number.fve_baterie_kapacita": str(capacity)}
            context = {"states": states.__getitem__, "is_number": is_number}
            with self.subTest(soc=soc, capacity=capacity):
                self.assertEqual(self.render("sensor.fve_baterie_nabito", "availability", **context), available)
                self.assertEqual(self.render("sensor.fve_baterie_nabito", **context), energy)


if __name__ == "__main__":
    unittest.main()
