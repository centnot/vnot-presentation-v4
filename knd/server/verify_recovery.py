"""Explicit cold-recovery test; always attempts to restore the frozen state.
Run only when a freeze/thaw test is needed, not while a generation job is running.
The local validation receipt contains infrastructure IDs and is git-ignored.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time
from cloud_control import TARGET_PATH, load_target

REMOTE = r'''
from pathlib import Path
import json,subprocess,time,urllib.request
base=Path('/srv/owl')
deadline=time.time()+120
while time.time()<deadline:
 try:
  with urllib.request.urlopen('http://127.0.0.1:8188/system_stats',timeout=5) as r:stats=json.load(r)
  break
 except Exception:time.sleep(3)
else:raise RuntimeError('ComfyUI did not start automatically after thaw')
assert subprocess.run(['systemctl','is-active','owl-comfy.service'],capture_output=True,text=True).stdout.strip()=='active'
plan=json.loads((base/'logs/model-plan.json').read_text())
assert all((base/'ComfyUI/models'/n).is_file() and (base/'ComfyUI/models'/n).stat().st_size==s for n,s in plan['files'].items())
assert (base/'logs/models-cached.json').is_file()
cache_state=subprocess.run(['systemctl','show','owl-model-cache.service','--property=ActiveState,ConditionResult,ExecMainStartTimestamp'],capture_output=True,text=True,check=True).stdout
assert 'ActiveState=inactive' in cache_state and 'ConditionResult=no' in cache_state,'Model cache should be skipped on thaw'
with urllib.request.urlopen('http://127.0.0.1:8188/queue',timeout=5) as r:q=json.load(r)
assert not q['queue_running'] and not q['queue_pending']
state=json.loads((base/'logs/dashboard-status.json').read_text());assert state['stage']=='complete'
file=base/'out'/state['result']['files'][0]
probe=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,nb_frames:format=duration','-of','json',str(file)],capture_output=True,text=True,check=True,timeout=20).stdout)
gpu=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],capture_output=True,text=True,check=True).stdout.strip()
print(json.dumps({'autostart_verified':True,'model_cache_skipped':True,'cached_model_files':len(plan['files']),'model_bytes':plan['bytes'],'model_revision':plan['revision'],'gpu':gpu,'generation':state['result'],'video':probe,'queue_empty':True}),flush=True)
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',default=str(TARGET_PATH))
    args=parser.parse_args()
    SERVER=Path(__file__).resolve().parent
    ROOT=SERVER.parent
    TARGET=load_target(args.target)
    CONTROL=[sys.executable,str(SERVER/'cloud_control.py'),'--target',TARGET['_config_path']]
    SSH=['ssh','-i',TARGET['ssh_key_path'],'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=5',TARGET['ssh_user']+'@'+TARGET['ip']]
    receipt={'server_id':TARGET['server_id'],'ip':TARGET['ip'],'stage':'verifying_recovery'}
    try:
        subprocess.run([*CONTROL,'thaw'],cwd=ROOT,check=True)
        deadline=time.time()+120
        while time.time()<deadline:
            result=subprocess.run([*SSH,'true'],capture_output=True,text=True,timeout=10)
            if result.returncode==0:break
            time.sleep(3)
        else:raise RuntimeError('SSH did not return after thaw')
        result=subprocess.run([*SSH,'python3','-'],input=REMOTE,capture_output=True,text=True,timeout=180)
        if result.returncode:
            print(result.stderr[-2000:],flush=True)
            raise RuntimeError('Recovery verification failed')
        receipt.update(json.loads(result.stdout))
        receipt['stage']='recovery_verified'
        (SERVER/'validation.local.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Autostart, GPU, persistent models and saved video verified after thaw.',flush=True)
    finally:
        try:
            subprocess.run([*SSH,'systemctl stop owl-comfy.service'],capture_output=True,text=True,timeout=40)
        except (subprocess.TimeoutExpired, OSError):
            print('Could not confirm service stop; attempting the guarded freeze check.',flush=True)
        result=subprocess.run([*CONTROL,'freeze'],cwd=ROOT,capture_output=True,text=True,timeout=360)
        print(result.stdout,flush=True)
        if result.returncode:
            print(result.stderr[-1500:],flush=True)
            receipt['stage']='freeze_unconfirmed'
            (SERVER/'validation.local.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            raise RuntimeError('Could not confirm final freeze')
        state=json.loads(result.stdout.strip().splitlines()[-1])
        assert state['status']=='SHELVED_OFFLOADED' and state.get('OS-EXT-STS:task_state') is None
        receipt['final_status']=state['status']
        receipt['stage']='complete' if receipt.get('autostart_verified') else 'verification_failed_but_frozen'
        (SERVER/'validation.local.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Finished; VM is frozen.',flush=True)

if __name__=='__main__':
    main()
