"""Regrese parseru a doložených podmínek vybíjení baterie."""

import ast
import importlib.util
import itertools
import math
from pathlib import Path
import sys
from types import SimpleNamespace
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


class CarChargingProposalTests(unittest.TestCase):
    """Výpočet z reálné YAML šablony, bez volání služeb nebo změn zařízení."""

    @classmethod
    def setUpClass(cls):
        package = check.load_yaml(ROOT / "fve" / "fve.yaml")
        block = next(b for b in package["template"]
                     if any(s.get("default_entity_id") == "sensor.fve_auto_vykon_doporuceny"
                            for s in b.get("sensor", [])))
        cls.template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            block["action"][0]["variables"]["fve_auto_varianta"])

    def proposal(self, mode="adaptivni", grid=(0, 0, 0), car=(0, 0, 0),
                 price=3, limit=0.6, overrides=None, maximum=16, minimum=False):
        states = {"input_select.fve_auto_rezim": mode,
                  "input_select.fve_auto_mapovani_fazi": "1-2-3",
                  "sensor.current_spot_electricity_price": price,
                  "sensor.spot_cena_limit_auto": limit}
        for i, (export, power) in enumerate(zip(grid, car), 1):
            states[f"sensor.fve_pretok_l{i}"] = export
            states[f"sensor.fve_auto_prikon_l{i}"] = power
        states.update(overrides or {})

        def is_number(value):
            try:
                return math.isfinite(float(value))
            except (ValueError, TypeError):
                return False

        return ast.literal_eval(self.template.render(
            states=lambda entity: str(states.get(entity, "unknown")),
            is_number=is_number,
            state_attr=lambda entity, attr: maximum,
            is_state=lambda entity, value: minimum and entity == "timer.fve_auto_minimum" and value == "active").strip())

    def test_six_ampere_from_five_solar_and_one_grid(self):
        result = self.proposal(grid=(1150, 0, 0))
        self.assertEqual((result["faze"], result["proud"], result["vykon"]), (1, 6, 1380))
        self.assertAlmostEqual(result["cena"], 0.5)

    def test_highest_power_not_lowest_price_or_highest_current(self):
        # 1 x 16 A je zdarma, ale 3 x 6 A má vyšší výkon a ještě vyhoví limitu.
        result = self.proposal(grid=(3680, 1000, 1000))
        self.assertEqual((result["faze"], result["proud"]), (3, 6))

    def test_full_power_when_grid_price_below_limit(self):
        for mode in ("fixni", "adaptivni"):
            with self.subTest(mode=mode):
                result = self.proposal(mode=mode, price=0.5)
                self.assertEqual(result["vykon"], 11040)
                self.assertEqual(result["podil_site"], 1)

    def test_adaptive_obeys_local_current_cap(self):
        result = self.proposal(price=0.5, maximum=8)
        self.assertEqual((result["faze"], result["proud"]), (3, 8))
        self.assertEqual(self.proposal(price=0.5, maximum=32)["proud"], 16)
        for maximum in (None, "unknown", float("nan"), 5):
            self.assertFalse(self.proposal(maximum=maximum)["platne"])
        self.assertEqual(self.proposal(mode="fixni", price=0.5, maximum=None)["proud"], 16)

    def test_minimum_falls_back_without_price_but_not_without_measurement(self):
        for mode, pair in (("fixni", (3, 16)), ("adaptivni", (1, 6))):
            result = self.proposal(mode=mode, price="unavailable", minimum=True)
            self.assertEqual((result["faze"], result["proud"]), pair)
            self.assertIsNone(result["cena"])
            self.assertFalse(result["varianty"][f"{pair[0]}/{pair[1]}"]["vyhovuje"])
        result = self.proposal(minimum=True, overrides={"sensor.fve_pretok_l2": "unavailable"})
        self.assertFalse(result["platne"])
        self.assertEqual(result["vykon"], 0)

    def test_equal_limit_does_not_allow_charging(self):
        result = self.proposal(grid=(1150, 0, 0), limit=0.5)
        self.assertTrue(result["platne"])
        self.assertEqual(result["vykon"], 0)
        self.assertIsNone(result["cena"])

    def test_other_phase_export_cannot_supply_single_phase(self):
        result = self.proposal(grid=(0, 0, 11040))
        self.assertEqual(result["vykon"], 0)

    def test_fixed_has_only_three_phase_sixteen_ampere(self):
        result = self.proposal(mode="fixni", grid=(1150, 0, 0))
        self.assertEqual(result["vykon"], 0)
        result = self.proposal(mode="fixni", grid=(3680, 3680, 3680))
        self.assertEqual((result["faze"], result["proud"]), (3, 16))

    def test_measured_car_load_is_added_back_on_each_phase(self):
        before = self.proposal(grid=(2000, 1700, 1300))
        during = self.proposal(grid=(-1000, -300, 300), car=(3000, 2000, 1000))
        self.assertEqual(before, during)

    def test_house_import_is_not_charged_to_car(self):
        result = self.proposal(grid=(-5000, -2000, -1000), price=0.5)
        self.assertEqual(result["podil_site"], 1)
        self.assertEqual(result["cena"], 0.5)

    def test_zero_and_negative_spot_are_valid(self):
        for price in (0, -2):
            with self.subTest(price=price):
                result = self.proposal(price=price)
                self.assertTrue(result["platne"])
                self.assertEqual(result["vykon"], 11040)

    def test_missing_and_nonfinite_measurements_are_not_surplus(self):
        inputs = [f"sensor.{kind}{i}"
                  for kind in ("fve_pretok_l", "fve_auto_prikon_l") for i in range(1, 4)]
        for entity, value in itertools.product(inputs, ("unknown", "unavailable", "nan", "inf", "-inf")):
            with self.subTest(entity=entity, value=value):
                result = self.proposal(grid=(11040, 11040, 11040),
                                       price="unavailable", overrides={entity: value})
                self.assertFalse(result["platne"])
                self.assertEqual(result["vykon"], 0)

    def test_missing_price_or_limit_allows_only_measured_surplus(self):
        # Výpadek ceny nemění skutečně změřené přebytky na neplatná data,
        # ale nesmí povolit ani malý dokup. Platí pro obě instalace.
        for mode, entity, value in itertools.product(
                ("fixni", "adaptivni"),
                ("sensor.current_spot_electricity_price", "sensor.spot_cena_limit_auto"),
                ("unknown", "unavailable", "nan", "inf", "-inf")):
            with self.subTest(mode=mode, entity=entity, value=value):
                result = self.proposal(mode=mode, overrides={entity: value})
                self.assertTrue(result["platne"])
                self.assertEqual(result["vykon"], 0)
                self.assertIsNone(result["cena"])
                result = self.proposal(mode=mode, grid=(3680, 3680, 3680),
                                       overrides={entity: value})
                self.assertEqual(result["vykon"], 11040)
                self.assertEqual(result["cena"], 0)
                self.assertEqual(result["podil_site"], 0)

    def test_solar_without_price_selects_highest_fully_covered_power(self):
        result = self.proposal(grid=(3680, 1380, 1380), price="unavailable")
        self.assertEqual((result["faze"], result["proud"]), (3, 6))
        self.assertEqual(result["podil_site"], 0)
        result = self.proposal(grid=(1380, 0, 0), price="unavailable")
        self.assertEqual((result["faze"], result["proud"]), (1, 6))
        self.assertEqual(self.proposal(grid=(1379, 0, 0), price="unavailable")["vykon"], 0)

    def test_solar_does_not_need_positive_limit_or_price(self):
        result = self.proposal(grid=(3680, 3680, 3680), price="unavailable", limit="unknown")
        self.assertEqual(result["vykon"], 11040)
        result = self.proposal(grid=(3680, 3680, 3680), price=10, limit=0)
        self.assertEqual(result["vykon"], 11040)

    def test_negative_car_consumption_is_invalid(self):
        self.assertFalse(self.proposal(car=(-1, 0, 0))["platne"])

    def test_instance_without_car_is_not_enabled(self):
        for mode in ("off", "unknown", "unavailable", ""):
            with self.subTest(mode=mode):
                self.assertFalse(self.proposal(mode=mode)["platne"])

    def test_phase_mapping_uses_normalized_grid_order(self):
        # Wallbox L1 je na fázi 2 přípojky; zdroj měření nezávisí na režimu.
        result = self.proposal(price="unavailable", overrides={
            "input_select.fve_auto_mapovani_fazi": "2-1-3",
            "sensor.fve_pretok_l2": 1380,
        })
        self.assertEqual((result["faze"], result["proud"]), (1, 6))

    def test_unverified_mapping_blocks_proposal(self):
        for value in ("neovereno", "1-1-3"):
            with self.subTest(value=value):
                self.assertFalse(self.proposal(overrides={
                    "input_select.fve_auto_mapovani_fazi": value})["platne"])

    def test_local_adapter_preserves_measurements_and_unavailability(self):
        # Dočasný odhad GoodWe je ×3; příkon auta a znaménko se zachovávají.
        config = check.load_yaml(ROOT / "configuration.yaml")
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        for kind, source in (("fve_pretok", "goodwe_active_power_l"),
                             ("fve_auto_prikon", "wallbox_power_l")):
            for i in range(1, 4):
                sensor = next(s for b in config["template"] for s in b.get("sensor", [])
                              if s.get("default_entity_id") == f"sensor.{kind}_l{i}")
                for value in ("-500", "0", "1380", "unknown", "unavailable", "nan", "inf"):
                    def states(entity):
                        self.assertEqual(entity, f"sensor.{source}{i}")
                        return value
                    def is_number(v):
                        try:
                            return math.isfinite(float(v))
                        except (ValueError, TypeError):
                            return False
                    valid = env.from_string(sensor["availability"]).render(
                        states=states, is_number=is_number)
                    self.assertEqual(valid, str(is_number(value)))
                    if is_number(value):
                        self.assertEqual(float(env.from_string(sensor["state"]).render(
                            states=states, is_number=is_number)),
                            float(value) * (3 if kind == "fve_pretok" else 1))

    def test_local_helpers_do_not_reset_on_restart(self):
        # Po synchronizaci souboru se nesmí místní hodnoty režimu nabíjení přepsat initial.
        package = check.load_yaml(ROOT / "fve" / "fve.yaml")
        self.assertEqual(package["input_select"]["fve_auto_rezim"]["options"][0], "vypnuto")
        for domain in ("input_select", "input_text"):
            for name, config in package.get(domain, {}).items():
                if name.startswith("fve_auto_"):
                    self.assertNotIn("initial", config)


