"""Startovací oprava proti doloženému chování presetů HA 2026.10.1.

Modeluje pouze preset a cíl; nespouští HA ani relé. Stejný preset se v této
verzi ignoruje, away uloží normální cíl a none jej vrátí (generic_thermostat).
"""
import unicodedata
import unittest

import test_checks as base


class HeatingStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = base.check.load_yaml(base.ROOT / 'scripts.yaml')
        cls.automations = base.check.load_yaml(base.ROOT / 'automations.yaml')
        cls.groups = base.check.load_yaml(base.ROOT / 'groups.yaml')
        cls.reset = cls.scripts['obnov_mod_topeni']['sequence']
        cls.thermostat_rule = next(a for a in cls.automations if a['id'] == '1698311963410')
        cls.configs = {}
        for config in base.check.load_yaml(base.ROOT / 'configuration.yaml')['climate']:
            name = unicodedata.normalize('NFKD', config['name']).encode('ascii', 'ignore').decode()
            cls.configs['climate.' + name.lower().replace(' ', '_')] = config

    def expand(self, targets):
        if isinstance(targets, str):
            targets = [targets]
        result = []
        for target in targets:
            if target.startswith('group.'):
                result.extend(self.groups[target.removeprefix('group.')]['entities'])
            else:
                result.append(target)
        return result

    def preset(self, rooms, targets, value):
        for entity in self.expand(targets):
            room = rooms[entity]
            if room['preset'] == value:
                continue
            if value == 'none':
                room['target'] = room['normal']
            else:
                if room['preset'] == 'none':
                    room['normal'] = room['target']
                room['target'] = self.configs[entity]['away_temp']
            room['preset'] = value

    def control(self, rooms, state):
        # Rozhodnutí a seznamy místností čteme ze skutečné minutové automatizace.
        for block in self.thermostat_rule['action']:
            condition = block['if'][0]
            active = any(state == c['state'] for c in condition['conditions'])
            for action in block['then' if active else 'else']:
                if action.get('action') == 'climate.set_preset_mode':
                    self.preset(rooms, action['target']['entity_id'], action['data']['preset_mode'])

    def test_repairs_restored_away_and_uses_configured_temperatures(self):
        targets = self.reset[0]['variables']['termostaty']
        for mode in ('on', 'off', 'unknown', 'unavailable'):
            with self.subTest(mode=mode):
                rooms = {e: {'preset': 'away', 'target': self.configs[e]['target_temp'],
                             'normal': self.configs[e]['target_temp']}
                         for e in self.expand(targets)}
                # Obě operace načteme z opraveného skriptu, nikoli ze seznamu v testu.
                for action in self.reset[1:3]:
                    self.preset(rooms, targets, action['data']['preset_mode'])
                self.control(rooms, mode)
                for e, room in rooms.items():
                    expected = self.configs[e]['target_temp' if mode == 'on' else 'away_temp']
                    self.assertEqual(room['target'], expected, e)
                    self.assertEqual(room['preset'], 'none' if mode == 'on' else 'away', e)

    def test_normal_mode_preserves_custom_target(self):
        targets = self.reset[0]['variables']['termostaty']
        rooms = {e: {'preset': 'none', 'target': self.configs[e]['target_temp'] + 0.5,
                     'normal': self.configs[e]['target_temp']}
                 for e in self.expand(targets)}
        for action in self.reset[1:3]:
            self.preset(rooms, targets, action['data']['preset_mode'])
        self.control(rooms, 'on')
        for e, room in rooms.items():
            self.assertEqual(room['target'], self.configs[e]['target_temp'] + 0.5)

    def test_startup_only_reset_has_no_direct_temperature_or_boost_writes(self):
        self.assertEqual([a['data']['preset_mode'] for a in self.reset[1:3]], ['away', 'none'])
        self.assertTrue(all(a['action'] == 'climate.set_preset_mode' for a in self.reset[1:3]))
        self.assertEqual(self.reset[3]['target']['entity_id'], 'automation.topeni_termostaty_nastav')
        self.assertNotIn('climate.set_temperature', str(self.reset))
        self.assertNotIn('input_boolean.turn_', str(self.reset))
        self.assertNotIn('script.obnov_mod_topeni', str(self.thermostat_rule))
        startup = next(a for a in self.automations if a['alias'] == 'HA Start')
        self.assertEqual(startup['action'][0]['data']['entity_id'], 'script.restart_modu_topeni')
        self.assertEqual(self.scripts['restart_modu_topeni']['sequence'][-1]['action'],
                         'script.obnov_mod_topeni')
        self.assertEqual(self.scripts['obnov_mod_topeni']['mode'], 'single')
