"""Read-only checks for a restored renderer before and after cutover."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

import httpx

PIN = '6992380c5e82f07f3e1fc46b90927b6f1c655407'
REMOTE = r'''
import hashlib,json,sqlite3,sys
from pathlib import Path
data=json.load(sys.stdin); root=Path('/MoneyPrinterTurbo/storage').resolve(); mismatches=[]
for item in data:
    path=(root/item['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        mismatches.append(item['path']); continue
    value=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''): value.update(chunk)
    if value.hexdigest()!=item['sha256']: mismatches.append(item['path'])
db=sqlite3.connect('file:/MoneyPrinterTurbo/storage/renderer-state.sqlite3?mode=ro',uri=True)
try:
    integrity=[r[0] for r in db.execute('PRAGMA integrity_check')]
    rows=db.execute('SELECT id,data FROM tasks ORDER BY id').fetchall()
finally: db.close()
print(json.dumps({'files_checked':len(data),'mismatches':mismatches,'integrity':integrity,
    'receipts':len(rows),'receipt_digest':hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()}))
'''


def verify(snapshot, container, base_url, key):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}', container):
        raise ValueError('Invalid renderer container name')
    url = urlsplit(base_url)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path not in ('', '/') or url.username or url.password or url.query or url.fragment:
        raise ValueError('Renderer restore verification requires a fixed loopback HTTP origin')
    base_url = base_url.rstrip('/')
    files = json.loads((snapshot / 'files.json').read_text())
    expected = json.loads((snapshot / 'report.json').read_text())
    result = subprocess.run(['docker', 'exec', '-i', container, 'python', '-c', REMOTE],
                            input=json.dumps(files), text=True, capture_output=True, check=True)
    stored = json.loads(result.stdout)
    if stored['mismatches'] or stored['integrity'] != ['ok'] or any(stored[k] != expected[k] for k in ('receipts', 'receipt_digest')):
        raise RuntimeError('Restored media or receipts differ from the verified snapshot')
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        denied = client.get(base_url + '/api/v1/capabilities')
        if denied.status_code != 401:
            raise RuntimeError('Renderer controls did not require authentication')
        response = client.get(base_url + '/api/v1/capabilities', headers={'Authorization': 'Bearer ' + key})
        response.raise_for_status()
        capabilities = response.json()
        if (capabilities.get('upstream_commit') != PIN or capabilities.get('upstream_version') != '1.3.9'
                or not all(capabilities.get(k) is True for k in ('durable_state_v1', 'control_api_auth_v1',
                    'automatic_publishing_disabled_for_approved_scenes', 'manual_clip_overrides_v1', 'initiative_scoped_automatic_broll_v1'))):
            raise RuntimeError('Renderer capabilities do not match the verified approved-only release')
        previews = [item for item in files if re.fullmatch(r'tasks/[0-9a-f-]+/final-[1-9][0-9]*\.(mp4|jpg)', item['path'])]
        checked = []
        # Include both video and thumbnail when present, plus a second video.
        selected = [next((p for p in previews if p['path'].endswith('.jpg')), None)] + [p for p in previews if p['path'].endswith('.mp4')][:2]
        for item in filter(None, selected):
            media = client.get(base_url + '/' + item['path'])
            if media.status_code != 200 or hashlib.sha256(media.content).hexdigest() != item['sha256']:
                raise RuntimeError('A preserved preview is no longer served byte-for-byte')
            checked.append(item['path'])
        if not checked and previews:
            raise RuntimeError('No preserved preview was verified')
        if previews:
            task = previews[0]['path'].split('/')[1]
            for filename in ('script.txt', 'composition.json', 'audio.mp3'):
                if client.get(f'{base_url}/tasks/{task}/{filename}').status_code != 404:
                    raise RuntimeError('A private task artifact is publicly accessible')
    return {**stored, 'origin': base_url, 'upstream_commit': PIN, 'auth_required': True,
            'previews_verified': checked, 'private_artifacts_blocked': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--container', required=True)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--fixture-key')
    args = parser.parse_args()
    key = args.fixture_key
    if not key:
        # Canonical checks read the privately preserved key without logging it.
        original = json.loads((args.snapshot / 'docker-inspect.json').read_text())[0]
        env = dict(value.split('=', 1) for value in original['Config']['Env'] if '=' in value)
        key = env['MPT_API_KEY']
    report = verify(args.snapshot, args.container, args.origin, key)
    (args.snapshot / (args.container + '.verification.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
