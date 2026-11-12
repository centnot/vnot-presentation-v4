"""Run one bounded KND validation job as soon as its exact weights are cached."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path('/srv/owl')
STATUS = BASE / 'logs/dashboard-status.json'
JOBS = Path(sys.argv[1]) if len(sys.argv)>1 else BASE/'jobs_knd_dashboard.json'
RUN_NAME = json.loads(JOBS.read_text())['jobs'][0]['name']

def status(stage, **extra):
    STATUS.write_text(json.dumps({'stage':stage,'time':time.time(),**extra},ensure_ascii=False,indent=2))

status('waiting_for_weights')
deadline = time.time() + 1800
ready = False
while time.time() < deadline:
    plan = json.loads((BASE / 'logs/model-plan.json').read_text())
    needed = list(plan['files'])[:5]
    if all((BASE / 'ComfyUI/models' / name).is_file() and (BASE / 'ComfyUI/models' / name).stat().st_size == plan['files'][name] for name in needed):
        ready = True
        break
    time.sleep(5)
if not ready:
    status('error',error='Required weights were not cached within 30 minutes')
    raise SystemExit(1)

status('running')
command = [str(BASE / 'ComfyUI/.venv/bin/python'),'-u',str(BASE / 'owl_run.py'),str(JOBS)]
with (BASE / 'logs/dashboard-generation.log').open('a') as log:
    try:
        result = subprocess.run(command,cwd=BASE,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'OWL':str(BASE)},timeout=1800)
    except subprocess.TimeoutExpired:
        status('error',error='Generation runner exceeded 30 minutes; inspect the ComfyUI queue')
        raise SystemExit(1)
runs = BASE / 'logs/runs.jsonl'
records = [json.loads(line) for line in runs.read_text().splitlines()] if runs.exists() else []
records = [record for record in records if record['tag'].startswith(RUN_NAME+'_')]
if result.returncode == 0 and records and records[-1].get('ok'):
    status('complete',result=records[-1])
else:
    status('error',returncode=result.returncode,result=records[-1] if records else None)
    raise SystemExit(1)
