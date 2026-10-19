import unittest
from services.indexer import validate_extraction


class IndexerTests(unittest.TestCase):
    def test_nonempty_source_requires_summary_and_at_least_one_atom(self):
        source={'id':'s','revision':1,'kind':'faq','content':'Training is included.','metadata':{}}
        for result in ({'summary':'Included training','atoms':[]},{'summary':' ','atoms':[{'kind':'fact','text':'Training is included.'}]}):
            with self.assertRaises(ValueError): validate_extraction(source,result)

    def test_resolution_timestamp_is_normalized_to_utc(self):
        source={'id':'s','revision':1,'kind':'objection','content':'Price?\n120 USD.',
            'metadata':{'inbound_text':'Price?','final_content':'120 USD.','status':'PUBLISHED','agent_slug':'sleyz','prospect_id':'p','delivered_at':'2026-10-19T13:00:00+05:00','resolved_at':'2026-10-19T13:02:00+05:00'}}
        result=validate_extraction(source,{'summary':'Current price answered.','atoms':[{'kind':'objection','objection':'Price?','answer':'120 USD.'}]})
        self.assertEqual(result['atoms'][0]['resolved_at'],'2026-10-19T08:02:00+00:00')

    def test_exact_quotes_and_server_resolution_timestamp(self):
        source = {'id':'s', 'revision':2, 'kind':'objection', 'content':'That is expensive!\nIt includes training.', 'metadata': {'inbound_text':'That is expensive!', 'final_content':'It includes training.', 'resolved_at':'2026-01-01T00:00:00+00:00', 'delivered_at':'2026-01-01T00:00:00+00:00', 'status':'PUBLISHED', 'agent_slug':'sleyz', 'prospect_id':'p'}}
        result = validate_extraction(source, {'summary':'Pricing concern addressed with included training.', 'atoms':[{'kind':'objection', 'objection':'That is expensive!', 'answer':'It includes training.', 'resolved_at':'fake'}]})
        atom = result['atoms'][0]
        self.assertEqual(atom['resolved_at'], source['metadata']['resolved_at'])
        self.assertEqual(atom['source_id'], 's')
        self.assertEqual(atom['objection_span'], [0,18])
        with self.assertRaises(ValueError): validate_extraction(source, {'summary':'x', 'atoms':[{'kind':'objection', 'objection':'Expensive', 'answer':'It includes training.'}]})

    def test_factual_sources_cannot_become_synthetic_objections(self):
        source = {'id':'s', 'revision':1, 'kind':'faq', 'content':'Shipping takes two days.', 'metadata':{}}
        with self.assertRaises(ValueError): validate_extraction(source, {'summary':'Shipping', 'atoms':[{'kind':'objection', 'objection':'Shipping', 'answer':'two days'}]})
        value = validate_extraction(source, {'summary':'Shipping duration.', 'atoms':[{'kind':'fact', 'text':'Shipping takes two days.'}]})
        self.assertEqual(value['atoms'][0]['span'], [0,24])

    def test_unresolved_or_undelivered_objection_rejected(self):
        for metadata in ({}, {'status':'APPROVED','resolved_at':'2026-01-01','delivered_at':'2026-01-01'}):
            with self.assertRaises(ValueError): validate_extraction({'id':'x','revision':1,'kind':'objection','content':'a\nb','metadata':metadata}, {'summary':'x','atoms':[]})



# Optional real PostgreSQL lane. Use a disposable test_converza* database only.
import os
import json
from pathlib import Path

