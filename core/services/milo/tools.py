"""Deterministic Milo tools bound to an already authenticated organization."""
from datetime import datetime, timedelta, timezone

from .evidence import get_top_buyer_objections, load_context
from .pipeline import validate_brand_compliance
from .store import MiloStore


class MiloTools:
    def __init__(self, repo, org_id):
        self.repo=repo
        self.org_id=org_id
        self.store=MiloStore(repo)

    async def get_top_buyer_objections(self, time_window: timedelta, *, now=None):
        if not isinstance(time_window,timedelta) or not timedelta(0)<time_window<=timedelta(days=365):
            raise ValueError('Objection time window must be positive and no longer than365days')
        now=now or datetime.now(timezone.utc)
        since=now-time_window
        rows=await self.store.objections(self.org_id,since.isoformat())
        return get_top_buyer_objections(rows,org_id=self.org_id,since=since)

    async def validate_brand_compliance(self, draft_text):
        settings=await self.store.settings(self.org_id)
        context=await load_context(self.repo,self.org_id,self.store,
            since=datetime.now(timezone.utc)-timedelta(days=settings['window_days']))
        return validate_brand_compliance(draft_text,context)
