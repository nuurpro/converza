"""Loopback-only QA server using real PostgreSQL + production routes, test auth/inference.

TEST_DSN='... dbname=test_converza_qa' python core/tests/qa_harness.py
Never import this harness in the production app. It creates local test fixtures only.
"""
from __future__ import annotations
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

CORE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CORE)); sys.path.insert(0,str(Path(__file__).parent))
from pg_supabase import PgSupabase
from psycopg2.extras import Json

OWNER='11111111-1111-4111-8111-111111111111'
OWNER_B='11111111-1111-4111-8111-111111111112'
ORG_B='22222222-2222-4222-8222-222222222223'
PASSPORT_B='33333333-3333-4333-8333-333333333334'
ORG='22222222-2222-4222-8222-222222222222'
PASSPORT='33333333-3333-4333-8333-333333333333'
PROSPECT='44444444-4444-4444-8444-444444444444'
SLEYZ='55555555-5555-4555-8555-555555555555'
MILO='66666666-6666-4666-8666-666666666666'
PRODUCT='77777777-7777-4777-8777-777777777777'
FAQ='88888888-8888-4888-8888-888888888888'
KEY='qa-loopback-backend-key'
PUBLISHER='qa-loopback-publisher-key'
USER={'id':OWNER,'aud':'authenticated','role':'authenticated','email':'owner@qa.invalid','email_confirmed_at':'2026-01-01T00:00:00Z','app_metadata':{'provider':'email','providers':['email']},'user_metadata':{},'created_at':'2026-01-01T00:00:00Z','updated_at':'2026-01-01T00:00:00Z'}


def jwt(owner=OWNER):
    encode=lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    return encode({'alg':'HS256','typ':'JWT'})+'.'+encode({'sub':owner,'role':'authenticated','aud':'authenticated','exp':int(time.time())+86400,'iat':int(time.time()),'iss':'http://127.0.0.1:8019/auth/v1'})+'.qa-test-signature'

TOKEN=os.environ.get('QA_SESSION_TOKEN') or jwt()
TOKEN_B=jwt(OWNER_B)
USER_B={**USER,'id':OWNER_B,'email':'second-owner@qa.invalid'}


def validate_qa_dsn(dsn):
    from psycopg2.extensions import parse_dsn
    config=parse_dsn(dsn)
    loopback=('127.0.0.1','localhost','::1')
    if (config.get('host') not in loopback or config.get('hostaddr',config['host']) not in loopback
            or config.get('service') or not config.get('dbname','').startswith('test_converza')):
        raise ValueError('QA harness requires an explicitly named disposable loopback test_converza database')


async def qa_sleyz_model(messages, **kwargs):
    """Only the browser fixture uses this stub; production Huawei is untouched."""
    properties=(kwargs.get('schema') or {}).get('properties',{})
    if 'intent_score' in properties:
        return {'intent_score':.9,'product_query':'founder-course','quantity':1,'language':'en','objections':[]}
    if 'citations' in properties:
        return {'citations':[],'acknowledgement':'thanks','next_step':'buy','include_price':True,'include_stock':True,'include_description':True}
    if 'rule_type' in properties:
        return {'rule':'','rule_type':'style','scope':'none','supporting_spans':[]}
    raise ValueError('Unknown QA inference contract')