@unittest.skipUnless(os.environ.get('MEMORY_TEST_DSN'), 'set MEMORY_TEST_DSN for PostgreSQL transactional tests')
class PostgreSQLMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        cls.psycopg2 = psycopg2
        cls.conn = psycopg2.connect(os.environ['MEMORY_TEST_DSN'])
        if not cls.conn.info.dbname.startswith('test_converza'):
            raise ValueError('Integration lane requires disposable test_converza database')
        cursor=cls.conn.cursor()
        cursor.execute("SELECT to_regclass('public.memory_sources')")
        if cursor.fetchone()[0] is None:
            root=Path(__file__).resolve().parents[1]
            cursor.execute((root/'services/indexer/tests/bootstrap.sql').read_text())
            cursor.execute((root/'migrations/004_brand_memory.sql').read_text())
            cls.conn.commit()

    def setUp(self):
        self.cur = self.conn.cursor()
        self.cur.execute('INSERT INTO orgs DEFAULT VALUES RETURNING id')
        self.org = self.cur.fetchone()[0]

    def tearDown(self):
        self.conn.rollback()

    @classmethod
    def tearDownClass(cls): cls.conn.close()

    def scalar(self, query, args=()):
        self.cur.execute(query,args)
        return self.cur.fetchone()[0]

    def product(self):
        return self.scalar('INSERT INTO brand_products(org_id,name,price,currency) VALUES(%s,%s,100,%s) RETURNING id',(self.org,'Training','USD'))

    def claim(self):
        self.cur.execute('SELECT id,source_id,source_revision,lease_token,attempts FROM memory_claim_jobs(1,120)')
        return self.cur.fetchone()

    def test_direct_edit_revision_and_obsolete_completion(self):
        p = self.product()
        first = self.claim()
        self.assertIsNotNone(first)
        self.cur.execute('UPDATE brand_products SET price=120 WHERE id=%s',(p,))
        self.assertFalse(self.scalar('SELECT memory_complete_job(%s,%s,%s,%s)',(first[0],first[3],'old price','[]')))
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_price_history WHERE org_id=%s',(self.org,)),2)
        self.assertEqual(self.scalar('SELECT revision FROM memory_sources WHERE org_id=%s',(self.org,)),2)
        self.assertEqual(self.scalar('SELECT summary FROM memory_sources WHERE org_id=%s',(self.org,)),'')
        self.assertIn('120', self.scalar('SELECT content FROM memory_sources WHERE org_id=%s',(self.org,)))

    def test_expired_lease_reclaim_fences_old_worker_and_retry(self):
        self.product()
        a=self.claim()
        self.cur.execute("UPDATE memory_index_jobs SET lease_until=now()-interval '1 second' WHERE id=%s",(a[0],))
        b=self.claim()
        self.assertEqual(a[0],b[0]); self.assertNotEqual(a[3],b[3])
        self.assertFalse(self.scalar('SELECT memory_complete_job(%s,%s,%s,%s)',(a[0],a[3],'stale','[]')))
        self.assertTrue(self.scalar('SELECT memory_fail_job(%s,%s,%s)',(b[0],b[3],'validation_error')))
        self.assertEqual(self.scalar('SELECT status FROM memory_index_jobs WHERE id=%s',(a[0],)),'pending')
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_claim_jobs(1,120)'),0)
        self.cur.execute("UPDATE memory_index_jobs SET attempts=4,available_at=now() WHERE id=%s",(a[0],))
        last=self.claim()
        self.assertTrue(self.scalar('SELECT memory_fail_job(%s,%s,%s)',(last[0],last[3],'validation_error')))
        self.assertEqual(self.scalar('SELECT status FROM memory_index_jobs WHERE id=%s',(a[0],)),'failed')
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_retry_job(gen_random_uuid(),%s)',(a[0],)),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_retry_job(%s,%s)',(self.org,a[0])),1)

    def test_forget_excludes_and_cancels_leased_revision(self):
        p=self.product(); job=self.claim()
        self.assertTrue(self.scalar("SELECT memory_forget(%s,'product',%s)",(self.org,p)))
        self.assertFalse(self.scalar('SELECT memory_complete_job(%s,%s,%s,%s)',(job[0],job[3],'deleted','[]')))
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_sources WHERE org_id=%s AND deleted_at IS NULL',(self.org,)),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_claim_jobs(1,120)'),0)

    def test_only_delivered_explicit_resolution_and_forget_stays_forgotten(self):
        d=self.scalar("INSERT INTO drafts(org_id,status,inbound_text,draft_content,agent_slug,prospect_id) VALUES(%s,'APPROVED','Too costly','Includes training','sleyz',gen_random_uuid()) RETURNING id",(self.org,))
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_sources WHERE org_id=%s',(self.org,)),0)
        self.cur.execute("UPDATE drafts SET status='PUBLISHED',delivered_at=now(),delivery_receipt='{}' WHERE id=%s",(d,))
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_sources WHERE org_id=%s',(self.org,)),0)
        self.cur.execute('UPDATE drafts SET resolved_at=now() WHERE id=%s',(d,))
        s=self.scalar('SELECT id FROM memory_sources WHERE org_id=%s',(self.org,))
        self.assertTrue(self.scalar('SELECT memory_forget_source(%s,%s)',(self.org,s)))
        self.cur.execute("UPDATE drafts SET final_content='Updated final answer' WHERE id=%s",(d,))
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_sources WHERE org_id=%s AND deleted_at IS NULL',(self.org,)),0)

    def test_backfill_idempotent_preserves_source_age_and_no_approval_classification(self):
        self.product()
        self.cur.execute('INSERT INTO brand_passports(org_id,brand_name,updated_at) VALUES(%s,%s,now()-interval \'60 days\')',(self.org,'Nova'))
        before=self.scalar('SELECT count(*) FROM memory_index_jobs WHERE org_id=%s',(self.org,))
        self.scalar('SELECT memory_backfill(%s)',(self.org,)); self.scalar('SELECT memory_backfill(%s)',(self.org,))
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_index_jobs WHERE org_id=%s',(self.org,)),before)
        self.assertGreater(self.scalar("SELECT extract(epoch FROM now()-updated_at)/86400 FROM memory_sources WHERE org_id=%s AND kind='passport'",(self.org,)),59)

    def test_tenant_records_cannot_be_transferred_and_service_rpcs_not_public(self):
        p=self.product()
        other=self.scalar('INSERT INTO orgs DEFAULT VALUES RETURNING id')
        self.cur.execute('SAVEPOINT change_org')
        with self.assertRaises(self.psycopg2.Error): self.cur.execute('UPDATE brand_products SET org_id=%s WHERE id=%s',(other,p))
        self.cur.execute('ROLLBACK TO SAVEPOINT change_org')
        self.assertFalse(self.scalar("SELECT has_function_privilege('authenticated','memory_claim_jobs(integer,integer)','EXECUTE')"))
        self.assertFalse(self.scalar("SELECT has_function_privilege('anon','memory_forget(uuid,text,uuid)','EXECUTE')"))

    def test_passport_faq_and_textual_pricing_are_versioned_facts_and_removal_tombstones(self):
        self.cur.execute('ALTER TABLE brand_passports ADD COLUMN IF NOT EXISTS faq jsonb, ADD COLUMN IF NOT EXISTS pricing jsonb, ADD COLUMN IF NOT EXISTS objections jsonb')
        p=self.scalar("INSERT INTO brand_passports(org_id,brand_name,faq,pricing,objections) VALUES(%s,'Nova',%s,%s,%s) RETURNING id",(self.org,json.dumps([{'question':'When?','answer':'Monday'}]),json.dumps([{'tier':'Starter','price':'$100/mo','features':['Coaching']}]),json.dumps(['Unverified historical notes'])))
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_sources WHERE org_id=%s',(self.org,)),4)
        self.assertEqual(self.scalar("SELECT count(*) FROM memory_sources WHERE org_id=%s AND kind='objection'",(self.org,)),0)
        self.cur.execute("UPDATE brand_passports SET pricing=%s,faq='[]' WHERE id=%s",(json.dumps([{'tier':'Starter','price':'$120/mo','features':['Coaching']}]),p))
        self.assertEqual(self.scalar("SELECT count(*) FROM memory_sources WHERE org_id=%s AND metadata->>'source_field'='faq' AND deleted_at IS NULL",(self.org,)),0)
        self.assertEqual(self.scalar("SELECT count(*) FROM memory_price_history WHERE org_id=%s AND currency='LEGACY'",(self.org,)),2)
        before=self.scalar('SELECT count(*) FROM memory_index_jobs WHERE org_id=%s',(self.org,))
        self.scalar('SELECT memory_backfill(%s)',(self.org,))
        self.assertEqual(self.scalar('SELECT count(*) FROM memory_index_jobs WHERE org_id=%s',(self.org,)),before)

    def test_concurrent_claimers_skip_locked(self):
        # Own transaction holds lease row lock; independent backend sees no claim.
        p=self.product()
        # Make fixture visible, then retain it only in this disposable database.
        self.conn.commit()
        self.claim()
        other=self.psycopg2.connect(os.environ['MEMORY_TEST_DSN'])
        try:
            other.cursor().execute("SET statement_timeout='2s'")
            cursor=other.cursor(); cursor.execute('SELECT count(*) FROM memory_claim_jobs(1,120)')
            self.assertEqual(cursor.fetchone()[0],0)
        finally:
            other.rollback(); other.close(); self.conn.rollback()
            # Avoid triggers on test fixture cleanup; tombstone cancels job durably.
            self.cur.execute("SELECT memory_forget(%s,'product',%s)",(self.org,p)); self.conn.commit()

