import os, sys, time, json, http.cookiejar, urllib.request, urllib.error, subprocess
from dotenv import load_dotenv
load_dotenv()
os.environ.setdefault('ENKRIPSIH_PASSWORD', 'npg_z25gJGferdMK')
os.environ.setdefault('ENKRIPSIH_KEYBCA_SECRET', 'ugCC-4DHQ8fXxcAJ7hkO17TWkp2oi3-s6AUc1GVzf0w')
os.environ.setdefault('ENKRIPSIH_DB_PASSPHRASE', 'muhammadakhdaan2005')

p = subprocess.Popen(
    [sys.executable, r'E:\enkripsih\_srv_launch.py'],
    cwd=r'E:\enkripsih',
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)

# Wait up to 55s (lifespan ~20s + binding)
for i in range(55):
    time.sleep(1)
    if p.poll() is not None:
        err = p.stderr.read()
        print(f'died ({p.returncode}): {err[:400]}', flush=True)
        sys.exit(1)
    try:
        urllib.request.urlopen('http://127.0.0.1:8000/api/auth/commander-status', timeout=2)
        print(f'HTTP ready after {i+1}s', flush=True)
        break
    except Exception:
        if i in (5, 15, 25, 35, 45):
            print(f'  ...{i}s', flush=True)
else:
    err = p.stderr.read()[:500]
    print(f'TIMEOUT. stderr: {err}', flush=True)
    p.terminate()
    sys.exit(1)

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    req.timeout = 25
    try:
        return json.loads(opener.open(req).read())
    except urllib.error.HTTPError as e:
        return {'error': True, 'code': e.code, 'detail': e.read().decode()}

def get(url):
    req = urllib.request.Request(url); req.timeout = 15
    return json.loads(opener.open(req).read())

# login
login = post('http://127.0.0.1:8000/api/auth/login',
             {'username': 'cmd', 'password': 'npg_z25gJGferdMK'})
print('login:', login.get('success'), flush=True)

# agent keys
ak = get('http://127.0.0.1:8000/api/agent-keys').get('agent_keys', [])
print(f'agents ({len(ak)}):')
for a in ak:
    print(f"  {a['name']} -> {a['recipient_id']}", flush=True)

# encrypt to each agent
for a in ak:
    name = a['name']
    rid = a['recipient_id']
    res = post('http://127.0.0.1:8000/api/messages/encrypt-agent',
               {'plaintext': f'Halo {name}', 'recipient_id': rid, 'save': True})
    ok = res.get('success')
    msg_id = res.get('saved', {}).get('message_id', '')
    detail = res.get('detail', '')
    print(f'{name}: success={ok} msg_id={msg_id} detail={detail}', flush=True)

print('\nDONE', flush=True)
p.terminate()
