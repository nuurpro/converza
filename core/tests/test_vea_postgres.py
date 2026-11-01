"""Transactional parity gate against an explicitly isolated PostgreSQL database."""
import asyncio
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import AsyncMock,patch

from services.vea.store import VeaStore, prepare_build
from services.workflow.state import WorkflowConflict
import test_milo_postgres as milo_tests
from test_vea_storage import catalog_asset


@unittest.skipUnless(os.getenv('CONVERZA_WORKFLOW_TEST_DSN'),'requires isolated PostgreSQL test database')
class VeaPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        milo_tests.MiloPostgresTests.setUpClass()
        cls.client=milo_tests.MiloPostgresTests.client
        cls.repo=milo_tests.MiloPostgresTests.repo
        cls.store=milo_tests.MiloPostgresTests.store
        with cls.client.connect() as conn,conn.cursor() as q:
            q.execute((Path(__file__).resolve().parents[1]/'migrations'/'009_vea_variants.sql').read_text(encoding='utf-8'))

    setUp=milo_tests.MiloPostgresTests.setUp
    tearDown=milo_tests.MiloPostgresTests.tearDown
    ready=milo_tests.MiloPostgresTests.ready
    run_async=milo_tests.MiloPostgresTests.run_async

    def approved(self):
        c=self.ready()
        return self.run_async(self.store.decide_script(self.org,c['id'],'approve',c['revision'],'approve'))

    def result(self,c,v):
        from services.milo.video import build_binding
        job=next(j for j in self.run_async(self.store.jobs(self.org)) if j['id']==v['job_id'])
        binding=build_binding(job)
        preset={'id':v['preset_id'],'version':1}
        preset_sha=hashlib.sha256(json.dumps(preset,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        manifest={'segments':[{'segment_id':'scene-0-cut-0','asset_id':'a','start_ms':0,'end_ms':3000,'scene_index':0}],
                  'preset':preset,'preset_sha256':preset_sha,'duration_ms':3000,
                  'org_id':self.org,'script_sha256':binding['script_sha256'],'vea_config_sha256':binding['vea_config_sha256']}
        sha=hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        return dict(schema_version=1,id=v['id'],variant_revision=v['revision'],video_url='https://media.test/video.mp4',
            thumbnail_url='https://media.test/thumbnail.jpg',duration_sec=3.0,preset_used=v['preset_id'],preset_version=1,
            preset_sha256=preset_sha,source_milo_script_id=c['id'],approved_script_revision=c['revision']-1,
            composition_sha256=sha,render_telemetry={},composition_manifest=manifest)

    def test_concurrent_variant_creation_uses_one_job_and_default_binding(self):
        c=self.approved()
        vea=VeaStore(self.repo)
        def create(_):return self.run_async(vea.create_variant(self.org,c['id'],c['revision'],'editorial_showcase','create'))
        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            rows=list(pool.map(create,range(8)))
        self.assertEqual(len({r['id'] for r in rows}),1)
        jobs=self.run_async(self.store.claim('build',limit=10))
        self.assertEqual(len(jobs),2)
        default=next(j for j in jobs if not j['payload'].get('variant_id'))
        default=self.run_async(prepare_build(default,self.store))
        self.assertEqual(default,self.run_async(prepare_build(default,self.store)))
        self.assertTrue(next(v for v in self.run_async(vea.list_variants(self.org)) if v['job_id']==default['id'])['is_default'])
        self.assertEqual(default['payload']['vea_config']['clip_overrides'],[])

    def test_complete_swap_and_sql_review_fence_are_atomic(self):
        c=self.approved();vea=VeaStore(self.repo)
        job=self.run_async(prepare_build(self.run_async(self.store.claim('build'))[0],self.store))
        v=self.run_async(vea.list_variants(self.org))[0]
        c=self.run_async(self.store.complete_build(job,self.result(c,v)))
        v=self.run_async(vea.get_variant(self.org,v['id']))
        self.assertEqual(v['status'],'completed')
        draft=self.run_async(self.repo.get_draft(v['draft_id']))
        self.assertEqual(draft['vea_artifact']['id'],v['id'])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.repo.transition_draft(self.org,draft['id'],'edit',draft['revision'],'edit',edited_content='bad'))
        with patch('services.vea.store.fetch_renderer',AsyncMock(return_value={'assets':[catalog_asset(self.org)]})):
            replaced=self.run_async(vea.swap(self.org,v['id'],1,'scene-0-cut-0','replacement','swap'))
            replay=self.run_async(vea.swap(self.org,v['id'],1,'scene-0-cut-0','replacement','swap'))
        self.assertEqual(replaced,replay)
        self.assertEqual(replaced['revision'],2)
        old=self.run_async(self.repo.get_draft(draft['id']))
        self.assertEqual(old['status'],'REJECTED')
        self.assertTrue(old['vea_artifact']['superseded'])
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.repo.transition_draft(self.org,old['id'],'approve',old['revision'],'approve-old'))

    def test_ineligible_swap_preserves_approved_export_and_sql_state(self):
        c=self.approved();vea=VeaStore(self.repo)
        job=self.run_async(prepare_build(self.run_async(self.store.claim('build'))[0],self.store))
        variant=self.run_async(vea.list_variants(self.org))[0]
        self.run_async(self.store.complete_build(job,self.result(c,variant)))
        variant=self.run_async(vea.get_variant(self.org,variant['id']))
        draft=self.run_async(self.repo.get_draft(variant['draft_id']))
        draft=self.run_async(self.repo.transition_draft(self.org,draft['id'],'approve',draft['revision'],'approve-export'))

        def snapshot():
            return (self.run_async(vea.get_variant(self.org,variant['id'])),
                    self.run_async(self.repo.get_draft(draft['id'])),
                    self.run_async(self.store.jobs(self.org)),
                    self.client.table('vea_variant_revisions').select('*').eq('variant_id',variant['id']).execute().data,
                    self.client.table('vea_decisions').select('*').eq('org_id',self.org).execute().data)

        before=snapshot()
        self.assertEqual(draft['status'],'APPROVED')
        with patch('services.vea.store.fetch_renderer',AsyncMock(return_value={'assets':[
                catalog_asset(self.org, rights_confirmed=False, tags={'en':['Mountain landscape']})]})):
            with self.assertRaises(WorkflowConflict):
                self.run_async(vea.swap(self.org,variant['id'],1,'scene-0-cut-0','replacement','irrelevant'))
        self.assertEqual(snapshot(),before)

    def test_ambiguous_failure_stays_blocked_and_nondefault_keeps_compatibility(self):
        c=self.approved();vea=VeaStore(self.repo)
        variant=self.run_async(vea.create_variant(self.org,c['id'],c['revision'],'editorial_showcase','create'))
        jobs=self.run_async(self.store.claim('build',limit=10))
        default=self.run_async(prepare_build(next(j for j in jobs if not j['payload'].get('variant_id')),self.store))
        manual=next(j for j in jobs if j['id']==variant['job_id'])
        self.run_async(self.store.complete_build(manual,self.result(c,variant)))
        campaign=self.run_async(self.store.get_campaign(self.org,c['id']))
        self.assertIsNone(campaign['result'])
        self.assertEqual(campaign['build_status'],'running')
        self.run_async(self.store.update_build(default,{'submission_state':'submitting'}))
        self.run_async(self.store.fail(default,'timeout'))
        default_variant=next(v for v in self.run_async(vea.list_variants(self.org)) if v['is_default'])
        self.assertEqual(default_variant['status'],'failed')
        with self.assertRaises(WorkflowConflict):
            self.run_async(vea.retry(self.org,default_variant['id'],1,'retry'))

    def test_manual_lifecycle_preserves_legacy_default_result_and_status(self):
        c=self.approved()
        legacy=self.run_async(self.store.claim('build'))[0]
        c=self.run_async(self.store.complete_build(legacy,{'video_url':'https://media.test/legacy.mp4'}))
        legacy_result=c['result']
        vea=VeaStore(self.repo)
        row=self.run_async(vea.create_variant(self.org,c['id'],c['revision'],'editorial_showcase','manual'))
        manual=self.run_async(self.store.claim('build'))[0]
        c=self.run_async(self.store.get_campaign(self.org,c['id']))
        self.assertEqual(c['build_status'],'completed')
        self.assertEqual(c['result'],legacy_result)
        self.run_async(self.store.update_build(manual,{'submission_state':'provider_failed'}))
        self.run_async(self.store.fail(manual,'failure'))
        c=self.run_async(self.store.get_campaign(self.org,c['id']))
        self.assertEqual(c['build_status'],'completed')
        self.run_async(vea.retry(self.org,row['id'],1,'retry'))
        c=self.run_async(self.store.get_campaign(self.org,c['id']))
        self.assertEqual(c['build_status'],'completed')

    def test_sql_approval_rechecks_brand_and_rpc_is_not_public(self):
        import psycopg2
        c=self.approved();vea=VeaStore(self.repo)
        job=self.run_async(prepare_build(self.run_async(self.store.claim('build'))[0],self.store))
        v=self.run_async(vea.list_variants(self.org))[0]
        self.run_async(self.store.complete_build(job,self.result(c,v)))
        v=self.run_async(vea.get_variant(self.org,v['id']))
        draft=self.run_async(self.repo.get_draft(v['draft_id']))
        self.client.table('brand_passports').update({'brand_name':'Updated current brand'}).eq('org_id',self.org).execute()
        with self.assertRaises(WorkflowConflict):
            self.run_async(self.repo.transition_draft(self.org,draft['id'],'approve',draft['revision'],'stale-approve'))
        with self.client.connect() as conn,conn.cursor() as q:
            q.execute('SET LOCAL ROLE authenticated')
            with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                q.execute("SELECT vea_store('list','{}'::jsonb)")
            conn.rollback()