class CarChargingStabilityTests(unittest.TestCase):
    """Minutové potvrzení vyhodnocujeme skutečnými šablonami s řízeným časem."""

    @classmethod
    def setUpClass(cls):
        package = check.load_yaml(ROOT / "fve" / "fve.yaml")
        cls.sensor = next(s for b in package["template"] for s in b.get("sensor", [])
                          if s.get("default_entity_id") == "sensor.fve_auto_nastaveni_cilove")
        cls.env = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def step(self, previous, time, phases=3, amps=16, valid=True, startup=False, minimum=False):
        context = dict(this=previous, now=lambda: time, as_timestamp=lambda value: value,
                       trigger=SimpleNamespace(platform="homeassistant" if startup else "time_pattern"),
                       fve_auto_varianta=SimpleNamespace(faze=phases, proud=amps, platne=valid, varianty={"3/16": {}}),
                       is_state=lambda entity, value: minimum and value == "active")
        render = lambda text: self.env.from_string(text).render(**context).strip()
        # HA při nedostupnosti nepoužije číselný/stavový výsledek šablony.
        state = render(self.sensor["state"]) if valid else "unavailable"
        attributes = {key: ast.literal_eval(render(text)) if key == "navrh_od"
                      else render(text) for key, text in self.sensor["attributes"].items()}
        return SimpleNamespace(state=state, attributes=attributes)

    def test_exact_minute_then_change_does_not_apply_immediately(self):
        current = self.step(SimpleNamespace(state="unknown", attributes={}), 0)
        self.assertEqual(current.state, "0/0")
        current = self.step(current, 59)
        self.assertEqual(current.state, "0/0")
        current = self.step(current, 60)
        self.assertEqual(current.state, "3/16")
        current = self.step(current, 70, phases=1, amps=6)
        self.assertEqual(current.state, "3/16")
        current = self.step(current, 129, phases=1, amps=6)
        self.assertEqual(current.state, "3/16")
        current = self.step(current, 130, phases=1, amps=6)
        self.assertEqual(current.state, "1/6")

    def test_restart_preserves_active_minimum_without_new_deadline(self):
        previous = SimpleNamespace(state="3/16", attributes={"navrh": "3/16", "navrh_od": 0})
        current = self.step(previous, 500, startup=True, minimum=True)
        self.assertEqual(current.state, "3/16")
        self.assertEqual(current.attributes["navrh_od"], 500)
        # Jiný cíl musí i po restartu znovu počkat minutu.
        self.assertEqual(self.step(current, 510, phases=1, amps=6, minimum=True).state, "3/16")

    def test_changing_proposal_restarts_confirmation(self):
        current = self.step(SimpleNamespace(state="0/0", attributes={}), 0)
        current = self.step(current, 50, amps=15)
        current = self.step(current, 60)
        current = self.step(current, 110)
        self.assertEqual(current.state, "0/0")
        self.assertEqual(self.step(current, 120).state, "3/16")

    def test_restart_and_recovery_do_not_reuse_old_confirmation(self):
        previous = SimpleNamespace(state="3/16", attributes={"navrh": "3/16", "navrh_od": 0})
        current = self.step(previous, 1000, startup=True)
        self.assertEqual(current.state, "0/0")
        self.assertEqual(current.attributes["navrh_od"], 1000)
        current = self.step(current, 1060)
        current = self.step(current, 1070, valid=False)
        self.assertEqual(current.state, "unavailable")
        # I kdyby HA při unavailable ponechal staré atributy, musí čekat znovu.
        current.attributes = previous.attributes
        current = self.step(current, 2000)
        self.assertEqual(current.state, "0/0")
        self.assertEqual(self.step(current, 2059).state, "0/0")
        self.assertEqual(self.step(current, 2060).state, "3/16")


if __name__ == "__main__":
    unittest.main()
