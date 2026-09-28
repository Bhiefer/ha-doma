"""Řídicí akce z YAML nad náhradami služeb: bez spojení s domácností."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import jinja2
import test_checks as base


class Stopped(Exception):
    pass


class CarControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = base.check.load_yaml(base.ROOT / 'fve/fve.yaml')
        cls.config = base.check.load_yaml(base.ROOT / 'configuration.yaml')
        cls.env = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def setUp(self):
        self.states = {
            'input_select.fve_auto_rezim': 'adaptivni',
            'binary_sensor.spot_podprumerna_cena_auto': 'on',
            'sensor.fve_auto_nastaveni_cilove': '3/16',
            'switch.fve_auto_nabijeni': 'off',
            'number.fve_auto_proud': '6', 'select.fve_auto_faze': '1',
            'binary_sensor.fve_auto_nabijeni': 'off',
            'input_boolean.fve_auto_relace_zahajena': 'off',
            'timer.fve_auto_minimum': 'idle',
            **{f'sensor.fve_auto_prikon_l{i}': '0' for i in range(1, 4)},
        }
        self.attrs = {('number.fve_auto_proud', 'max'): 16}
        self.calls = []
        self.acknowledge = True
        self.context = {
            'states': lambda e: self.states.get(e, 'unknown'),
            'is_state': lambda e, v: self.states.get(e) == v,
            'state_attr': lambda e, a: self.attrs.get((e, a)),
            'is_number': lambda v: self.numeric(v),
            'trigger': SimpleNamespace(id='', from_state=None),
        }

    @staticmethod
    def numeric(value):
        import math
        try:
            return math.isfinite(float(value))
        except (ValueError, TypeError):
            return False

    def render(self, value):
        if not isinstance(value, str) or ('{{' not in value and '{%' not in value):
            return value
        out = self.env.from_string(value).render(**self.context).strip()
        try:
            return ast.literal_eval(out)
        except (ValueError, SyntaxError):
            return out

    def run_actions(self, actions):
        for a in actions:
            if 'variables' in a:
                self.context.update({k: self.render(v) for k, v in a['variables'].items()})
            elif 'condition' in a:
                if not self.render(a['value_template']):
                    raise Stopped()
            elif 'choose' in a:
                for choice in a['choose']:
                    if self.render(choice['conditions']):
                        self.run_actions(choice['sequence'])
                        break
                else:
                    self.run_actions(a.get('default', []))
            elif 'if' in a:
                self.run_actions(a.get('then' if self.render(a['if']) else 'else', []))
            elif 'wait_template' in a:
                completed = bool(self.render(a['wait_template']))
                self.context['wait'] = SimpleNamespace(completed=completed)
                if not completed and not a.get('continue_on_timeout', True):
                    raise Stopped()
            elif 'stop' in a:
                raise Stopped()
            else:
                service = a['action']
                entity = a['target']['entity_id']
                data = {k: self.render(v) for k, v in a.get('data', {}).items()}
                self.calls.append((service, entity, data))
                if service in ('switch.turn_on', 'switch.turn_off', 'input_boolean.turn_on', 'input_boolean.turn_off'):
                    self.states[entity] = service.split('_')[-1]
                elif service == 'timer.start':
                    self.states[entity] = 'active'
                elif service == 'timer.cancel':
                    self.states[entity] = 'idle'
                elif self.acknowledge:
                    self.states[entity] = str(data.get('value', data.get('option')))

    def run_automation(self, identifier):
        automation = next(a for a in self.package['automation'] if a.get('id') == identifier)
        try:
            self.run_actions(automation['action'])
        except Stopped:
            pass

    def test_adaptive_configures_before_start_using_only_adapters(self):
        self.run_automation('fve_auto_rizeni')
        self.assertEqual([c[0] for c in self.calls],
                         ['switch.turn_off', 'number.set_value', 'select.select_option', 'switch.turn_on'])
        self.assertTrue(all('.fve_auto_' in c[1] for c in self.calls))

    def test_fixed_only_switches_and_needs_no_adjustable_entities(self):
        self.states['input_select.fve_auto_rezim'] = 'fixni'
        self.states.pop('number.fve_auto_proud')
        self.states.pop('select.fve_auto_faze')
        self.run_automation('fve_auto_rizeni')
        self.assertEqual(self.calls, [('switch.turn_on', 'switch.fve_auto_nabijeni', {})])

    def test_unconfirmed_stop_prevents_phase_change(self):
        for value in ('1380', 'unavailable'):
            with self.subTest(value=value):
                self.setUp()
                self.states['sensor.fve_auto_prikon_l1'] = value
                self.run_automation('fve_auto_rizeni')
                self.assertEqual([c[0] for c in self.calls], ['switch.turn_off'])

    def test_unacknowledged_current_stops_even_without_phase_change(self):
        self.states['select.fve_auto_faze'] = '3'
        self.states['switch.fve_auto_nabijeni'] = 'on'
        self.acknowledge = False
        self.run_automation('fve_auto_rizeni')
        self.assertEqual([c[0] for c in self.calls], ['number.set_value', 'switch.turn_off'])

    def test_missing_adapter_or_lowered_limit_stops(self):
        for unavailable in (True, False):
            with self.subTest(unavailable=unavailable):
                self.setUp()
                self.states['switch.fve_auto_nabijeni'] = 'on'
                if unavailable:
                    self.states['number.fve_auto_proud'] = 'unavailable'
                else:
                    self.attrs[('number.fve_auto_proud', 'max')] = 8
                self.run_automation('fve_auto_rizeni')
                self.assertEqual([c[0] for c in self.calls], ['switch.turn_off'])

    def test_disabled_instance_is_untouched_but_disabling_stops(self):
        self.states['input_select.fve_auto_rezim'] = 'vypnuto'
        self.run_automation('fve_auto_rizeni')
        self.assertEqual(self.calls, [])
        self.context['trigger'] = SimpleNamespace(id='rezim', from_state=SimpleNamespace(state='adaptivni'))
        self.run_automation('fve_auto_rizeni')
        self.assertEqual([c[0] for c in self.calls], ['switch.turn_off'])

    def test_minimum_starts_at_actual_charging_once_and_survives_pause(self):
        self.states['switch.fve_auto_nabijeni'] = 'on'
        self.run_automation('fve_auto_minimum')
        self.assertEqual(self.calls, [])
        self.states['binary_sensor.fve_auto_nabijeni'] = 'on'
        self.run_automation('fve_auto_minimum')
        self.assertEqual(self.states['timer.fve_auto_minimum'], 'active')
        self.states['binary_sensor.fve_auto_nabijeni'] = 'off'
        self.run_automation('fve_auto_minimum')
        self.states['binary_sensor.fve_auto_nabijeni'] = 'on'
        self.run_automation('fve_auto_minimum')
        self.states['timer.fve_auto_minimum'] = 'idle'  # Původních 20 minut uplynulo.
        self.run_automation('fve_auto_minimum')
        self.assertEqual(sum(c[0] == 'timer.start' for c in self.calls), 1)
        self.assertEqual(self.package['timer']['fve_auto_minimum']['duration'], '00:20:00')
        self.assertTrue(self.package['timer']['fve_auto_minimum']['restore'])

    def test_permission_loss_cancels_minimum(self):
        self.states.update({'timer.fve_auto_minimum': 'active',
                            'input_boolean.fve_auto_relace_zahajena': 'on',
                            'binary_sensor.spot_podprumerna_cena_auto': 'off'})
        self.run_automation('fve_auto_minimum')
        self.assertEqual([c[0] for c in self.calls], ['timer.cancel', 'input_boolean.turn_off'])

    def test_price_gate_allows_minimum_but_measurement_loss_always_stops(self):
        gate = next(s for b in self.package['template'] for s in b.get('binary_sensor', [])
                    if s.get('default_entity_id') == 'binary_sensor.spot_podprumerna_cena_auto')
        self.attrs[('sensor.fve_auto_vykon_doporuceny', 'varianty')] = {'3/16': {'vyhovuje': False}}
        self.states['sensor.fve_auto_vykon_doporuceny'] = '1380'
        self.states['timer.fve_auto_minimum'] = 'active'
        self.assertTrue(self.render(gate['state']))
        self.states['timer.fve_auto_minimum'] = 'idle'
        self.assertFalse(self.render(gate['state']))
        self.attrs[('sensor.fve_auto_vykon_doporuceny', 'varianty')]['3/16']['vyhovuje'] = True
        self.assertTrue(self.render(gate['state']))
        self.states['sensor.fve_auto_vykon_doporuceny'] = 'unavailable'
        self.states['timer.fve_auto_minimum'] = 'active'
        self.assertFalse(self.render(gate['state']))

    def test_switch_is_local_template_and_preserves_on_off_options(self):
        switch = next(s for b in self.config['template'] for s in b.get('switch', [])
                      if s.get('default_entity_id') == 'switch.fve_auto_nabijeni')
        for side, option in (('turn_on', 'On'), ('turn_off', 'Off')):
            self.assertEqual(switch[side][0]['target']['entity_id'], 'select.wallbox_force_state')
            self.assertEqual(switch[side][0]['data']['option'], option)
        for state, expected in (('On', True), ('Off', False), ('Neutral', True)):
            self.states['select.wallbox_force_state'] = state
            self.assertTrue(self.render(switch['availability']))
            self.assertEqual(self.render(switch['state']), expected)
        self.states['select.wallbox_force_state'] = 'unavailable'
        self.assertFalse(self.render(switch['availability']))

    def test_current_template_forwards_only_whole_amperes_6_to_16(self):
        number = next(s for b in self.config['template'] for s in b.get('number', [])
                      if s.get('default_entity_id') == 'number.fve_auto_proud')
        self.assertEqual((number['min'], number['max'], number['step']), (6, 16, 1))
        for value in (6, 10, 16, 5, 17, 6.5, 'unavailable', 'nan'):
            with self.subTest(value=value):
                self.calls = []
                self.context['value'] = value
                try:
                    self.run_actions(number['set_value'])
                except Stopped:
                    pass
                expected = [('number.set_value', 'number.wallbox_set_max_ampere_limit',
                             {'value': value})] if value in (6, 10, 16) else []
                self.assertEqual(self.calls, expected)
        for value in ('6', '16', '32', 'unknown', 'unavailable', 'nan', 'inf'):
            self.states['number.wallbox_set_max_ampere_limit'] = value
            self.assertEqual(self.render(number['availability']), self.numeric(value))
            if self.numeric(value):
                self.assertEqual(self.render(number['state']), float(value))

    def test_temporary_goodwe_scale_preserves_sign_and_rejects_missing_data(self):
        # Odhad celé FVE násobí jen přetok; skutečný příkon auta zůstává měřený.
        sensors = {s.get('default_entity_id'): s for b in self.config['template']
                   for s in b.get('sensor', [])}
        for phase in range(1, 4):
            grid = sensors[f'sensor.fve_pretok_l{phase}']
            car = sensors[f'sensor.fve_auto_prikon_l{phase}']
            for value in ('-100', '0', '250.5', 'unknown', 'unavailable', 'nan', 'inf'):
                with self.subTest(phase=phase, value=value):
                    self.states[f'sensor.goodwe_active_power_l{phase}'] = value
                    self.assertEqual(self.render(grid['availability']), self.numeric(value))
                    expected = float(value) * 3 if self.numeric(value) else None
                    self.assertEqual(self.render(grid['state']), expected)
            self.states[f'sensor.wallbox_power_l{phase}'] = '1380'
            self.assertEqual(self.render(car['state']), 1380)
