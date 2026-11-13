"""Run a command or copy files on the KND GPU server with the local target.json; nothing secret is printed.

  python gpu_remote.py run "systemctl is-active owl-comfy.service"
  python gpu_remote.py put LOCAL REMOTE        (scp -r to the server)
  python gpu_remote.py get REMOTE LOCAL        (scp -r from the server)
"""
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import sys

TARGET_PATH = Path(__file__).with_name('target.json')


def target():
    """Read only the SSH part of target.json; paths resolve like in cloud_control.py."""
    if not TARGET_PATH.is_file():
        raise SystemExit('Missing local target.json next to this script. No server was contacted.')
    data = json.loads(TARGET_PATH.read_text('utf-8-sig'))
    # Older target.json files have no ssh_key_path; the first setup used this fixed key name.
    key = Path(data.get('ssh_key_path') or '~/.ssh/knd_selectel_ed25519').expanduser()
    key = key if key.is_absolute() else (TARGET_PATH.parent / key)
    user = str(data.get('ssh_user', 'root'))
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', user):
        raise SystemExit('Invalid ssh_user in target.json.')
    return str(key.resolve()), f'{user}@{ipaddress.ip_address(data["ip"])}'


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('run', 'put', 'get'):
        raise SystemExit(__doc__)
    key, host = target()
    options = ['-i', key, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
               '-o', 'ServerAliveInterval=30', '-o', 'StrictHostKeyChecking=accept-new']
    operation, *args = sys.argv[1:]
    if operation == 'run':
        command = ['ssh', *options, host, args[0]]
    elif operation == 'put':
        command = ['scp', *options, '-r', args[0], f'{host}:{args[1]}']
    else:
        command = ['scp', *options, '-r', f'{host}:{args[0]}', args[1]]
    raise SystemExit(subprocess.run(command).returncode)


if __name__ == '__main__':
    main()
