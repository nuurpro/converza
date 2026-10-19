from copy import deepcopy
from datetime import datetime, timezone


class WorkflowConflict(ValueError):
    """A stale revision, reused key, or invalid state transition (HTTP 409)."""


def apply_transition(draft, action, *, edited_content=None, receipt=None, error=None):
    """Pure state rules mirrored by workflow_transition in migration 005."""
    row = deepcopy(draft)
    status = row['status']
    now = datetime.now(timezone.utc).isoformat()
    if action == 'ready' and status == 'PENDING_DRAFT':
        content = (edited_content or '').strip()
        if not content:
            raise WorkflowConflict('Generated content must not be empty')
        row.update(status='AWAITING_HITL', draft_content=content, generation_error=None, generation_status='completed')
    elif action == 'generation_started' and status == 'PENDING_DRAFT' and row.get('generation_status', 'pending') == 'pending':
        row['generation_status'] = 'running'
    elif action in ('generation_failed', 'retry_generation') and status == 'PENDING_DRAFT':
        if action == 'retry_generation' and row.get('generation_status') != 'failed':
            raise WorkflowConflict('Generation is not failed')
        row['generation_error'] = error if action == 'generation_failed' else None
        row['generation_status'] = 'failed' if action == 'generation_failed' else 'pending'
    elif action in ('approve', 'edit', 'reject') and status == 'AWAITING_HITL':
        final = (edited_content or '').strip() if action == 'edit' else row['draft_content']
        if action == 'edit' and not final:
            raise ValueError('final_content is required when editing a draft')
        row.update(status={'approve':'APPROVED','edit':'EDITED','reject':'REJECTED'}[action],
                   final_content=final if action != 'reject' else None, decided_at=now)
    elif action in ('publish', 'begin_delivery', 'delivery_failed', 'delivery_ambiguous', 'claim_delivery') and status in ('APPROVED','EDITED'):
        if action == 'publish':
            if not isinstance(receipt, dict) or not receipt.get('channel') or not receipt.get('message_id') or not row.get('delivery_attempt_id') or receipt.get('attempt_id') != row.get('delivery_attempt_id'):
                raise WorkflowConflict('Successful publisher receipt is required')
            row.update(status='PUBLISHED', delivery_status='delivered', delivery_receipt=receipt,
                       delivered_at=now, delivery_error=None)
        elif action == 'begin_delivery':
            if row.get('delivery_status') in ('ambiguous', 'sending'):
                raise WorkflowConflict('Delivery requires reconciliation before retry')
            if not isinstance(receipt, dict) or not receipt.get('attempt_id'):
                raise WorkflowConflict('Delivery attempt id is required')
            row.update(delivery_status='sending', delivery_error=None, delivery_attempt_id=receipt['attempt_id'], delivery_claimed_at=None)
        elif action == 'claim_delivery':
            if row.get('delivery_status') != 'sending' or row.get('delivery_claimed_at') or not isinstance(receipt, dict) or receipt.get('attempt_id') != row.get('delivery_attempt_id'):
                raise WorkflowConflict('Delivery already claimed')
            row['delivery_claimed_at'] = now
        else:
            row.update(delivery_status='failed' if action == 'delivery_failed' else 'ambiguous', delivery_error=error)
    elif action == 'resolve' and row.get('agent_slug') == 'sleyz' and row.get('prospect_id') and status == 'PUBLISHED' and row.get('delivered_at') and row.get('delivery_receipt') and not row.get('resolved_at'):
        row['resolved_at'] = now
    else:
        raise WorkflowConflict(f'Cannot {action} draft in {status}')
    row.update(revision=row['revision'] + 1, updated_at=now)
    return row
