"""Mechanical part of the reviewed v1.3.9 conflict resolution.

Run once against upgrade_vendor.py's private evidence directory, then apply
the documented Converza overlay. Never a deployment/startup command.
"""
import argparse
import re
import subprocess
from pathlib import Path


def resolve(evidence, destination):
    choices={
        'app/config/config.py':['local','local','local','both'],
        'app/models/schema.py':['both','local','upstream'],
        'app/controllers/v1/video.py':['local'],
        'app/controllers/v1/llm.py':['local','local'],
        'app/services/task.py':['upstream','upstream','upstream','upstream','local'],
    }
    for name in ('app/asgi.py','app/services/llm.py','app/services/voice.py','app/services/video.py'):
        (destination/name).write_bytes((evidence/(name+'.upstream')).read_bytes())
    for name, decisions in choices.items():
        stem=str(evidence/name)
        result=subprocess.run(['git','merge-file','-p',stem+'.local',stem+'.base',stem+'.upstream'],capture_output=True)
        index=0
        def replace(match):
            nonlocal index
            mode=decisions[index]; index+=1
            return match[1] if mode=='local' else match[2] if mode=='upstream' else match[1]+match[2]
        merged=re.sub(r'(?ms)^<<<<<<<[^\n]*\n(.*?)^=======\n(.*?)^>>>>>>>[^\n]*\n',replace,result.stdout.decode())
        if index!=len(decisions) or any(marker in merged for marker in ('<<<<<<<','>>>>>>>')):
            raise ValueError('Conflict layout changed: '+name)
        (destination/name).write_text(merged,encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence',type=Path); parser.add_argument('destination',type=Path)
    args=parser.parse_args(); resolve(args.evidence,args.destination)
