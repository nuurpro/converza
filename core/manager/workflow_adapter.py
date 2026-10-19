"""Manager bot adapter. Destinations and content always come from storage."""
from lib.repository import SupabaseRepository
from services.workflow.publication import deliver_telegram_draft


async def decide_and_publish(*, client, conn, draft_id, action, revision, key, content=None):
    repo = SupabaseRepository(client)
    draft = await repo.get_draft(draft_id)
    if not draft or draft['org_id'] != conn['org_id']:
        raise KeyError(draft_id)
    if action == 'resolve':
        return await repo.mark_resolved(conn['org_id'], draft_id, revision, key)
    if action != 'retry':
        draft = await repo.transition_draft(conn['org_id'], draft_id, action, revision, key, edited_content=content)
    if action == 'reject':
        return draft
    if not draft.get('prospect_id'):
        return draft
    return await deliver_telegram_draft(repo=repo, org_id=conn['org_id'], draft_id=draft_id,
        expected_revision=draft['revision'] if action != 'retry' else revision,
        idempotency_key=key + ':send')
