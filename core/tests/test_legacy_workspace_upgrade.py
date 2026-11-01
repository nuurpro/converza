"""Real SQL bridge regressions, exclusively in an empty loopback test_* database."""
import os
from pathlib import Path
import unittest
import uuid

DSN = os.getenv('CONVERZA_LEGACY_TEST_DSN')
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(DSN, 'requires isolated legacy-upgrade PostgreSQL database')
class LegacyWorkspaceUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        from psycopg2.extensions import parse_dsn
        config = parse_dsn(DSN)
        if (config.get('host') not in ('127.0.0.1','localhost','::1')
                or config.get('hostaddr',config.get('host')) != config.get('host')
                or not config.get('dbname','').startswith('test_') or config.get('service')):
            raise RuntimeError('Legacy upgrade tests require a disposable loopback test_* database')
        cls.connect = staticmethod(lambda: psycopg2.connect(DSN))
        with cls.connect() as c, c.cursor() as q:
            q.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
            if q.fetchone()[0]:
                raise RuntimeError('Legacy upgrade fixture database must be empty')

    def setUp(self):
        self.db=self.connect()
        self.q=self.db.cursor()
        self.q.execute("""
          DO $$ BEGIN CREATE ROLE service_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
          DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
          DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
          CREATE SCHEMA IF NOT EXISTS auth;
          CREATE TABLE auth.users(id uuid PRIMARY KEY);
          CREATE TABLE orgs(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),name text,created_at timestamptz DEFAULT now());
          CREATE TABLE brand_passports(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id text UNIQUE NOT NULL,
            owner_user_id uuid REFERENCES auth.users(id),brand_name text NOT NULL,core_offer text,tone text,
            faq jsonb,pricing jsonb,objections jsonb,updated_at timestamptz DEFAULT now(),created_at timestamptz DEFAULT now(),
            industry text,target_audience text,target_location text,hex_colors text[]);
          CREATE TABLE prospects(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id text NOT NULL,
            tg_user_id bigint NOT NULL,tg_chat_id bigint NOT NULL,platform text NOT NULL DEFAULT 'telegram',external_id text,
            conversation_id uuid,UNIQUE(org_id,tg_user_id));
          CREATE TABLE messages(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id text NOT NULL,
            prospect_id uuid REFERENCES prospects(id),content text);
          CREATE TABLE drafts(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id text NOT NULL,
            prospect_id uuid REFERENCES prospects(id),inbound_text text,draft_content text,final_content text,
            status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','edited','rejected')),
            created_at timestamptz DEFAULT now(),decided_at timestamptz,updated_at timestamptz DEFAULT now());
          CREATE TABLE tg_connections(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id text UNIQUE NOT NULL,
            bot_token text NOT NULL,hitl_chat_id bigint NOT NULL);
          ALTER TABLE brand_passports ENABLE ROW LEVEL SECURITY;
          ALTER TABLE prospects ENABLE ROW LEVEL SECURITY;
          ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
          ALTER TABLE drafts ENABLE ROW LEVEL SECURITY;
          ALTER TABLE tg_connections ENABLE ROW LEVEL SECURITY;
        """)
        self.owner=str(uuid.uuid4())
        self.canonical=str(uuid.uuid4())
        self.q.execute('INSERT INTO auth.users VALUES(%s)',(self.owner,))
        for legacy, owner in (('old-festival',None),(self.canonical,self.owner)):
            self.q.execute('INSERT INTO brand_passports(org_id,owner_user_id,brand_name) VALUES(%s,%s,%s)',(legacy,owner,legacy))
            self.q.execute("INSERT INTO prospects(org_id,tg_user_id,tg_chat_id,external_id) VALUES(%s,7,8,'7') RETURNING id",(legacy,))
            prospect=self.q.fetchone()[0]
            self.q.execute("INSERT INTO messages(org_id,prospect_id,content) VALUES(%s,%s,'Preserved DM')",(legacy,prospect))
            for status in ('pending','approved','edited','rejected'):
                self.q.execute("INSERT INTO drafts(org_id,prospect_id,status,draft_content) VALUES(%s,%s,%s,'Preserved draft')",(legacy,prospect,status))
            self.q.execute("INSERT INTO tg_connections(org_id,bot_token,hitl_chat_id) VALUES(%s,'fixture-not-a-real-token',8)",(legacy,))
        for name in ('001_agent_switchboard.sql','002_service_role_switchboard_policies.sql'):
            self.q.execute((ROOT/'migrations'/name).read_text(encoding='utf-8'))
        self.agent_org=str(uuid.uuid4())
        self.q.execute("INSERT INTO orgs(id,name) VALUES(%s,'Existing unrelated agent workspace')",(self.agent_org,))
        self.q.execute("INSERT INTO agent_runs(org_id,agent_slug,triggered_by,input_text) VALUES(%s,'milo','owner','Historical input') RETURNING id",(self.agent_org,))
        self.agent_run=self.q.fetchone()[0]
        self.q.execute("INSERT INTO agent_run_steps(agent_run_id,org_id,agent_slug,step_label,step_status) VALUES(%s,%s,'milo','Historical step','completed')",(self.agent_run,self.agent_org))
        self.q.execute("INSERT INTO squad_messages(org_id,sender_slug,content,related_run_id) VALUES(%s,'milo','Historical message',%s)",(self.agent_org,self.agent_run))

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def bridge(self):
        self.q.execute((ROOT/'compatibility/legacy_workspace.sql').read_text(encoding='utf-8'))

    def test_exact_identity_preserves_owned_and_unowned_records(self):
        self.bridge()
        self.q.execute('SELECT org_id,owner_user_id FROM brand_passports WHERE owner_user_id IS NOT NULL')
        self.assertEqual(self.q.fetchone(),(self.canonical,self.owner))
        self.q.execute("SELECT org_id FROM converza_private.legacy_workspace_map WHERE legacy_org_id='old-festival'")
        recovered=self.q.fetchone()[0]
        self.assertNotEqual(recovered,self.canonical)
        self.q.execute('SELECT owner_user_id FROM brand_passports WHERE org_id=%s',(recovered,))
        self.assertIsNone(self.q.fetchone()[0])
        for table, count in (('brand_passports',1),('prospects',1),('messages',1),('drafts',4),('tg_connections',1)):
            self.q.execute(f'SELECT count(*) FROM {table} WHERE org_id=%s',(recovered,))
            self.assertEqual(self.q.fetchone()[0],count)
        self.q.execute("SELECT has_schema_privilege('anon','converza_private','USAGE'),has_table_privilege('authenticated','converza_private.legacy_workspace_map','SELECT')")
        self.assertEqual(self.q.fetchone(),(False,False))

    def test_full_prerequisite_chain_and_real_inbound_acceptance(self):
        self.q.execute('SELECT id,draft_content,status FROM drafts ORDER BY id')
        history=self.q.fetchall()
        self.bridge()
        for path in sorted((ROOT/'migrations').glob('*.sql')):
            self.q.execute(path.read_text(encoding='utf-8'))
        for id,content,status in history:
            self.q.execute('SELECT draft_content,status,delivery_status FROM drafts WHERE id=%s',(id,))
            expected='AWAITING_HITL' if status=='pending' else status.upper()
            self.assertEqual(self.q.fetchone(),(content,expected,'idle'))
        self.q.execute('SELECT count(*) FROM workflow_events')
        self.assertEqual(self.q.fetchone()[0],0)
        self.q.execute('SELECT count(*) FROM sleyz_learning_jobs')
        self.assertEqual(self.q.fetchone()[0],0)
        self.q.execute('SELECT count(*) FROM milo_jobs')
        self.assertEqual(self.q.fetchone()[0],0)
        self.q.execute('SELECT org_id,input_text FROM agent_runs WHERE id=%s',(self.agent_run,))
        self.assertEqual(self.q.fetchone(),(self.agent_org,'Historical input'))
        self.q.execute('SELECT related_run_id,content FROM squad_messages WHERE org_id=%s',(self.agent_org,))
        self.assertEqual(self.q.fetchone(),(self.agent_run,'Historical message'))
        from psycopg2.extras import Json
        self.q.execute('SELECT sleyz_accept_inbound(%s)',(Json({
            'org_id':self.canonical,'platform':'instagram','customer_id':'fixture-customer',
            'connection_id':'fixture','external_message_id':'fixture-1','text':'Price?',
            'simulated':True,'received_at':'2026-11-01T00:00:00Z'}),))
        self.assertFalse(self.q.fetchone()[0]['duplicate'])
        self.q.execute('SELECT pending_approval_feed(%s)',(self.canonical,))
        self.assertIsInstance(self.q.fetchone()[0],dict)
        self.q.execute('SELECT workspace_save_passport(%s,%s,%s)',(self.owner,self.canonical,Json({'brand_name':'Owned restored brand'})))
        self.assertEqual(self.q.fetchone()[0]['org_id'],self.canonical)

    def test_canonical_uuid_collision_aborts_instead_of_merging_tenants(self):
        self.q.execute("INSERT INTO brand_passports(org_id,brand_name) VALUES(%s,'Collision')",(self.canonical.upper(),))
        with self.assertRaises(Exception):
            self.bridge()

    def test_bridge_is_transactional_and_legacy_states_are_preserved(self):
        self.q.execute('SAVEPOINT before_bridge')
        self.bridge()
        self.q.execute('ROLLBACK TO SAVEPOINT before_bridge')
        self.q.execute("SELECT data_type FROM information_schema.columns WHERE table_name='brand_passports' AND column_name='org_id'")
        self.assertEqual(self.q.fetchone()[0],'text')
        self.q.execute('SELECT count(*) FROM orgs')
        self.assertEqual(self.q.fetchone()[0],1)

    def test_blank_tenant_is_rejected_before_any_conversion(self):
        self.q.execute("INSERT INTO brand_passports(org_id,brand_name) VALUES('','Invalid')")
        with self.assertRaises(Exception):
            self.bridge()

    def test_cross_tenant_history_is_rejected_not_reassigned(self):
        self.q.execute("UPDATE messages SET org_id=%s WHERE org_id='old-festival'",(self.canonical,))
        with self.assertRaisesRegex(Exception,'disagree on tenant'):
            self.bridge()

    def test_child_only_key_cannot_claim_existing_agent_workspace(self):
        self.q.execute("INSERT INTO prospects(org_id,tg_user_id,tg_chat_id) VALUES(%s,999,999)",(self.agent_org,))
        with self.assertRaisesRegex(Exception,'overlaps existing canonical workspace'):
            self.bridge()

    def test_explicit_snapshot_audit_preserves_existing_root_without_changing_it(self):
        self.q.execute("INSERT INTO prospects(org_id,tg_user_id,tg_chat_id) VALUES(%s,999,999)",(self.agent_org,))
        self.q.execute('SELECT jsonb_agg(to_jsonb(o)) FROM orgs o')
        audit=self.q.fetchone()[0]
        from psycopg2.extras import Json
        self.q.execute("SELECT set_config('converza.legacy_org_audit',%s,true)",(Json(audit),))
        self.bridge()
        self.q.execute('SELECT id,name FROM orgs WHERE id=%s',(self.agent_org,))
        self.assertEqual(self.q.fetchone(),(self.agent_org,'Existing unrelated agent workspace'))
        self.q.execute('SELECT count(*) FROM brand_passports WHERE org_id=%s',(self.agent_org,))
        self.assertEqual(self.q.fetchone()[0],0)

    def test_stale_or_forged_existing_root_audit_is_rejected(self):
        self.q.execute("INSERT INTO prospects(org_id,tg_user_id,tg_chat_id) VALUES(%s,999,999)",(self.agent_org,))
        self.q.execute('SELECT jsonb_agg(to_jsonb(o)) FROM orgs o')
        audit=self.q.fetchone()[0]
        audit[0]['name']='Unverified root'
        from psycopg2.extras import Json
        self.q.execute("SELECT set_config('converza.legacy_org_audit',%s,true)",(Json(audit),))
        with self.assertRaisesRegex(Exception,'overlaps existing canonical workspace'):
            self.bridge()

    def test_owned_passport_cannot_attach_to_audited_child_only_root(self):
        self.q.execute('SELECT jsonb_agg(to_jsonb(o)) FROM orgs o')
        audit=self.q.fetchone()[0]
        from psycopg2.extras import Json
        self.q.execute("SELECT set_config('converza.legacy_org_audit',%s,true)",(Json(audit),))
        self.q.execute("INSERT INTO brand_passports(org_id,brand_name,owner_user_id) VALUES(%s,'Unverified attachment',%s)",(self.agent_org,self.owner))
        with self.assertRaisesRegex(Exception,'overlaps existing canonical workspace'):
            self.bridge()

    def test_workflow_functions_are_private_with_supabase_default_grants(self):
        self.q.execute('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon,authenticated')
        self.bridge()
        for path in sorted((ROOT/'migrations').glob('*.sql')):
            self.q.execute(path.read_text(encoding='utf-8'))
        self.q.execute("SELECT proname FROM pg_proc WHERE pronamespace='public'::regnamespace AND proname LIKE 'workflow_%' AND (has_function_privilege('anon',oid,'EXECUTE') OR has_function_privilege('authenticated',oid,'EXECUTE'))")
        self.assertEqual(self.q.fetchall(),[])
        self.q.execute("SELECT has_function_privilege('service_role','workflow_snapshot(uuid)','EXECUTE')")
        self.assertTrue(self.q.fetchone()[0])
