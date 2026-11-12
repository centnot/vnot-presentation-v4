"""Initial packages for a clean Ubuntu GPU VM. No credentials are stored here."""
from pathlib import Path
import os
import subprocess

log = Path('/var/log/knd-bootstrap.log')
packages = ['ubuntu-drivers-common','git','curl','ffmpeg','python3-venv','python3-pip','unzip','ca-certificates','build-essential']
with log.open('a') as stream:
    for command in [['apt-get','update'],['apt-get','install','-y',*packages]]:
        result = subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'})
        if result.returncode:
            print('Base package setup failed; see',log,flush=True)
            raise SystemExit(result.returncode)
print('Base packages installed.',flush=True)