def bootstrap(dsn):
    validate_qa_dsn(dsn)
    os.environ['CONVERZA_WORKFLOW_TEST_DSN']=dsn
    import test_workflow_postgres
    test_workflow_postgres.DSN=dsn
    test_workflow_postgres.PostgresWorkflowTests.setUpClass()
    client=PgSupabase(dsn)
    with client.connect() as c:
        with c.cursor() as q:
            q.execute('CREATE SCHEMA IF NOT EXISTS auth; CREATE TABLE IF NOT EXISTS auth.users(id uuid PRIMARY KEY)')
            q.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING',(OWNER,))
            q.execute('INSERT INTO auth.users(id) VALUES(%s) ON CONFLICT DO NOTHING',(OWNER_B,))
            q.execute((CORE/'migrations/002_service_role_switchboard_policies.sql').read_text())
            q.execute((CORE/'migrations/003_onboarding_paywall.sql').read_text())
            q.execute('''CREATE TABLE IF NOT EXISTS tg_connections(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                org_id uuid REFERENCES orgs(id),bot_token text)''')
            q.execute((CORE/'migrations/006_telegram_destinations.sql').read_text())
            q.execute("SELECT to_regclass('sleyz_inbound')")
            if not q.fetchone()[0]:
                q.execute((CORE/'migrations/007_sleyz_inbound.sql').read_text())
            q.execute((CORE/'migrations/008_milo_campaigns.sql').read_text())
            q.execute('''ALTER TABLE brand_passports ADD COLUMN IF NOT EXISTS tone text,
              ADD COLUMN IF NOT EXISTS industry text,ADD COLUMN IF NOT EXISTS core_offer text,
              ADD COLUMN IF NOT EXISTS target_audience text,ADD COLUMN IF NOT EXISTS target_location text,
              ADD COLUMN IF NOT EXISTS hex_colors text[];''')
            q.execute('INSERT INTO orgs(id) VALUES(%s) ON CONFLICT DO NOTHING',(ORG,))
            q.execute('INSERT INTO orgs(id) VALUES(%s) ON CONFLICT DO NOTHING',(ORG_B,))
            q.execute("INSERT INTO brand_passports(id,org_id,owner_user_id,brand_name,onboarding_completed_at,paywall_status) VALUES(%s,%s,%s,'Festival Studio',now(),'paid') ON CONFLICT DO NOTHING",(PASSPORT_B,ORG_B,OWNER_B))
            q.execute("INSERT INTO brand_passports(id,org_id,owner_user_id,brand_name,tone,core_offer,target_audience,target_location,onboarding_completed_at,paywall_status,voice_rules,negative_constraints) VALUES(%s,%s,%s,'Nova Training','Warm and direct','Practical founder training','Early-stage founders','Tashkent',now(),'paid',%s,%s) ON CONFLICT DO NOTHING",(PASSPORT,ORG,OWNER,Json(['Use clear examples']),Json(['No guaranteed revenue claims'])))
            q.execute('INSERT INTO prospects(id,org_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',(PROSPECT,ORG))
            q.execute("INSERT INTO brand_products(id,org_id,name,description,price,currency,sku,stock_count,checkout_url_template) VALUES(%s,%s,'Founder course','Live training with two coaching sessions',100,'USD','founder-course',3,'https://merchant.example/checkout?sku={sku}&quantity={quantity}') ON CONFLICT DO NOTHING",(PRODUCT,ORG))
            q.execute("INSERT INTO brand_knowledge(id,org_id,kind,title,content) VALUES(%s,%s,'faq','Course delivery','Training starts on Monday. Two coaching sessions are included.') ON CONFLICT DO NOTHING",(FAQ,ORG))
    for draft_id,agent,inbound,answer,prospect in ((SLEYZ,'sleyz','This sounds expensive. What is included?','The founder course is100 USD and includes two coaching sessions. What is your main growth goal?',PROSPECT),(MILO,'milo','Write a launch announcement for our founder course.','Build a clearer growth plan with Nova Training. Join the founder course and get two coaching sessions.',None)):
        existing=client.table('drafts').select('*').eq('id',draft_id).execute().data
        if not existing:
            draft=client.table('drafts').insert({'id':draft_id,'org_id':ORG,'agent_slug':agent,'prospect_id':prospect,'inbound_text':inbound,'draft_content':''}).execute().data[0]
            draft=client.rpc('workflow_transition',{'p_org_id':ORG,'p_draft_id':draft_id,'p_action':'ready','p_expected_revision':draft['revision'],'p_idempotency_key':'qa-seed-ready:'+draft_id,'p_content':answer}).execute().data
            client.table('squad_messages').insert({'org_id':ORG,'sender_slug':agent,'content':answer,'hitl_draft_id':draft_id}).execute()
    return client


