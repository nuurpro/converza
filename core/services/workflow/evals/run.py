"""Run deterministic lifecycle safety evaluation and optional paid intent eval."""
import argparse
import asyncio
import json
from pathlib import Path

from services.workflow.state import apply_transition, WorkflowConflict


def evaluate_invariants():
    states = ['PENDING_DRAFT','AWAITING_HITL','APPROVED','EDITED','REJECTED','PUBLISHED']
    actions = ['ready','approve','edit','reject','publish','resolve']
    allowed = {('PENDING_DRAFT','ready'),('AWAITING_HITL','approve'),
        ('AWAITING_HITL','edit'),('AWAITING_HITL','reject'),('APPROVED','publish'),
        ('EDITED','publish'),('PUBLISHED','resolve')}
    passed = 0
    for state in states:
        for action in actions:
            row = {'id':'draft','org_id':'a','agent_slug':'sleyz','prospect_id':'buyer',
                'status':state,'revision':1,'draft_content':'Exact answer',
                'delivery_attempt_id':'attempt','delivered_at':'2026-10-19T00:00:00Z',
                'delivery_receipt':{'channel':'telegram','message_id':1}}
            try:
                result = apply_transition(row,action,edited_content='Exact edit',
                    receipt={'channel':'telegram','message_id':1,'attempt_id':'attempt'})
                actual = result['revision'] == 2
            except WorkflowConflict:
                actual = False
            if actual != ((state,action) in allowed):
                raise AssertionError(f'Lifecycle matrix failed: {state}/{action}')
            passed += 1
    for agent, buyer in [('milo','buyer'),('vea','buyer'),('sleyz',None)]:
        try:
            apply_transition({'status':'PUBLISHED','revision':1,'agent_slug':agent,
                'prospect_id':buyer,'delivered_at':'now','delivery_receipt':{'id':1}},'resolve')
        except WorkflowConflict:
            passed += 1
        else:
            raise AssertionError('Non-buyer content became resolved objection memory')
    return passed


async def main(live):
    passed = evaluate_invariants()
    print(json.dumps({'evaluation':'workflow_invariants','passed':passed,'total':passed,'threshold':1.0}))
    if live:
        from lib.switchboard import classify_output
        cases = json.loads(Path(__file__).with_name('cases.json').read_text())
        results = [await classify_output(c['agent'],c['request']) == c['kind'] for c in cases]
        print(json.dumps({'evaluation':'customer_intent','passed':sum(results),'total':len(results),'threshold':1.0}))
        if not all(results):
            raise SystemExit(1)


def cli(argv=None):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3] / '.env')
    parser = argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    try:
        asyncio.run(main(parser.parse_args(argv).live))
    except Exception as error:
        from services.llm import ConfigurationError
        print(json.dumps({'evaluation':'customer_intent','status':'missing_configuration' if isinstance(error, ConfigurationError) else 'failed','error_type':type(error).__name__}))
        return 2 if isinstance(error, ConfigurationError) else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(cli())
