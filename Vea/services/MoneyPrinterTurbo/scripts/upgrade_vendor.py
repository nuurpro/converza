"""Repeatable three-way vendor import. Conflicts are saved, never installed.

Run only after a private full-tree backup. Does not remove local-only files,
touch config.toml/storage/resource, stage Git changes, or deploy a container.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

BASE='63113a34228ce569436e2cf0037d378c64b3a2ae'
TARGET='6992380c5e82f07f3e1fc46b90927b6f1c655407'


def git(repo, *args):
    return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True).stdout


def upgrade(repo, destination, evidence):
    if git(repo,'rev-parse','v1.3.9').decode().strip()!=TARGET:
        raise ValueError('Official v1.3.9 tag does not match the approved pin')
    evidence.mkdir(parents=True,exist_ok=True)
    names=git(repo,'ls-tree','-r','--name-only',TARGET).decode().splitlines()
    base_names=set(git(repo,'ls-tree','-r','--name-only',BASE).decode().splitlines())
    roots={'main.py','config.example.toml','requirements.txt','pyproject.toml','uv.lock','LICENSE'}
    records=[]
    for name in names:
        # The approved image ships no WebUI, CLI launcher, packaged providers or weights.
        if not (name.startswith('app/') or name in roots): continue
        theirs=git(repo,'show',f'{TARGET}:{name}').replace(b'\r\n',b'\n')
        path=destination/name
        ours=path.read_bytes().replace(b'\r\n',b'\n') if path.is_file() else None
        base=git(repo,'show',f'{BASE}:{name}').replace(b'\r\n',b'\n') if name in base_names else None
        status='upstream'
        if ours is None or ours==base or ours==theirs:
            merged=theirs
        elif base==theirs:
            merged=ours; status='local_overlay'
        elif base is None:
            merged=ours; status='conflict_add_add'
        else:
            with tempfile.TemporaryDirectory() as folder:
                files=[Path(folder)/n for n in ('ours','base','theirs')]
                for f, content in zip(files,(ours,base,theirs)): f.write_bytes(content)
                result=subprocess.run(['git','merge-file','-p',*map(str,files)],capture_output=True)
                if result.returncode==0:
                    merged=result.stdout; status='merged'
                elif result.returncode in range(1,128):
                    merged=ours; status='conflict'
                else: raise RuntimeError(result.stderr.decode(errors='replace'))
        if status.startswith('conflict'):
            for suffix,content in (('base',base),('local',ours),('upstream',theirs)):
                if content is not None:
                    saved=evidence/(name+'.'+suffix); saved.parent.mkdir(parents=True,exist_ok=True); saved.write_bytes(content)
        else:
            path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(merged)
        records.append(dict(path=name,status=status,sha256=hashlib.sha256(merged).hexdigest()))
    (evidence/'merge-report.json').write_text(json.dumps(dict(base=BASE,target=TARGET,files=records),indent=2))
    print(json.dumps({s:sum(r['status']==s for r in records) for s in sorted({r['status'] for r in records})}))
    print('\n'.join(r['path'] for r in records if r['status'].startswith('conflict')))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('upstream',type=Path); parser.add_argument('destination',type=Path); parser.add_argument('evidence',type=Path)
    args=parser.parse_args(); upgrade(args.upstream,args.destination,args.evidence)