def create_app():
    dsn=os.environ.get('TEST_DSN','')
    if not dsn: raise RuntimeError('Set TEST_DSN to an isolated test_converza PostgreSQL database')
    client=bootstrap(dsn)
    client.auth=SimpleNamespace(get_user=lambda token: SimpleNamespace(user=SimpleNamespace(id=OWNER if token==TOKEN else OWNER_B)) if token in (TOKEN,TOKEN_B) else (_ for _ in ()).throw(ValueError('Invalid QA session')))
    os.environ['BACKEND_API_KEY']=KEY; os.environ['PUBLISHER_API_KEY']=PUBLISHER; os.environ['DEFAULT_ORG_ID']=ORG
    import db
    db._client=client
    import main
    main.get_supabase=lambda:client
    import lib.switchboard as board
    async def classify(*args,**kwargs): return {'kind':'customer_copy'}
    async def engine(*args,**kwargs):
        from services.memory import MemoryStore
        products=MemoryStore(client).products(ORG)
        price=f"{products[0]['price']} {products[0]['currency']}" if products else 'not currently listed'
        return f'Nova Training founder course price is {price} and includes two coaching sessions. Which goal should we focus on?'
    board.complete_json=classify; board.call_engine=engine
    # QA-only semantic review: real route validation/storage still run unchanged.
    import services.milo.routes as milo_routes
    async def qa_review(artifact,context,**kwargs):
        from services.milo.pipeline import validate_brand_compliance
        report=validate_brand_compliance(artifact,context)
        report['semantic_checked']=True
        return report
    milo_routes.review_compliance=qa_review
    app=main.app
    from fastapi import Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:3000','http://localhost:3000','http://127.0.0.1:3029','http://localhost:3029'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
    def session(second=False): return {'access_token':TOKEN_B if second else TOKEN,'token_type':'bearer','expires_in':86400,'expires_at':int(time.time())+86400,'refresh_token':'qa-local-refresh','user':USER_B if second else USER}
    @app.get('/auth/v1/user')
    async def user(authorization:str|None=Header(None)):
        if authorization not in ('Bearer '+TOKEN,'Bearer '+TOKEN_B): raise HTTPException(401,'Invalid QA session')
        return USER if authorization=='Bearer '+TOKEN else USER_B
    @app.post('/auth/v1/token')
    async def token(): return session()
    @app.get('/qa/session')
    async def qa_session(account: str='first'):
        second=account=='second'
        return {'session':session(second),'org_id':ORG_B if second else ORG,
                'drafts':{} if second else {'sleyz':SLEYZ,'milo':MILO}}
    @app.post('/qa/publish/{draft_id}')
    async def qa_publish(draft_id:str):
        draft=client.table('drafts').select('*').eq('id',draft_id).eq('org_id',ORG).single().execute().data
        if not draft: raise HTTPException(404,'QA draft not found')
        if draft['status']=='PUBLISHED': return draft
        attempt='qa-delivery:'+draft_id
        claimed=client.rpc('workflow_transition',{'p_org_id':ORG,'p_draft_id':draft_id,'p_action':'begin_delivery','p_expected_revision':draft['revision'],'p_idempotency_key':attempt,'p_receipt':{'attempt_id':attempt}}).execute().data
        return client.rpc('workflow_transition',{'p_org_id':ORG,'p_draft_id':draft_id,'p_action':'publish','p_expected_revision':claimed['revision'],'p_idempotency_key':'qa-receipt:'+draft_id,'p_receipt':{'channel':'telegram','message_id':42,'attempt_id':attempt}}).execute().data
    @app.post('/qa/index')
    async def qa_index():
        from services.indexer import IndexWorker
        async def extraction(source):
            if source['kind']=='objection':
                meta=source['metadata']; atoms=[{'kind':'objection','objection':meta['inbound_text'],'answer':meta['final_content']}]
            else: atoms=[{'kind':'fact','text':source['content']}]
            return {'summary':source['content'][:150],'atoms':atoms}
        return {'processed':await IndexWorker(client,extraction).run_once(100)}
    @app.post('/qa/sleyz-process')
    async def qa_sleyz_process():
        from services.memory import MemoryStore
        from services.sleyz.worker import SleyzWorker
        from lib.repository import SupabaseRepository
        async def context_loader(job,query):
            memory=MemoryStore(client)
            context=memory.context(job['org_id'],query)
            context['products']=memory.products(job['org_id'])
            return context
        processed=await SleyzWorker(SupabaseRepository(client),model=qa_sleyz_model,context_loader=context_loader).run_once()
        return {'processed':processed}
    @app.post('/qa/milo-seed')
    async def qa_milo_seed():
        from datetime import datetime,timezone
        from services.milo.evidence import save_brand
        from services.milo.store import MiloStore
        from services.sleyz.store import SleyzStore
        from lib.repository import SupabaseRepository
        repo=SupabaseRepository(client)
        source=client.table('memory_sources').select('*').eq('org_id',ORG).eq('kind','faq').eq('external_id',FAQ).single().execute().data
        await save_brand(repo,ORG,{'campaign_language':'en','personas':[],
            'proof_points':[{'id':'coaching','source_id':source['id'],'revision':source['revision'],
                             'quote':'Two coaching sessions are included.','objection_topics':['price']}],
            'banned_terms':['guaranteed revenue'],'competitor_names':[]},OWNER)
        accepted=await SleyzStore(repo).accept(dict(org_id=ORG,platform='telegram',connection_id='qa-real-fixture',external_message_id='milo-buyer',
            customer_id='qa-milo-buyer',text='This sounds expensive. What support is included?',received_at=datetime.now(timezone.utc).isoformat()))
        store=MiloStore(repo)
        for job in await store.claim('extract',limit=100):
            if job['payload']['inbound_id']==accepted['inbound_id']:
                await store.finish_extraction(job,[dict(objection_type='price',topic='price',product_id=None,buyer_text='This sounds expensive.',span_start=0,span_end=22)])
            else: await store.finish_extraction(job,[])
        return {'org_id':ORG,'ready':True}
    @app.post('/qa/milo-process')
    async def qa_milo_process():
        from services.milo.worker import MiloWorker
        from lib.repository import SupabaseRepository
        async def model(messages,**kwargs):
            if 'passed' in kwargs['schema'].get('properties',{}): return {'passed':True,'violations':[]}
            request=json.loads(messages[-1]['content'])
            quote=request['buyer_objections'][0]; proof=request['verified_proof_points'][0]
            return dict(schema_version=1,trigger_reason=request['trigger_reason'],target_persona=request['personas'][0],language=request['language'],
                hooks=[{'framework':'A','text':'This sounds expensive. What support is included?'},
                       {'framework':'B','text':'Two coaching sessions are included.'},
                       {'framework':'C','text':'DM us to ask about the founder course.'}],
                video_script=[{'spoken_narration':'Two coaching sessions are included. DM us for details.',
                               'visual_broll_cues':'Show the coaching session setup.','on_screen_text':'Coaching included'}],
                social_captions={'instagram':'Ask about coaching for your founder journey.','telegram':'Two coaching sessions are included. DM us for details.','tiktok':'What support do you need as a founder?'},
                buyer_quotes=[{'source_id':quote['id'],'text':quote['buyer_text']}],proof_references=[{k:proof[k] for k in ('source_id','revision','quote')}],brand_revision=request['brand_revision'])
        worker=MiloWorker(SupabaseRepository(client),model=model)
        return {'processed':await worker.run_once('generate')}
    @app.post('/qa/milo-build')
    async def qa_milo_build():
        raise HTTPException(501, 'Use the isolated real-media journey test; no synthetic video receipts are accepted here')
    return app


if __name__=='__main__':
    import uvicorn
    uvicorn.run(create_app(),host='127.0.0.1',port=8019)
