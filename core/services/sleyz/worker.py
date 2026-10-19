"""Supervised durable inbox/learning worker. Each claim is fenced by a lease token."""
import asyncio
from datetime import datetime, timezone
import logging
import time

from starlette.concurrency import run_in_threadpool

from services.memory import MemoryStore
from .learning import analyze_edit
from .pipeline import classify_message, generate_artifact
from .store import SleyzStore

logger=logging.getLogger('converza.sleyz.worker')


class SleyzWorker:
    def __init__(self, repo, *, model=None, context_loader=None, timeout_seconds=500):
        self.repo=repo
        self.store=SleyzStore(repo)
        self.model=model
        self.context_loader=context_loader
        self.timeout_seconds=timeout_seconds

    async def history(self, job):
        """Bounded chronological context, cut off at this inbound's acceptance."""
        def timestamp(value):
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('Conversation timestamps must include a timezone')
            return parsed.astimezone(timezone.utc)

        cutoff = timestamp(job['envelope']['received_at'])
        simulated = bool(job['envelope'].get('simulated'))
        if not hasattr(self.repo, 'client'):
            drafts = {row['id']: row for row in self.repo.drafts}
            inbox = list(self.store.state['inbox'].values())
            accepted_order = {row['id']: index for index, row in enumerate(inbox)}
            current_order = accepted_order[job['id']]
            rows = [row for row in inbox if row['org_id'] == job['org_id']
                    and row['prospect_id'] == job['prospect_id']
                    and accepted_order[row['id']] < current_order
                    and timestamp(row['received_at']) <= cutoff]
            rows.sort(key=lambda row: (timestamp(row['received_at']), accepted_order[row['id']]))
            rows = rows[-20:]
            replies = [row for row in drafts.values() if row['org_id'] == job['org_id']
                       and row.get('prospect_id') == job['prospect_id']
                       and row.get('agent_slug') == 'sleyz' and row.get('status') == 'PUBLISHED'
                       and row.get('delivery_status') == 'delivered' and row.get('delivered_at')
                       and bool(row.get('simulated')) == simulated
                       and timestamp(row['delivered_at']) <= cutoff]
        else:
            accepted_at = job.get('created_at')
            if not accepted_at:
                accepted_at = (await self.repo.get_draft(job['draft_id']))['created_at']

            def inbound_query():
                return (self.repo.client.table('sleyz_inbound').select('id,envelope,received_at,created_at')
                        .eq('org_id', job['org_id']).eq('prospect_id', job['prospect_id'])
                        .lte('received_at', cutoff.isoformat())
                        .order('received_at', desc=True).order('created_at', desc=True).order('id', desc=True).limit(20))

            # A timestamp tie uses the stable inbox UUID as a deterministic final key.
            # Separate bounded queries preserve older history even with many tied rows.
            before = inbound_query().lt('created_at', accepted_at)
            tied = inbound_query().eq('created_at', accepted_at).lt('id', job['id'])
            delivered = (self.repo.client.table('drafts').select('*')
                         .eq('org_id', job['org_id']).eq('prospect_id', job['prospect_id'])
                         .eq('agent_slug', 'sleyz').eq('status', 'PUBLISHED')
                         .eq('delivery_status', 'delivered').eq('simulated', simulated)
                         .lte('delivered_at', cutoff.isoformat())
                         .order('delivered_at', desc=True).order('id', desc=True).limit(20))
            prior, equal, sent = await asyncio.gather(*[
                run_in_threadpool(query.execute) for query in (before, tied, delivered)])
            rows = (prior.data or []) + (equal.data or [])
            rows.sort(key=lambda row: (timestamp(row['received_at']), timestamp(row['created_at']), row['id']))
            rows = rows[-20:]
            replies = sent.data or []
            accepted_order = {row['id']: index for index, row in enumerate(rows)}

        events = []
        for row in rows:
            text = row['envelope'].get('text')
            if isinstance(text, str) and text.strip():
                events.append((timestamp(row['received_at']), 0, accepted_order[row['id']],
                               {'role': 'user', 'content': text}))
        for row in replies:
            receipt = row.get('delivery_receipt')
            content = row.get('final_content') or row.get('draft_content')
            if isinstance(receipt, dict) and receipt.get('message_id') and isinstance(content, str) and content.strip():
                events.append((timestamp(row['delivered_at']), 1, row['id'],
                               {'role': 'assistant', 'content': content}))
        events.sort(key=lambda event: event[:3])
        return [event[3] for event in events[-20:]]

    async def context(self, job, query):
        if self.context_loader:
            return await self.context_loader(job,query)
        if not hasattr(self.repo,'client'):
            state=self.store.state
            return {'identity':{'passport':await self.repo.get_brand_passport(job['org_id']),'exports':{}},
                    'knowledge':[dict(row,source_id=row['id']) for row in state['corrections'] if row['org_id']==job['org_id'] and not row.get('deleted_at')],
                    'products':getattr(self.repo,'brand_products',[])}
        memory=MemoryStore(self.repo.client)
        context=await run_in_threadpool(memory.context,job['org_id'],query)
        # Generic agent context has a small price-only catalog. Sales tools require complete canonical records.
        context['products']=await run_in_threadpool(memory.products,job['org_id'])
        return context

    async def process(self, job):
        started=time.monotonic()
        envelope=job['envelope']
        history=await self.history(job)
        classification=await classify_message(envelope,model=self.model,history=history)
        await self.store.telemetry(job,[objection.model_dump(mode='json') for objection in classification.objections])
        query=' '.join([classification.product_query,envelope['text'],*(o.type for o in classification.objections),
                       'customer reply question concerns paragraphs concise language signature tone pressuring benefits'])
        context=await self.context(job,query)
        context['history']=history
        artifact=await generate_artifact(envelope,context,model=self.model,classification=classification)
        draft=await self.store.ready(job,artifact)
        age=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(envelope['received_at'].replace('Z','+00:00'))).total_seconds())
        logger.info('sleyz_draft_ready org=%s draft=%s platform=%s intent=%s generation_ms=%d inbound_to_draft_ms=%d attempt=%s',
                    job['org_id'],job['draft_id'],envelope['platform'],artifact['intent'],int((time.monotonic()-started)*1000),int(age*1000),job['attempts'])
        if not envelope.get('simulated') and hasattr(self.repo,'client'):
            # Dashboard state is already durable. Manager notifications are best-effort.
            try:
                from Sleyz.agents.reporter import report_hitl
                await report_hitl(job['org_id'],job['prospect_id'],job['draft_id'],envelope.get('tg_chat_id'),
                                  envelope.get('business_connection_id'),envelope['text'],draft['draft_content'])
            except Exception as exc:
                logger.warning('sleyz_notification_failed draft=%s error_type=%s',job['draft_id'],type(exc).__name__)

    async def run_once(self):
        count=0
        for job in await self.store.claim(limit=1,lease_seconds=600):
            count+=1
            try:
                await asyncio.wait_for(self.process(job),timeout=self.timeout_seconds)
            except Exception as exc:
                await self.store.fail(job,type(exc).__name__)
                logger.warning('sleyz_generation_failed org=%s draft=%s error_type=%s attempt=%s',job['org_id'],job['draft_id'],type(exc).__name__,job['attempts'])
        for job in await self.store.claim_learning(limit=1,lease_seconds=600):
            count+=1
            try:
                correction=await asyncio.wait_for(analyze_edit(job,model=self.model),timeout=self.timeout_seconds)
                saved=await self.store.complete_learning(job,correction)
                logger.info('sleyz_learning draft=%s outcome=%s saved=%s',job['draft_id'],'rule' if correction else 'no_rule',saved)
            except Exception as exc:
                await self.store.fail_learning(job,type(exc).__name__)
                logger.warning('sleyz_learning_failed draft=%s error_type=%s',job['draft_id'],type(exc).__name__)
        return count

    async def run(self,poll_seconds=1):
        while True:
            try:
                count=await self.run_once()
                if not count:
                    await asyncio.sleep(poll_seconds)
            except Exception as exc:
                logger.warning('sleyz_worker_poll_failed error_type=%s',type(exc).__name__)
                await asyncio.sleep(poll_seconds)
