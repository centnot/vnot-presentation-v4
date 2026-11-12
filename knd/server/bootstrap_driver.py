"""Install the Ubuntu-recommended NVIDIA open driver; probe before rebooting."""
from pathlib import Path
import json
import os
import platform
import re
import subprocess

result = subprocess.run(['ubuntu-drivers','devices'],capture_output=True,text=True,check=True)
match = re.search(r'driver\s*:\s*(nvidia-driver-\d+(?:-server)?-open)\s+[^\n]*recommended',result.stdout)
if not match:
    raise SystemExit('No recommended NVIDIA open driver found; inspect ubuntu-drivers devices.')
driver = match.group(1)
print('Installing recommended driver:',driver,flush=True)
with Path('/var/log/knd-gpu-driver.log').open('a') as log:
    result = subprocess.run(['apt-get','install','-y',driver,'linux-headers-'+platform.release()],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'})
    if result.returncode:
        raise SystemExit('Driver installation failed; see /var/log/knd-gpu-driver.log')
subprocess.run(['modprobe','nvidia'],capture_output=True,text=True)
result = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],capture_output=True,text=True)
state = {'driver_package':driver,'reboot_required':result.returncode!=0,'gpu':result.stdout.strip()}
Path(__file__).resolve().with_name('driver-status.local.json').write_text(json.dumps(state,indent=2))
print(json.dumps(state),flush=True)
