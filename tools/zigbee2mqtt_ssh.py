#!/usr/bin/env python3
"""SSH obnova Evans a Doma bez sshpass; heslo není v argumentech ani logu."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml


def ssh_command(mode, secrets, root):
    """Povoleny jsou pouze kontrola a jeden reboot, bez libovolného SSH příkazu."""
    host = str(secrets['zigbee2mqtt_ssh_host'])
    user = str(secrets['zigbee2mqtt_ssh_user'])
    port = int(secrets['zigbee2mqtt_ssh_port'])
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', host):
        raise ValueError('Neplatný SSH host')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', user) or not 1 <= port <= 65535:
        raise ValueError('Neplatný SSH uživatel nebo port')
    commands = {
        'check': 'cat /proc/sys/kernel/random/boot_id; cat /proc/uptime; '
                 'sudo -n -l /sbin/reboot >/dev/null 2>&1; echo REBOOT_ALLOWED=$?',
        'reboot': 'sudo -n /sbin/reboot',
    }
    remote = commands[mode]
    # Klíč serveru si uložíme trvale. Změněný klíč už SSH odmítne.
    known_hosts = root / '.ssh' / 'zigbee2mqtt_known_hosts'
    return [
        shutil.which('ssh') or 'ssh', '-T', '-o', 'ConnectTimeout=10',
        '-o', 'ConnectionAttempts=1', '-o', 'NumberOfPasswordPrompts=1',
        '-o', 'PubkeyAuthentication=no', '-o', 'PreferredAuthentications=password,keyboard-interactive',
        '-o', 'StrictHostKeyChecking=accept-new', '-o', f'UserKnownHostsFile={known_hosts}',
        '-p', str(port), f'{user}@{host}', remote,
    ]


def run(mode, root, profile='evans'):
    stored = yaml.safe_load((root / 'secrets.yaml').read_text())
    # Pevný výběr oddělených přístupů; chybějící Doma údaje nesmí použít Evans.
    prefix = {'evans': 'zigbee2mqtt_ssh_', 'doma': 'zigbee2mqtt_doma_ssh_'}[profile]
    secrets = {'zigbee2mqtt_ssh_' + k: stored[prefix + k]
               for k in ('host', 'port', 'user', 'pass')}
    command = ssh_command(mode, secrets, root)
    known_hosts_dir = root / '.ssh'
    known_hosts_dir.mkdir(mode=0o700, exist_ok=True)
    env = os.environ.copy()
    # OpenSSH spustí tento soubor samostatně jen pro vyžádání hesla.
    # Heslo je pouze v prostředí potomka; není součástí shell_command ani trace HA.
    env.update(SSH_ASKPASS=str(Path(__file__).resolve()), SSH_ASKPASS_REQUIRE='force',
               Z2M_SSH_ASKPASS='1', Z2M_SSH_PASSWORD=str(secrets['zigbee2mqtt_ssh_pass']))
    try:
        result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=35,
                                start_new_session=True)
    except subprocess.TimeoutExpired:
        print('SSH překročilo časový limit; bez dalšího pokusu.', file=sys.stderr)
        return 1
    # Nevypisovat výstup SSH: může obsahovat banner či přihlašovací údaje.
    if result.returncode:
        print(f'SSH skončilo kódem {result.returncode}; bez dalšího pokusu.', file=sys.stderr)
        return 1
    if mode == 'check':
        lines = result.stdout.splitlines()
        boot_id = next((s for s in lines if re.fullmatch(r'[0-9a-f-]{36}', s)), None)
        allowed = 'REBOOT_ALLOWED=0' in lines
        if boot_id is None:
            print('SSH kontrola nevrátila identifikátor startu serveru.', file=sys.stderr)
            return 1
        print(json.dumps({'boot_id': boot_id, 'reboot_allowed': allowed}))
        return 0 if allowed else 1
    print('SSH příkaz reboot dokončen; skutečný restart ověř podle nového boot_id a bridge.')
    return 0


def main():
    if os.environ.get('Z2M_SSH_ASKPASS') == '1':
        sys.stdout.write(os.environ['Z2M_SSH_PASSWORD'] + '\n')
        return 0
    if (len(sys.argv) not in (2, 3) or sys.argv[1] not in ('check', 'reboot')
            or (len(sys.argv) == 3 and sys.argv[2] not in ('evans', 'doma'))):
        print('Použití: zigbee2mqtt_ssh.py check|reboot [evans|doma]', file=sys.stderr)
        return 1
    try:
        return run(sys.argv[1], Path(__file__).resolve().parents[1],
                   sys.argv[2] if len(sys.argv) == 3 else 'evans')
    except (OSError, ValueError, KeyError, yaml.YAMLError):
        print('SSH se nepodařilo připravit; ověř secrets, OpenSSH a přístupové soubory.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
