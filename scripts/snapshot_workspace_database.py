"""Read-only private backup of the rows touched by the legacy workspace upgrade.

Quiesce writers first. Two identical bounded reads are required before saving;
this is a verified maintenance snapshot, not a general PostgreSQL PITR backup.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dotenv import dotenv_values
import httpx

TABLES = ('orgs','brand_passports','prospects','messages','drafts','tg_connections')
MAX_BYTES = 100_000_000
MAX_ROWS = 100_000


def source_origin(raw):
    from urllib.parse import urlsplit
    u=urlsplit(raw)
    if (u.scheme!='https' or not u.hostname or u.username or u.password
            or u.path not in ('','/') or u.query or u.fragment):
        raise ValueError('Backup requires the fixed HTTPS Supabase origin')
    return raw.rstrip('/')


def collect(client, origin, headers):
    result={}
    total_rows=0
    total_bytes=0
    for table in TABLES:
        rows=[]
        while True:
            response=client.get(origin+'/rest/v1/'+table,headers=headers,
                                params={'select':'*','order':'id.asc','offset':len(rows),'limit':500})
            if response.status_code!=200:
                raise RuntimeError(f'Backup read failed for {table} ({response.status_code})')
            page=response.json()
            if not isinstance(page,list):
                raise ValueError('Invalid backup response')
            total_rows+=len(page)
            total_bytes+=len(response.content)
            if total_rows>MAX_ROWS or total_bytes>MAX_BYTES:
                raise ValueError('Backup exceeds the confirmation threshold; obtain explicit size approval')
            rows.extend(page)
            if not page:
                break
        result[table]=rows
    return result


def encode(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')


def secure_directory(path):
    path.mkdir(parents=True,exist_ok=False)
    if os.name=='nt':
        owner=subprocess.check_output(['whoami'],text=True).strip()
        subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r',
                        f'{owner}:(OI)(CI)F','SYSTEM:(OI)(CI)F'],check=True,capture_output=True)
    else:
        path.chmod(0o700)


def privileged_key(key):
    if key.startswith('sb_secret_'):
        return 'secret'
    try:
        payload=key.split('.')[1]
        claims=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
        if claims.get('role')=='service_role':
            return 'service_role'
    except (IndexError,ValueError,TypeError):
        pass
    raise ValueError('A server-only service-role/secret credential is required')


def snapshot(config, destination, recovery_root, *, expected_counts, quiesced=False):
    if not quiesced:
        raise ValueError('Quiesce writers before taking the migration snapshot')
    destination,recovery_root=destination.resolve(),recovery_root.resolve()
    project=Path(__file__).resolve().parents[1]
    if (destination==recovery_root or not destination.is_relative_to(recovery_root)
            or destination.is_relative_to(project) or destination.exists()):
        raise ValueError('Use a new private recovery directory outside the source tree')
    origin=source_origin(config.get('SUPABASE_URL') or '')
    key=config.get('SUPABASE_SERVICE_KEY')
    if not key:
        raise ValueError('Server-side backup credentials missing')
    kind=privileged_key(key)
    if (set(expected_counts)!=set(TABLES) or any(type(n) is not int or n<0 for n in expected_counts.values())):
        raise ValueError('Independent SQL counts for every affected table are required')
    headers={'apikey':key,'Authorization':'Bearer '+key}
    with httpx.Client(timeout=30,trust_env=False,follow_redirects=False) as client:
        first=collect(client,origin,headers)
        second=collect(client,origin,headers)
    if encode(first)!=encode(second):
        raise RuntimeError('Rows changed during the snapshot; stop writers and retry')
    if {table:len(rows) for table,rows in first.items()}!=expected_counts:
        raise RuntimeError('Backup visibility/count mismatch against independent SQL counts')
    payload=encode(first)
    if len(payload)>MAX_BYTES:
        raise ValueError('Encoded backup exceeds the confirmation threshold')
    secure_directory(destination)
    saved=destination/'rows.json'
    saved.write_bytes(payload)
    checksum=hashlib.sha256(payload).hexdigest()
    if hashlib.sha256(saved.read_bytes()).hexdigest()!=checksum:
        raise RuntimeError('Private backup verification failed')
    report={'snapshot':str(destination),'origin':origin,'sha256':checksum,'bytes':len(payload),
            'rows':expected_counts,'double_read_verified':True,'independent_counts_verified':True,
            'credential_kind':kind}
    (destination/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--recovery-root',type=Path,default=Path('E:/Coding/_Converza_recovery'))
    parser.add_argument('--writers-quiesced',action='store_true')
    parser.add_argument('--expected-counts',type=Path,required=True,help='JSON object from independent privileged SQL counts')
    args=parser.parse_args()
    try:
        config=dotenv_values(Path(__file__).resolve().parents[1]/'core/.env')
        counts=json.loads(args.expected_counts.read_text(encoding='utf-8-sig'))
        print(json.dumps(snapshot(config,args.destination,args.recovery_root,
                                  expected_counts=counts,quiesced=args.writers_quiesced)))
    except Exception as error:
        print(json.dumps({'ok':False,'error_type':type(error).__name__}))
        raise SystemExit(1)
