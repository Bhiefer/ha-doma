"""Obnova bridge: jeden pokus, přežití restartu HA a stabilní návrat."""
import datetime as dt
from types import SimpleNamespace
import unittest

import jinja2
import test_checks as base


class ZigbeeRecoveryTests(unittest.TestCase):
    automation_id = '1767652230337'
    lock_key = 'zigbee_evans_obnova_pokus'
    script_key = 'zigbee2mqtt_reboot'
    command_key = 'zigbee2mqtt_reboot_over_ssh'
    command = 'python3 /config/tools/zigbee2mqtt_ssh.py reboot'
    @classmethod
    def setUpClass(cls):
        cls.config = base.check.load_yaml(base.ROOT / 'configuration.yaml')
        cls.automation = next(a for a in base.check.load_yaml(base.ROOT / 'automations.yaml')
                              if a['id'] == cls.automation_id)
        cls.branches = cls.automation['actions'][1]['choose']
        cls.now = dt.datetime(2026, 10, 23, 12, tzinfo=dt.timezone.utc)

    def evaluate(self, branch, state, age, lock):
        bridge = None if state is None else SimpleNamespace(
            state=state, last_changed=self.now - dt.timedelta(seconds=age))
        entity = self.automation['variables']['bridge_entity']
        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        template = env.from_string(self.branches[branch]['conditions'][0]['value_template'])
        return template.render(
            bridge_entity=entity, states={entity: bridge}, now=lambda: self.now,
            as_timestamp=lambda value: value.timestamp(),
            is_state=lambda entity, value: lock == value,
        ).strip() == 'True'

    def test_only_known_bridge_outage_after_ten_minutes(self):
        for state in ('on', 'off', 'unknown', 'unavailable', None):
            for age in (0, 599, 600, 601):
                for lock in ('off', 'on', 'unknown', 'unavailable'):
                    with self.subTest(state=state, age=age, lock=lock):
                        expected = state in ('off', 'unknown', 'unavailable') and age >= 600 and lock == 'off'
                        self.assertEqual(self.evaluate(1, state, age, lock), expected)

    def test_short_recovery_does_not_unlock_restarts(self):
        for state in ('on', 'off', 'unknown', 'unavailable', None):
            for age in (0, 599, 600, 601):
                for lock in ('off', 'on', 'unknown', 'unavailable'):
                    with self.subTest(state=state, age=age, lock=lock):
                        expected = state == 'on' and age >= 600 and lock == 'on'
                        self.assertEqual(self.evaluate(0, state, age, lock), expected)

    def test_no_repeat_on_failure_or_short_online_flap(self):
        self.assertTrue(self.evaluate(1, 'unavailable', 600, 'off'))
        # První akce pokusu zamkne stav; stejný zámek se obnoví i po startu HA.
        for outage_age in (601, 3600, 86400):
            self.assertFalse(self.evaluate(1, 'unavailable', outage_age, 'on'))
        self.assertFalse(self.evaluate(0, 'on', 599, 'on'))
        self.assertFalse(self.evaluate(1, 'off', 600, 'on'))
        self.assertTrue(self.evaluate(0, 'on', 600, 'on'))
        # Teprve po stabilní obnově je nový samostatný výpadek znovu řešitelný.
        self.assertTrue(self.evaluate(1, 'off', 600, 'off'))

    def test_lock_is_restored_not_reset_at_ha_start(self):
        helper = self.config['input_boolean'][self.lock_key]
        self.assertNotIn('initial', helper)

    def test_startup_periodic_checks_and_single_execution(self):
        triggers = self.automation['triggers']
        self.assertTrue(any(t.get('trigger') == 'homeassistant' and t.get('id') == 'start_ha'
                            for t in triggers))
        self.assertTrue(any(t.get('trigger') == 'time_pattern' and t.get('minutes') == '/1'
                            for t in triggers))
        state_trigger = next(t for t in triggers if t['trigger'] == 'state')
        self.assertEqual(state_trigger['entity_id'], self.automation['variables']['bridge_entity'])
        self.assertIsNone(state_trigger['to'])
        startup = self.automation['actions'][0]
        self.assertEqual(startup['if'][0], {'condition': 'trigger', 'id': 'start_ha'})
        self.assertEqual(startup['then'][0]['delay'], '00:10:00')
        self.assertEqual(self.automation['mode'], 'single')

    def test_one_existing_server_reboot_after_locking(self):
        actions = self.branches[1]['sequence']
        self.assertEqual(actions[0]['action'], 'input_boolean.turn_on')
        self.assertEqual(actions[0]['target']['entity_id'], 'input_boolean.' + self.lock_key)
        reboots = [a for a in actions if a.get('action') == 'script.' + self.script_key]
        self.assertEqual(len(reboots), 1)
        self.assertTrue(reboots[0]['continue_on_error'])
        self.assertFalse(any(a.get('action') == 'mqtt.publish' for a in actions))
        scripts = base.check.load_yaml(base.ROOT / 'scripts.yaml')
        self.assertEqual(scripts[self.script_key]['sequence'][0]['service'],
                         'shell_command.' + self.command_key)
        self.assertEqual(self.config['shell_command'][self.command_key],
                         self.command)
        wait = next(a for a in actions if 'wait_template' in a)
        self.assertEqual(wait['timeout'], '00:05:00')
        self.assertTrue(wait['continue_on_timeout'])
        self.assertFalse(any('repeat' in a for a in actions))
        self.assertEqual(actions[-1]['action'], 'persistent_notification.create')


class ZigbeeDomaRecoveryTests(ZigbeeRecoveryTests):
    # Stejné hranice a selhání se ověřují proti skutečným šablonám druhého bridge.
    automation_id = '1767652230338'
    lock_key = 'zigbee_doma_obnova_pokus'
    script_key = 'zigbee2mqtt_doma_reboot'
    command_key = 'zigbee2mqtt_doma_reboot_over_ssh'
    command = 'python3 /config/tools/zigbee2mqtt_ssh.py reboot doma'

    def test_bridges_and_locks_are_separate(self):
        self.assertEqual(self.automation['variables']['bridge_entity'],
                         'binary_sensor.zigbee2mqtt_bridge_connection_state')
        self.assertNotIn('zigbee_evans', str(self.automation))
        self.assertNotIn('connection_state_2', str(self.automation))
