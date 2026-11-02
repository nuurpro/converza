"""Real PostgreSQL director CAS, tenancy, leases and transactional SSE gates."""
import asyncio
import concurrent.futures
import os
from pathlib import Path
import unittest
import uuid

from services.milo.director.store import DirectorStore
from services.milo.director.documents import DirectorDocuments
from services.milo.director.contracts import Storyboard
from services.milo.store import MiloStore
from services.workflow.state import WorkflowConflict
import test_milo_postgres as base


@unittest.skipUnless(os.getenv('CONVERZA_WORKFLOW_TEST_DSN'),'requires disposable PostgreSQL DSN')
class DirectorPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.MiloPostgresTests.setUpClass()
        cls.client=base.MiloPostgresTests.client
        cls.repo=base.MiloPostgresTests.repo
        cls.store=DirectorStore(cls.repo)
        with cls.client.connect() as conn,conn.cursor() as q:
            q.execute((Path(__file__).resolve().parents[1]/'migrations/009_vea_variants.sql').read_text(encoding='utf-8'))
            q.execute((Path(__file__).resolve().parents[1]/'migrations/012_pending_feed.sql').read_text(encoding='utf-8'))
            q.execute((Path(__file__).resolve().parents[1]/'migrations/018_milo_director.sql').read_text(encoding='utf-8'))
            q.execute((Path(__file__).resolve().parents[1]/'migrations/019_milo_director_documents.sql').read_text(encoding='utf-8'))
            q.execute((Path(__file__).resolve().parents[1]/'migrations/020_milo_director_approval.sql').read_text(encoding='utf-8'))

    def setUp(self):
        self.org=str(uuid.uuid4())
        self.client.table('orgs').insert({'id':self.org}).execute()
        self.campaign=self.client.table('milo_campaigns').insert(dict(org_id=self.org,trigger='manual',
            dedup_key=str(uuid.uuid4()),script_status='approved',revision=2)).execute().data[0]
        self.scenes=[dict(scene_index=i,target_duration_sec=2,narration_chunk=str(i)) for i in range(1,3)]

    def tearDown(self):
        with self.client.connect() as conn,conn.cursor() as q:
            q.execute('DELETE FROM brand_passports WHERE org_id=%s',(self.org,))
            q.execute('DELETE FROM orgs WHERE id=%s',(self.org,))

    def run_async(self,awaitable): return asyncio.run(awaitable)

    def start(self,key='start',**kw):
        from psycopg2.extras import Json
        with self.client.connect() as conn,conn.cursor() as q:
            q.execute('INSERT INTO milo_director_documents(org_id,campaign_id,document) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                (self.org,self.campaign['id'],Json(dict(campaign_revision=2,storyboard=dict(revision=1,scenes=self.scenes,narration_approved=True)))))
        kw.setdefault('storyboard_revision',1)
        return self.run_async(self.store.create_run(self.org,self.campaign['id'],2,self.scenes,key,**kw))

    def claim(self): return self.run_async(self.store.claim())

    def finish(self,task):
        self.run_async(self.store.submitted(task,{'task_id':task['id']}))
        return self.run_async(self.store.complete(task,{'artifact_sha256':'a'*64,'video_url':'https://example.test/a.mp4'},
            {'passed':True}))

    def test_concurrent_creation_claim_and_completion_are_exactly_once(self):
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            runs=list(pool.map(lambda _:self.start(),range(8)))
        self.assertEqual(len({r['id'] for r in runs}),1)
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            claims=list(pool.map(lambda _:self.claim(),range(8)))
        self.assertEqual(sum(len(c) for c in claims),1)
        first=next(c[0] for c in claims if c)
        self.run_async(self.store.submitted(first,{'task_id':first['id']}))
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda _:self.run_async(self.store.complete(first,
                {'artifact_sha256':'a'*64},{'passed':True})),range(8)))
        second=self.claim()[0]
        self.assertEqual(second['scene_index'],2)
        self.finish(second)
        master=self.claim()[0]
        self.finish(master)
        self.run_async(self.store.complete(master,{}, {'passed':True}))
        with self.client.connect() as conn,conn.cursor() as q:
            q.execute('SELECT count(*) FROM drafts WHERE org_id=%s',(self.org,))
            self.assertEqual(q.fetchone()[0],1)
            q.execute('SELECT count(*) FROM milo_director_verified_tokens WHERE org_id=%s',(self.org,))
            self.assertEqual(q.fetchone()[0],2)
            q.execute("SELECT count(*) FROM workflow_events WHERE org_id=%s AND type='agent_run_step'",(self.org,))
            self.assertGreater(q.fetchone()[0],5)

    def test_tenant_signoff_supersession_and_sql_expiry_fence(self):
        run=self.start()
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.get(str(uuid.uuid4()),run['id']))
        task=self.claim()[0]
        with self.client.connect() as conn,conn.cursor() as q:
            q.execute("UPDATE milo_director_runs SET document=jsonb_set(document,'{tasks,0,lease_until}','0') WHERE id=%s",(run['id'],))
        with self.assertRaises(WorkflowConflict): self.finish(task)
        replacement=self.start('revision',parent_run_id=run['id'])
        self.assertEqual(self.run_async(self.store.get(self.org,run['id']))['superseded_by'],replacement['id'])
        claimed=self.claim()[0]
        self.assertEqual(claimed['run_id'],replacement['id'])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.create_run(self.org,self.campaign['id'],1,self.scenes,'bad',parent_run_id=replacement['id']))

    def test_retry_dag_and_event_rollback(self):
        run=self.start()
        for attempt in range(1,4):
            task=self.claim()[0]
            self.assertEqual(task['attempt'],attempt)
            self.run_async(self.store.fail(task,'caption missing'))
        self.assertEqual(self.run_async(self.store.get(self.org,run['id']))['state'],'BLOCKED')
        self.assertEqual(self.claim(),[])
        with self.client.connect() as conn,conn.cursor() as q:
            q.execute('SELECT count(*) FROM milo_director_scene_attempts WHERE run_id=%s',(run['id'],))
            self.assertEqual(q.fetchone()[0],3)
            q.execute('SELECT count(*) FROM milo_director_master_attempts WHERE run_id=%s',(run['id'],))
            self.assertEqual(q.fetchone()[0],0)

    def board(self):
        return dict(revision=1,narration_approved=False,scenes=[dict(scene_index=1,total_scenes=1,
            target_duration_sec=2,narration_chunk='Exact approved words',
            visual_directive=dict(prompt='Product',subject_action='Still',camera_movement='Static',lighting_style='Soft'),
            asset_constraints={},overlay_text=dict(text='Exact caption',end_sec=2))])

    def test_document_cas_narration_reapproval_and_stale_preview(self):
        docs=DirectorDocuments(self.repo)
        board=self.board()
        def initialize(_):
            return self.run_async(docs.command(self.org,self.campaign['id'],'initialize',
                board=board,campaign_revision=2,key='init'))
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            boards=list(pool.map(initialize,range(8)))
        self.assertTrue(all(b==Storyboard.model_validate(board).model_dump(mode='json') for b in boards))
        def approve(_):
            return self.run_async(docs.command(self.org,self.campaign['id'],'approve',expected_revision=1,key='approve'))
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            approved=list(pool.map(approve,range(8)))
        self.assertTrue(all(b['narration_approved'] for b in approved))
        preview=dict(base_revision=1,narration_changed=True,unresolved_instructions=[],scenes=board['scenes'])
        preview['scenes'][0]['narration_chunk']='New narration'
        saved=self.run_async(docs.preview(self.org,self.campaign['id'],1,preview))
        edited=self.run_async(docs.command(self.org,self.campaign['id'],'apply',expected_revision=1,
            preview_id=saved['preview_id'],key='apply'))
        self.assertEqual(edited['revision'],2)
        self.assertFalse(edited['narration_approved'])
        with self.assertRaises(WorkflowConflict):
            self.run_async(docs.command(self.org,self.campaign['id'],'apply',expected_revision=1,
                preview_id=saved['preview_id'],key='stale'))
        with self.assertRaises(WorkflowConflict):
            self.run_async(docs.get(str(uuid.uuid4()),self.campaign['id']))
        self.run_async(docs.command(self.org,self.campaign['id'],'approve',expected_revision=2,key='approve-2'))
        self.run_async(docs.command(self.org,self.campaign['id'],'started',expected_revision=1,key='started-old'))
        self.assertTrue(self.run_async(docs.document(self.org,self.campaign['id']))['pending_start'])

    def test_actual_leased_build_handoff_is_fenced(self):
        self.client.table('milo_jobs').insert(dict(org_id=self.org,campaign_id=self.campaign['id'],
            kind='build',payload={},dedup_key='handoff')).execute()
        job=self.run_async(MiloStore(self.repo).claim('build'))[0]
        docs=DirectorDocuments(self.repo)
        wrong={**job,'lease_token':str(uuid.uuid4())}
        with self.assertRaises(WorkflowConflict): self.run_async(docs.handoff(wrong))
        self.run_async(docs.handoff(job))
        with self.assertRaises(WorkflowConflict): self.run_async(docs.handoff(job))
        row=self.client.table('milo_jobs').select('*').eq('id',job['id']).execute().data[0]
        self.assertEqual(row['status'],'completed')

    def test_initial_signoff_atomically_binds_only_its_storyboard_revision(self):
        from types import SimpleNamespace
        from test_milo_director_contracts import scene
        from copy import deepcopy
        from services.milo.director.runtime import handoff_build
        self.client.table('brand_passports').insert({'org_id':self.org,'brand_name':'Director test'}).execute()
        milo=MiloStore(self.repo)
        helper=SimpleNamespace(store=milo,client=self.client,repo=self.repo,org=self.org,run_async=self.run_async)
        campaign=base.MiloPostgresTests.ready(helper)
        spec=scene();spec['narration_chunk']=campaign['artifact']['video_script'][0]['spoken_narration'];spec['overlay_text']['text']='Look'
        docs=DirectorDocuments(self.repo)
        self.run_async(docs.command(self.org,campaign['id'],'initialize',board={'revision':1,'scenes':[spec]},campaign_revision=campaign['revision'],key='initial'))
        approved=self.run_async(milo.decide_script(self.org,campaign['id'],'approve',campaign['revision'],'sign'))
        document=self.run_async(docs.document(self.org,campaign['id']))
        self.assertTrue(document['storyboard']['narration_approved'])
        self.assertEqual(document['campaign_revision'],approved['revision'])
        job=self.run_async(milo.claim('build'))[0]
        self.assertEqual(job['payload']['director_storyboard_revision'],1)
        for revision,text in ((1,'Different unsigned narration'),(2,spec['narration_chunk'])):
            changed=deepcopy(spec);changed['narration_chunk']=text
            preview=self.run_async(docs.preview(self.org,campaign['id'],revision,
                dict(base_revision=revision,scenes=[changed],narration_changed=True,unresolved_instructions=[])))
            self.run_async(docs.command(self.org,campaign['id'],'apply',expected_revision=revision,preview_id=preview['preview_id'],key=f'edit-{revision}'))
        self.run_async(handoff_build(self.repo,job))
        self.assertFalse(self.run_async(docs.document(self.org,campaign['id']))['storyboard']['narration_approved'])
        self.assertEqual(self.run_async(self.store.claim()),[])

    def test_event_and_aggregate_roll_back_on_late_commit_error(self):
        run=self.start()
        events=self.run_async(self.repo.read_events(self.org,0))
        mutated={**run,'state':'AWAITING_HITL','draft_id':'invalid-uuid','master_result':{},'inspection_report':{}}
        mutated['progress']=[*run['progress'],dict(id=str(uuid.uuid4()),state='AWAITING_HITL',message='rollback')]
        with self.assertRaises(Exception):
            self.run_async(self.store._rpc('commit',org=self.org,row=mutated,expected=run['version']))
        self.assertEqual(self.run_async(self.repo.read_events(self.org,0)),events)
        self.assertEqual(self.run_async(self.store.get(self.org,run['id'])),run)

    def test_edit_atomically_fences_old_run_and_draft_and_rejects_forged_approval(self):
        self.scenes=Storyboard.model_validate(self.board()).model_dump(mode='json')['scenes']
        run=self.start()
        self.finish(self.claim()[0])
        final=self.finish(self.claim()[0])
        docs=DirectorDocuments(self.repo)
        document=self.run_async(docs.document(self.org,self.campaign['id']))
        # Seed the reducer's remaining metadata, like an initialized real document.
        document.update(previews={},receipts={},pending_start=False)
        row=self.run_async(docs.get(self.org,self.campaign['id']))
        self.run_async(docs._rpc('commit',org=self.org,campaign=self.campaign['id'],
            document=document,expected_version=row['version']))
        changed=[{**self.scenes[0],'narration_chunk':'Replacement approved words'}]
        preview=self.run_async(docs.preview(self.org,self.campaign['id'],1,
            dict(base_revision=1,narration_changed=True,unresolved_instructions=[],scenes=changed)))
        edited=self.run_async(docs.command(self.org,self.campaign['id'],'apply',expected_revision=1,
            preview_id=preview['preview_id'],key='edit'))
        old=self.run_async(self.store.get(self.org,run['id']))
        self.assertTrue(old['document_fenced'])
        draft=self.client.table('drafts').select('*').eq('id',final['draft_id']).execute().data[0]
        self.assertTrue(draft['director_artifact']['superseded'])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.repo.transition_draft(self.org,final['draft_id'],'approve',1,'approve-stale'))
        feed=self.client.rpc('pending_approval_feed',{'p_org_id':self.org}).execute().data
        self.assertNotIn(final['draft_id'],[item['source_id'] for item in feed['items']])
        self.assertEqual(self.claim(),[])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.create_run(self.org,self.campaign['id'],2,changed,'forged',
                script_approved=True,parent_run_id=run['id'],storyboard_revision=edited['revision']))
        pending=self.run_async(self.store.create_run(self.org,self.campaign['id'],2,changed,'pending',
            script_approved=False,parent_run_id=run['id'],storyboard_revision=edited['revision']))
        self.assertEqual(pending['state'],'AWAITING_SCRIPT_APPROVAL')
        self.assertEqual(self.claim(),[])

    def test_recovery_receipt_is_org_scoped_and_replay_preserves_version(self):
        run=self.start()
        task=self.claim()[0]
        self.run_async(self.store.defer(task,'dependency unavailable'))
        first=self.run_async(self.store.recover(self.org,run['id'],key='recover',expected_revision=1))
        replay=self.run_async(self.store.recover(self.org,run['id'],key='recover',expected_revision=1))
        self.assertEqual(first,replay)
        branch=self.start('branch',parent_run_id=run['id'])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store.recover(self.org,branch['id'],key='recover',expected_revision=1))

    def test_product_scope_must_match_owned_active_campaign_product(self):
        product=self.client.table('brand_products').insert(dict(org_id=self.org,name='Selected SKU')).execute().data[0]
        self.client.table('milo_campaigns').update({'product_id':product['id']}).eq('id',self.campaign['id']).execute()
        with self.assertRaises(WorkflowConflict): self.start()
        run=self.start(product_id=product['id'])
        self.assertEqual(self.claim()[0]['product_id'],product['id'])
        self.client.table('brand_products').update({'deleted_at':'2026-11-02T00:00:00Z'}).eq('id',product['id']).execute()
        with self.assertRaises(WorkflowConflict): self.start('deleted-product',parent_run_id=run['id'],product_id=product['id'])

    def test_master_final_approval_allows_export_but_blocks_edit_and_delivery(self):
        self.start()
        self.finish(self.claim()[0])
        self.finish(self.claim()[0])
        master=self.finish(self.claim()[0])
        draft=master['draft_id']
        feed=self.client.rpc('pending_approval_feed',{'p_org_id':self.org}).execute().data
        item=next(i for i in feed['items'] if i['source_id']==draft)
        self.assertFalse(item['restrictions']['can_edit'])
        self.assertTrue(item['restrictions']['can_approve'])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.repo.transition_draft(self.org,draft,'edit',1,'edit',edited_content='Replacement'))
        approved=self.run_async(self.repo.transition_draft(self.org,draft,'approve',1,'approve'))
        self.assertEqual(approved['status'],'APPROVED')
        for action in ('begin_delivery','claim_delivery','publish'):
            with self.subTest(action=action),self.assertRaises(WorkflowConflict):
                self.run_async(self.repo.transition_draft(self.org,draft,action,2,action,
                    receipt={'attempt_id':'attempt','channel':'telegram','message_id':'123'}))
        with self.client.connect() as conn,conn.cursor() as q:
            with self.assertRaises(Exception):
                q.execute("UPDATE drafts SET director_artifact=jsonb_set(director_artifact,'{video_url}','\"https://example.test/forged.mp4\"') WHERE id=%s",(draft,))

    def test_raw_renderer_context_is_immutable_and_verified_tokens_keep_binding(self):
        context={'renderer':{'catalog_sha256':'a'*64,'configuration_sha256':'b'*64}}
        run=self.start(reuse_context=context)
        first=self.claim()[0]
        self.assertEqual(first['renderer_context'],context['renderer'])
        self.assertEqual(first['scene_prompts'],self.scenes)
        verified=self.finish(first)
        with self.client.connect() as conn,conn.cursor() as q:
            q.execute('SELECT document FROM milo_director_verified_tokens WHERE run_id=%s',(run['id'],))
            self.assertEqual(q.fetchone()[0]['reuse_context_hash'],run['reuse_context_hash'])
        forged={**verified,'reuse_context':{'renderer':{'catalog_sha256':'c'*64}}}
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.store._rpc('commit',org=self.org,row=forged,expected=verified['version']))
        self.assertEqual(self.run_async(self.store.get(self.org,run['id']))['reuse_context'],context)