class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_validates_extracts_and_fences_completion(self):
        from services.indexer import IndexWorker
        source={'id':'s','org_id':'a','revision':2,'kind':'faq','content':'Shipping takes two days.','metadata':{}}
        job={'id':'j','source_id':'s','org_id':'a','source_revision':2,'lease_token':'token','attempts':1}
        calls=[]
        class Query:
            def __init__(self,data): self.data=data
            def select(self,*args): return self
            def eq(self,*args): return self
            def is_(self,*args): return self
            def limit(self,*args): return self
            def execute(self): return self
        class Client:
            def rpc(self,name,args):
                calls.append((name,args))
                return Query([job] if name=='memory_claim_jobs' else True)
            def table(self,name): return Query([source])
        async def extractor(row): return {'summary':'Delivery duration','atoms':[{'kind':'fact','text':row['content']}]}
        self.assertEqual(await IndexWorker(Client(),extractor).run_once(),1)
        complete=calls[-1]
        self.assertEqual(complete[0],'memory_complete_job')
        self.assertEqual(complete[1]['p_token'],'token')
        self.assertEqual(complete[1]['p_atoms'][0]['source_revision'],2)
        async def invalid(row): return {'summary':'Delivery','atoms':[{'kind':'fact','text':'Invented three days'}]}
        await IndexWorker(Client(),invalid).run_once()
        self.assertEqual(calls[-1][0],'memory_fail_job')
        self.assertEqual(calls[-1][1]['p_error'],'ValueError')


if __name__ == '__main__': unittest.main()
