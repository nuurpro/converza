"""Authenticated, receipt-bound scene execution; no narration regeneration."""
import hashlib
import json
import httpx
from services.milo.video import _control_headers,_public_video_url
from lib.moneyprinter import _base_url
from .storyboard import content_hash


class DirectorProvider:
    def __init__(self,client=None):self.client=client

    async def context(self,org_id,product_id=None,language='en'):
        params={'org_id':org_id,'language':language}
        if product_id:params['product_id']=product_id
        response=await self.request('GET','/api/v1/director/context',params=params)
        response.raise_for_status()
        value=response.json()
        if not all(isinstance(value.get(k),str) and len(value[k])==64 for k in ('asset_catalog_sha256','renderer_config_sha256')):
            raise ValueError('Renderer cache context unavailable')
        return value

    def envelope(self,task):
        payload=dict(org_id=task['org_id'],run_id=task['run_id'],campaign_id=task['campaign_id'],
            storyboard_revision=task['storyboard_revision'],attempt=task['attempt'],spec_sha256=task['spec_hash'],idempotency_key=task['idempotency_key'])
        correction=task.get('correction') or {}
        notes=correction.get('correction_notes') or correction.get('violations') or [] if isinstance(correction,dict) else [str(correction)]
        payload['correction_notes']=notes
        payload['expected_context']=task.get('renderer_context')
        if task['kind']=='scene':payload.update(scene=task['specification'],language=task.get('language','en'),product_id=task.get('product_id'))
        else:payload['manifest']=task['specification']
        return payload

    async def request(self,method,path,**kwargs):
        if self.client:
            response=await self.client.request(method,_base_url()+path,headers=_control_headers(),**kwargs)
        else:
            async with httpx.AsyncClient(timeout=60,follow_redirects=False) as client:
                response=await client.request(method,_base_url()+path,headers=_control_headers(),**kwargs)
        return response

    def validate(self,task,receipt):
        expected={k:v for k,v in self.envelope(task).items() if k in ('org_id','run_id','campaign_id','storyboard_revision','attempt','spec_sha256','idempotency_key')}
        if receipt.get('binding')!=expected or not receipt.get('task_id'):raise ValueError('Renderer receipt does not match director task binding')
        return receipt

    async def submit(self,task):
        response=await self.request('POST','/api/v1/director/'+('scenes' if task['kind']=='scene' else 'masters'),json=self.envelope(task))
        response.raise_for_status();return self.validate(task,response.json())

    async def reconcile(self,task):
        response=await self.request('GET','/api/v1/director/tasks',params={'org_id':task['org_id'],'idempotency_key':task['idempotency_key']})
        if response.status_code==404:return {'not_submitted':True}
        response.raise_for_status();return self.validate(task,response.json())

    async def poll(self,task):
        receipt_id=task['receipt']['task_id']
        response=await self.request('GET',f'/api/v1/director/tasks/{receipt_id}',params={'org_id':task['org_id']})
        response.raise_for_status();receipt=self.validate(task,response.json())
        if receipt['status']!='complete':
            return {'status':'failed' if receipt['status']=='failed' else 'running','error':receipt.get('error')}
        result=receipt['result']
        observed=result.get('evidence_sha256')
        if not observed or content_hash({k:v for k,v in result.items() if k!='evidence_sha256'})!=observed:
            raise ValueError('Renderer evidence digest mismatch')
        # Authenticate and hash the actual encoded artifact, independently of receipt metadata.
        artifact=await self.request('GET',f'/api/v1/director/tasks/{receipt_id}/artifacts/final-1.mp4',params={'org_id':task['org_id']})
        artifact.raise_for_status()
        if hashlib.sha256(artifact.content).hexdigest()!=result['artifact_sha256']:raise ValueError('Renderer clip bytes differ from inspection evidence')
        for field in ('video_url','thumbnail_url'):
            if result.get(field):result[field]=_public_video_url(result[field],_base_url())
        return {'status':'completed','result':result}
