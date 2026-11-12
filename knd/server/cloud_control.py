"""Control this one Selectel VM with user-supplied OpenStack credentials.

Credentials remain in memory. OpenRC is parsed as data and is never executed.
Usage: python cloud_control.py status|freeze|thaw [--target PATH] [--credentials PATH]
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shlex
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

TARGET_PATH = Path(__file__).with_name('target.json')
TARGET = {}
SERVER_ID = SERVER_IP = REGION = None

def load_target(path=TARGET_PATH):
    """Load an explicit local configuration; there is deliberately no default VM."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SystemExit('Missing local target.json. Copy target.example.json to target.json, fill it from your private server records, or pass --target PATH. No server was contacted.')
    try:
        data = json.loads(path.read_text('utf-8-sig'))
        for name in ['server_id', 'ip', 'region', 'project_id']:
            if not str(data.get(name, '')).strip() or 'PLACEHOLDER' in str(data[name]):
                raise ValueError(name)
        data['server_id'] = str(uuid.UUID(data['server_id']))
        data['ip'] = str(ipaddress.ip_address(data['ip']))
        data['project_id'] = uuid.UUID(data['project_id']).hex
        data['region'] = str(data['region']).strip()
        for name in ['credentials_path', 'ssh_key_path']:
            if data.get(name):
                local = Path(data[name]).expanduser()
                data[name] = str((path.parent / local).resolve() if not local.is_absolute() else local.resolve())
        data['ssh_user'] = str(data.get('ssh_user', 'root'))
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', data['ssh_user']):
            raise ValueError('ssh_user')
        if not data.get('ssh_key_path'):
            raise ValueError('ssh_key_path')
        data['_config_path'] = str(path)
        return data
    except (ValueError, TypeError, KeyError):
        raise SystemExit('Invalid local target.json. Fill server_id, ip, region, project_id and ssh_key_path; do not leave PLACEHOLDER values. No server was contacted.')

def trusted(url):
    parsed = urllib.parse.urlparse(url)
    assert parsed.scheme == 'https' and not parsed.username and not parsed.password
    assert any((parsed.hostname or '').endswith('.'+domain) or parsed.hostname == domain for domain in ['selvpc.ru','selectel.ru','selcloud.ru']), 'Expected a Selectel API endpoint'
    return url.rstrip('/')

def credentials(path, cloud):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise SystemExit('OpenStack credentials file is absent. Keep it outside the repository and set credentials_path or --credentials PATH. No server was contacted.')
    text = path.read_text('utf-8-sig')
    if Path(path).suffix.lower() in ['.yaml','.yml']:
        import yaml
        clouds = yaml.safe_load(text)['clouds']
        if not cloud:
            assert len(clouds) == 1, 'Specify --cloud when several clouds exist'
            cloud = next(iter(clouds))
        return clouds[cloud]['auth'], clouds[cloud].get('region_name',REGION)
    if Path(path).suffix.lower() == '.json':
        data = json.loads(text)
        return data.get('auth',data),data.get('region_name',REGION)
    values = {}
    for line in text.splitlines():
        match = re.fullmatch(r'\s*(?:export\s+)?(OS_[A-Z0-9_]+)\s*=(.*)\s*',line)
        if not match: continue
        if match.group(1) in ['OS_PASSWORD','OS_PASSWORD_INPUT']: continue
        parts = shlex.split(match.group(2),comments=True)
        if len(parts) == 1:
            value = re.sub(r'\$\{?(OS_[A-Z0-9_]+)\}?',lambda m:values[m.group(1)[3:].lower()],parts[0])
            assert '`' not in value and '$' not in value, 'Unsupported RC reference'
            values[match.group(1)[3:].lower()] = value
    service_file = Path(path).parent/'service_member.txt'
    if service_file.is_file():
        service = {}
        for line in service_file.read_text('utf-8-sig').splitlines():
            match = re.fullmatch(r'\s*(username|password)\s*[:=]\s*(.*?)\s*',line,re.I)
            if match: service[match.group(1).lower()] = match.group(2)
        assert service.get('username') == values.get('username'), 'Service user does not match RC'
        values['password'] = service['password']
    else:
        for line in text.splitlines():
            match = re.fullmatch(r'\s*(?:export\s+)?OS_PASSWORD\s*=(.*)\s*',line)
            if match:
                parts = shlex.split(match.group(1),comments=True)
                if len(parts) == 1 and '$' not in parts[0] and '`' not in parts[0]: values['password'] = parts[0]
    return values,values.get('region_name',REGION)

