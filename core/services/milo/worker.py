"""Supervised, bounded and fenced objection/generation/video worker."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time

from .evidence import load_context
from .pipeline import extract_objections, generate_campaign
from .scheduler import schedule
from .store import MiloStore
from .video import render_approved_script

logger=logging.getLogger('converza.milo')


class MiloWorker:
    def __init__(self,repo,*,model=None,context_loader=None,renderer=None,timeout_seconds=500):
        self.repo=repo; self.store=MiloStore(repo); self.model=model
        self.context_loader=context_loader; self.renderer=renderer or render_approved_script; self.timeout_seconds=timeout_seconds

    async def context(self,org):
        if self.context_loader: return await self.context_loader(org)
        settings=await self.store.settings(org)
        return await load_context(self.repo,org,self.store,since=datetime.now(timezone.utc)-timedelta(days=settings['window_days']))

    async def process(self,job):
        started=time.monotonic()
        if job['kind']=='extract':
            context=await self.context(job['org_id'])
            result=await extract_objections(job['payload']['text'],context['products'],model=self.model)
            await self.store.finish_extraction(job,result)
            logger.info('milo_extraction org=%s job=%s count=%s',job['org_id'],job['id'],len(result))
        elif job['kind']=='generate':
            campaign=await self.store.get_campaign(job['org_id'],job['campaign_id'])
            context=await self.context(job['org_id'])
            if campaign['trigger']!='manual':
                reserved=set(campaign.get('evidence_ids') or [])
                context={**context,'objections':[r for r in context['objections'] if r['id'] in reserved]}
            result=await generate_campaign(context,prompt=campaign['prompt'],trigger=campaign['trigger'],
                language=campaign.get('language'),topic=campaign.get('topic'),product_id=campaign.get('product_id'),model=self.model)
            row=await self.store.complete_generation(job,**result)
            logger.info('milo_campaign org=%s campaign=%s status=%s violations=%s',job['org_id'],row['id'],row['status'],len(result['compliance']['violations']))
            await self.repo.insert_squad_message(job['org_id'],'milo',
                ('Campaign needs evidence: '+' '.join(row['missing_evidence'])) if row['missing_evidence'] else
                ('Campaign blocked by brand compliance. Review the listed violations in the Milo workspace.' if row['status']=='blocked' else
                 'Campaign ready for review. Approve its video script in the Milo workspace to enqueue Vea.'))
        elif job['kind']=='build':
            from services.vea.store import prepare_build, enabled
            if job['payload'].get('variant_id') or job['payload'].get('vea_config') or enabled():
                job = await prepare_build(job, self.store)
            result=await self.renderer(job,self.store)
            row=await self.store.complete_build(job,result)
            approved=datetime.fromisoformat(job['created_at'].replace('Z','+00:00'))
            logger.info('milo_vea_completed org=%s campaign=%s render_seconds=%.3f approval_to_build_seconds=%.3f',
                        job['org_id'],row['id'],time.monotonic()-started,(datetime.now(timezone.utc)-approved).total_seconds())
        else: raise ValueError('Unknown Milo job kind')
        logger.info('milo_job org=%s job=%s kind=%s outcome=completed elapsed_seconds=%.3f',job['org_id'],job['id'],job['kind'],time.monotonic()-started)

    async def run_once(self,kind=None):
        count=0
        for current in ([kind] if kind else ['extract','generate','build']):
            jobs=await self.store.claim(current,limit=1,lease_seconds=600)
            for job in jobs:
                count+=1
                try:
                    await asyncio.wait_for(self.process(job),timeout=self.timeout_seconds)
                except Exception as exc:
                    await self.store.fail(job,type(exc).__name__)
                    logger.warning('milo_job org=%s job=%s kind=%s outcome=failed error_type=%s',job['org_id'],job['id'],job['kind'],type(exc).__name__)
        return count

    async def run(self):
        last_schedule=0
        while True:
            try:
                if time.monotonic()-last_schedule>=30:
                    await schedule(self.repo); last_schedule=time.monotonic()
                count=await self.run_once()
                if not count: await asyncio.sleep(2)
            except Exception as exc:
                logger.warning('milo_poll_failed error_type=%s',type(exc).__name__)
                await asyncio.sleep(5)
