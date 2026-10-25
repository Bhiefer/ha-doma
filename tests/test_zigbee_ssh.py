"""SSH bez sítě: heslo mimo argumenty, jeden pokus, chyby a kontrola boot_id."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import yaml

SPEC = importlib.util.spec_from_file_location(
    'zigbee_ssh', Path(__file__).resolve().parents[1] / 'tools/zigbee2mqtt_ssh.py')
ssh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ssh)


class ZigbeeSSHTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/config')
        self.secrets = dict(zigbee2mqtt_ssh_host='10.0.0.41', zigbee2mqtt_ssh_port=22,
                            zigbee2mqtt_ssh_user='test_user', zigbee2mqtt_ssh_pass='dummy$"password')

    def invoke(self, mode, result=None, error=None, profile='evans'):
        out, err = io.StringIO(), io.StringIO()
        with (patch.object(ssh.subprocess, 'run', return_value=result, side_effect=error) as mock,
              patch.object(Path, 'read_text', return_value=yaml.safe_dump(self.secrets)),
              patch.object(Path, 'mkdir')):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = ssh.run(mode, self.root, profile)
        return code, out.getvalue() + err.getvalue(), mock

    def test_reboot_once_without_password_in_arguments(self):
        code, output, mock = self.invoke('reboot', subprocess.CompletedProcess([], 0, '', ''))
        self.assertEqual(code, 0)
        mock.assert_called_once()
        args, options = mock.call_args
        self.assertEqual(args[0][-1], 'sudo -n /sbin/reboot')
        self.assertNotIn(self.secrets['zigbee2mqtt_ssh_pass'], ' '.join(args[0]) + output)
        self.assertEqual(options['env']['Z2M_SSH_PASSWORD'], self.secrets['zigbee2mqtt_ssh_pass'])
        self.assertEqual(options['env']['SSH_ASKPASS_REQUIRE'], 'force')
        self.assertTrue(options['start_new_session'])
        self.assertLess(options['timeout'], 60)

    def test_failure_does_not_leak_or_retry(self):
        code, output, mock = self.invoke('reboot', subprocess.CompletedProcess(
            [], 255, self.secrets['zigbee2mqtt_ssh_pass'], self.secrets['zigbee2mqtt_ssh_pass']))
        self.assertEqual(code, 1)
        mock.assert_called_once()
        self.assertNotIn(self.secrets['zigbee2mqtt_ssh_pass'], output)

    def test_timeout_does_not_retry(self):
        code, _, mock = self.invoke('reboot', error=subprocess.TimeoutExpired('ssh', 35))
        self.assertEqual(code, 1)
        mock.assert_called_once()

    def test_check_returns_boot_id_and_permission_without_reboot(self):
        boot = '12345678-1234-1234-1234-123456789abc'
        code, output, mock = self.invoke('check', subprocess.CompletedProcess(
            [], 0, boot + '\n123.00 456.00\nREBOOT_ALLOWED=0\n', ''))
        self.assertEqual(code, 0)
        self.assertIn(boot, output)
        self.assertNotIn('sudo -n /sbin/reboot', mock.call_args.args[0][-1])
        code, _, _ = self.invoke('check', subprocess.CompletedProcess([], 0, boot + '\nREBOOT_ALLOWED=1', ''))
        self.assertEqual(code, 1)

    def test_invalid_target_or_mode_never_executes(self):
        for key, value in (('zigbee2mqtt_ssh_host', '-oProxyCommand=bad'),
                           ('zigbee2mqtt_ssh_user', 'user;bad'), ('zigbee2mqtt_ssh_port', 0)):
            invalid = self.secrets | {key: value}
            with self.assertRaises(ValueError):
                ssh.ssh_command('reboot', invalid, self.root)
        with self.assertRaises(KeyError):
            ssh.ssh_command('arbitrary command', self.secrets, self.root)

    def test_ha_script_propagates_error_without_secret_data(self):
        import test_checks as base
        script = base.check.load_yaml(base.ROOT / 'scripts.yaml')['zigbee2mqtt_reboot']
        self.assertNotIn('data', script['sequence'][0])
        self.assertEqual(script['sequence'][0]['response_variable'], 'ssh_result')
        self.assertTrue(script['sequence'][1]['then'][0]['error'])

    def test_doma_profile_never_uses_evans_credentials(self):
        self.secrets.update(zigbee2mqtt_doma_ssh_host='10.0.0.58', zigbee2mqtt_doma_ssh_port=22,
                            zigbee2mqtt_doma_ssh_user='doma_user', zigbee2mqtt_doma_ssh_pass='doma_dummy')
        code, output, mock = self.invoke('reboot', subprocess.CompletedProcess([], 0, '', ''),
                                         profile='doma')
        self.assertEqual(code, 0)
        self.assertIn('doma_user@10.0.0.58', mock.call_args.args[0])
        self.assertNotIn('test_user@10.0.0.41', mock.call_args.args[0])
        self.assertEqual(mock.call_args.kwargs['env']['Z2M_SSH_PASSWORD'], 'doma_dummy')
        self.assertNotIn('doma_dummy', output)

    def test_missing_doma_credentials_do_not_fall_back(self):
        with self.assertRaises(KeyError):
            self.invoke('reboot', profile='doma')