class Selectel:
    def __init__(self, auth, region):
        try:
            import certifi
            self.context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            self.context = ssl.create_default_context()
        endpoint = trusted(auth['auth_url'])
        if not endpoint.endswith('/v3'): endpoint += '/v3'
        if auth.get('application_credential_id'):
            identity = {'methods':['application_credential'],'application_credential':{'id':auth['application_credential_id'],'secret':auth['application_credential_secret']}}
            body = {'auth':{'identity':identity}}
        else:
            domain = {'id':auth['user_domain_id']} if auth.get('user_domain_id') else {'name':auth['user_domain_name']}
            identity = {'methods':['password'],'password':{'user':{'name':auth['username'],'domain':domain,'password':auth['password']}}}
            if auth.get('project_id') or auth.get('tenant_id'):
                project = {'id':auth.get('project_id',auth.get('tenant_id'))}
            else:
                domain = {'id':auth['project_domain_id']} if auth.get('project_domain_id') else {'name':auth['project_domain_name']}
                project = {'name':auth.get('project_name',auth.get('tenant_name')),'domain':domain}
            body = {'auth':{'identity':identity,'scope':{'project':project}}}
        request = urllib.request.Request(endpoint+'/auth/tokens',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(request,timeout=30,context=self.context) as response:
            self.token = response.headers['X-Subject-Token']
            token_data = json.load(response)['token']
            self.project_id = token_data['project']['id']
            if auth.get('project_id'): assert self.project_id == auth['project_id'], 'Authenticated project mismatch'
            catalog = token_data['catalog']
            self.catalog = catalog
        endpoints = [e for service in catalog if service['type']=='compute' for e in service['endpoints'] if e['interface']=='public' and region in [e.get('region'),e.get('region_id')]]
        assert len(endpoints) == 1, 'Expected one compute endpoint for the selected region'
        self.endpoint = trusted(endpoints[0]['url'])

    def call(self, path, body=None):
        request = urllib.request.Request(self.endpoint+path,data=json.dumps(body).encode() if body is not None else None,headers={'X-Auth-Token':self.token,'Content-Type':'application/json'},method='POST' if body is not None else 'GET')
        with urllib.request.urlopen(request,timeout=30,context=self.context) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def server(self):
        data = self.call('/servers/'+SERVER_ID)['server']
        assert data['id'] == SERVER_ID
        assert data['tenant_id'] == self.project_id, 'Server project mismatch'
        addresses = [a['addr'] for group in data.get('addresses',{}).values() for a in group]
        assert SERVER_IP in addresses, 'VM addresses no longer match the expected server'
        return data

def safe_state(data):
    return {key:data.get(key) for key in ['id','name','status','OS-EXT-STS:vm_state','OS-EXT-STS:task_state']}

def verify_idle():
    script = """
import json,urllib.request,subprocess
from pathlib import Path
base=Path('/srv/owl')
if not base.exists() and not Path('/dev/nvidia0').exists():
 print('Ready to freeze: new unconfigured VM, no NVIDIA compute device initialized.')
 raise SystemExit(0)
active=subprocess.run(['systemctl','is-active','owl-comfy.service'],capture_output=True,text=True).stdout.strip()
if active=='active':
 with urllib.request.urlopen('http://127.0.0.1:8188/queue',timeout=10) as r:queue=json.load(r)
 assert not queue['queue_running'] and not queue['queue_pending'],'ComfyUI has unfinished work'
else:
 assert active=='inactive','Inspect ComfyUI service state'
 gpu=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],capture_output=True,text=True,check=True)
 assert not gpu.stdout.strip(),'GPU has another compute process'
state=json.loads((base/'logs/dashboard-status.json').read_text())
assert state['stage']=='complete','Validation or generation has not completed successfully'
plan=json.loads((base/'logs/model-plan.json').read_text())
assert all((base/'ComfyUI/models'/n).is_file() and (base/'ComfyUI/models'/n).stat().st_size==s for n,s in plan['files'].items()),'Model downloads are incomplete'
print('Ready to freeze: queue empty, validation complete, weights cached.')
"""
    key = Path(TARGET['ssh_key_path'])
    result = subprocess.run(['ssh','-i',str(key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=10',TARGET['ssh_user']+'@'+SERVER_IP,'python3','-'],input=script,text=True,capture_output=True,timeout=30)
    assert result.returncode == 0, 'Server readiness check failed; inspect SSH and unfinished work before freezing'
    print(result.stdout.strip(),flush=True)

def main():
    global TARGET, SERVER_ID, SERVER_IP, REGION
    parser = argparse.ArgumentParser()
    parser.add_argument('operation',choices=['status','freeze','thaw'])
    parser.add_argument('--target',default=str(TARGET_PATH),help='Local VM configuration; never committed')
    parser.add_argument('--credentials',help='OpenStack credentials outside the repository')
    parser.add_argument('--cloud')
    args = parser.parse_args()
    TARGET = load_target(args.target)
    SERVER_ID, SERVER_IP, REGION = TARGET['server_id'], TARGET['ip'], TARGET['region']
    credential_path = args.credentials or TARGET.get('credentials_path')
    if not credential_path:
        parser.error('Set credentials_path in the local target file or pass --credentials PATH')
    auth,region = credentials(credential_path,args.cloud)
    auth['project_id'] = TARGET['project_id']
    region = REGION
    client = Selectel(auth,region)
    data = client.server()
    print(json.dumps(safe_state(data),ensure_ascii=False),flush=True)
    if args.operation == 'status': return
    target = 'SHELVED_OFFLOADED' if args.operation == 'freeze' else 'ACTIVE'
    if data['status'] == target and data.get('OS-EXT-STS:task_state') is None: return
    if args.operation == 'freeze':
        flavor = client.call('/flavors/'+data['flavor']['id'])['flavor']
        if flavor.get('disk',0):
            raise SystemExit('Selectel forbids freezing this VM: its flavor has a local root disk. Migrate to a network-root VM first.')
    assert data['status'] == ('ACTIVE' if args.operation == 'freeze' else 'SHELVED_OFFLOADED'), 'Inspect the current VM state before changing it'
    if args.operation == 'freeze': verify_idle()
    client.call('/servers/'+SERVER_ID+'/action',{'shelve' if args.operation == 'freeze' else 'unshelve':None})
    deadline = time.time()+300
    while time.time() < deadline:
        time.sleep(5)
        data = client.server()
        if data['status'] == target and data.get('OS-EXT-STS:task_state') is None:
            print(json.dumps(safe_state(data),ensure_ascii=False),flush=True)
            return
        assert data['status'] != 'ERROR', 'VM entered ERROR state'
    raise RuntimeError('Operation is still pending; inspect Selectel before retrying')

if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as error:
        raise SystemExit(f'Selectel API HTTP {error.code}; credential values are not printed.')
    except urllib.error.URLError as error:
        raise SystemExit(f'Selectel connection failed: {type(error.reason).__name__}; credential values are not printed.')
