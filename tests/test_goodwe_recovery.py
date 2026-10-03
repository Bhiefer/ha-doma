"""Obnova patří jen existující integraci po výpadku všech zdrojových fází."""
import itertools
import unittest

import jinja2
import test_checks as base


class GoodWeRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = base.check.load_yaml(base.ROOT / 'fve/fve.yaml')
        cls.automation = next(a for a in package['automation']
                              if a['id'] == 'fve_goodwe_obnova')

    def test_only_complete_outage_of_existing_integration(self):
        template = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            self.automation['trigger'][0]['value_template'])
        for entry in (None, 'local-goodwe-entry'):
            for phases in itertools.product(('unknown', 'unavailable', '0', '-500'), repeat=3):
                states = dict(zip((f'sensor.goodwe_active_power_l{i}' for i in range(1, 4)), phases))
                with self.subTest(entry=entry, phases=phases):
                    result = template.render(config_entry_id=lambda _: entry,
                                             states=lambda e: states[e]).strip()
                    expected = entry is not None and all(
                        p in ('unknown', 'unavailable') for p in phases)
                    self.assertEqual(result, str(expected))

    def test_two_hours_then_one_local_reload(self):
        self.assertEqual(self.automation['trigger'][0]['for'], '02:00:00')
        self.assertEqual(self.automation['mode'], 'single')
        actions = self.automation['action']
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['action'], 'homeassistant.reload_config_entry')
        template = jinja2.Environment().from_string(actions[0]['data']['entry_id'])
        for local_entry in ('kopec-entry', 'evans-entry'):
            self.assertEqual(template.render(config_entry_id=lambda _: local_entry), local_entry)
