-- Additive, service-only autonomous director. Prior Milo queues remain unchanged.
-- Aggregates are version-CAS committed under workflow_lock; all projections,
-- progress events and final HITL insertion share the same database transaction.
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS director_artifact jsonb;
CREATE TABLE IF NOT EXISTS milo_director_runs (
 id uuid PRIMARY KEY, org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 campaign_id uuid NOT NULL REFERENCES milo_campaigns(id) ON DELETE CASCADE,
 dedup_key text NOT NULL, version bigint NOT NULL, document jsonb NOT NULL,
 superseded_by uuid REFERENCES milo_director_runs(id) DEFERRABLE INITIALLY DEFERRED,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(org_id,campaign_id,dedup_key), UNIQUE(org_id,id)
);
CREATE UNIQUE INDEX IF NOT EXISTS milo_director_one_active ON milo_director_runs(org_id,campaign_id) WHERE superseded_by IS NULL;
CREATE TABLE IF NOT EXISTS milo_director_run_revisions (
 run_id uuid PRIMARY KEY REFERENCES milo_director_runs(id) ON DELETE CASCADE,
 org_id uuid NOT NULL, campaign_id uuid NOT NULL, approved_revision bigint NOT NULL,
 storyboard_revision bigint NOT NULL, scenes jsonb NOT NULL,
 FOREIGN KEY(org_id,run_id) REFERENCES milo_director_runs(org_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS milo_director_scene_attempts (
 id uuid PRIMARY KEY, org_id uuid NOT NULL, run_id uuid NOT NULL,
 scene_index integer NOT NULL CHECK(scene_index BETWEEN 1 AND 12),
 attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3),
 parent_attempt_id uuid REFERENCES milo_director_scene_attempts(id), document jsonb NOT NULL,
 UNIQUE(run_id,scene_index,attempt),
 FOREIGN KEY(org_id,run_id) REFERENCES milo_director_runs(org_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS milo_director_master_attempts (
 id uuid PRIMARY KEY, org_id uuid NOT NULL, run_id uuid NOT NULL,
 attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3),
 parent_attempt_id uuid REFERENCES milo_director_master_attempts(id), document jsonb NOT NULL,
 UNIQUE(run_id,attempt),
 FOREIGN KEY(org_id,run_id) REFERENCES milo_director_runs(org_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS milo_director_verifications (
 task_id uuid PRIMARY KEY, org_id uuid NOT NULL, run_id uuid NOT NULL,
 document jsonb NOT NULL,
 FOREIGN KEY(org_id,run_id) REFERENCES milo_director_runs(org_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS milo_director_verified_tokens (
 token uuid PRIMARY KEY, org_id uuid NOT NULL, run_id uuid NOT NULL,
 task_id uuid NOT NULL REFERENCES milo_director_scene_attempts(id),
 specification_sha256 text NOT NULL, artifact_sha256 text NOT NULL, document jsonb NOT NULL,
 FOREIGN KEY(org_id,run_id) REFERENCES milo_director_runs(org_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS milo_director_queue_intents (
 task_id uuid PRIMARY KEY, org_id uuid NOT NULL, run_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('scene','master')), status text NOT NULL,
 lease_token uuid, lease_until timestamptz, idempotency_key text NOT NULL UNIQUE,
 document jsonb NOT NULL,
 FOREIGN KEY(org_id,run_id) REFERENCES milo_director_runs(org_id,id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS milo_director_queue_ready ON milo_director_queue_intents(status,lease_until);
CREATE TABLE IF NOT EXISTS milo_director_recovery_receipts (
 org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, key text NOT NULL,
 run_id uuid NOT NULL REFERENCES milo_director_runs(id) ON DELETE CASCADE,
 fingerprint text NOT NULL, PRIMARY KEY(org_id,key)
);

CREATE OR REPLACE FUNCTION milo_director_store(p_action text,p_args jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE o uuid:=(p_args->>'org')::uuid; r jsonb:=p_args->'row';
 old milo_director_runs; parent milo_director_runs; c milo_campaigns;
 v bigint:=(p_args->>'expected')::bigint; x jsonb; t jsonb; n integer; rid uuid; approved_document jsonb;
BEGIN
 IF p_action='candidates' THEN
  RETURN coalesce((SELECT jsonb_agg(document ORDER BY created_at) FROM milo_director_runs
   WHERE superseded_by IS NULL AND NOT coalesce((document->>'document_fenced')::boolean,false)
    AND document->>'state' NOT IN ('BLOCKED','AWAITING_HITL','AWAITING_SCRIPT_APPROVAL')),'[]');
 ELSIF p_action='get' THEN
  RETURN (SELECT document FROM milo_director_runs WHERE org_id=o AND id=(p_args->>'id')::uuid);
 ELSIF p_action='list' THEN
  RETURN coalesce((SELECT jsonb_agg(document ORDER BY created_at DESC) FROM milo_director_runs
   WHERE org_id=o AND campaign_id=(p_args->>'campaign_id')::uuid),'[]');
 ELSIF p_action<>'commit' THEN RAISE EXCEPTION 'workflow_conflict: unknown director operation'; END IF;
 IF o IS NULL OR o IS DISTINCT FROM (r->>'org_id')::uuid THEN
  RAISE EXCEPTION 'workflow_conflict: director tenant required'; END IF;
 PERFORM workflow_lock(o);
 rid:=(r->>'id')::uuid;
 SELECT * INTO old FROM milo_director_runs WHERE id=rid FOR UPDATE;
 IF v=-1 THEN
  SELECT * INTO old FROM milo_director_runs WHERE org_id=o AND campaign_id=(r->>'campaign_id')::uuid AND dedup_key=r->>'key';
  IF FOUND THEN
   IF old.document->>'request_hash' IS DISTINCT FROM r->>'request_hash' THEN
    RAISE EXCEPTION 'workflow_conflict: director key reused'; END IF;
   RETURN old.document;
  END IF;
  SELECT * INTO c FROM milo_campaigns WHERE org_id=o AND id=(r->>'campaign_id')::uuid FOR UPDATE;
  IF NOT FOUND OR ((r->>'script_approved')::boolean AND
    (c.script_status<>'approved' OR c.revision<>(r->>'approved_revision')::bigint)) THEN
   RAISE EXCEPTION 'workflow_conflict: director requires current narration signoff'; END IF;
  IF c.product_id IS DISTINCT FROM r->>'product_id' THEN
   RAISE EXCEPTION 'workflow_conflict: director selected product changed'; END IF;
  PERFORM milo_assert_product(o,c.product_id);
  IF c.artifact IS NOT NULL AND (r->>'script_approved')::boolean THEN
   PERFORM milo_assert_evidence(o,c.artifact);
  END IF;
  SELECT document INTO approved_document FROM milo_director_documents
   WHERE org_id=o AND campaign_id=c.id;
  IF approved_document IS NULL
   OR (approved_document->>'campaign_revision')::bigint<>(r->>'approved_revision')::bigint
   OR approved_document->'storyboard'->>'revision' IS DISTINCT FROM r->>'storyboard_revision'
   OR approved_document->'storyboard'->'scenes' IS DISTINCT FROM
      (SELECT jsonb_agg(value->'specification' ORDER BY ord) FROM jsonb_array_elements(r->'scenes') WITH ORDINALITY AS a(value,ord))
   OR ((r->>'script_approved')::boolean AND NOT coalesce((approved_document->'storyboard'->>'narration_approved')::boolean,false))
   THEN RAISE EXCEPTION 'workflow_conflict: latest storyboard signoff required'; END IF;
  IF r->>'parent_run_id' IS NOT NULL THEN
   SELECT * INTO parent FROM milo_director_runs WHERE org_id=o AND campaign_id=c.id
    AND id=(r->>'parent_run_id')::uuid FOR UPDATE;
   IF NOT FOUND OR parent.superseded_by IS NOT NULL OR parent.version<>(p_args->>'parent_version')::bigint THEN RETURN NULL; END IF;
   t:=jsonb_build_object('id',gen_random_uuid(),'run_id',parent.id,'state','SUPERSEDED',
     'storyboard_revision',parent.document->'storyboard_revision','scene_index',parent.document->'scene_index',
     'scene_count',jsonb_array_length(parent.document->'scenes'),'attempt',0,'message','New storyboard production supersedes this run');
   UPDATE milo_director_runs SET superseded_by=rid,version=version+1,
    document=document||jsonb_build_object('superseded_by',rid,'state','SUPERSEDED','version',version+1,
       'progress',(document->'progress')||jsonb_build_array(t)) WHERE id=parent.id;
   INSERT INTO agent_run_steps(id,agent_run_id,org_id,agent_slug,step_label,step_status,detail)
    VALUES((t->>'id')::uuid,parent.id,o,'milo','SUPERSEDED','completed',t::text);
   UPDATE drafts SET director_artifact=coalesce(director_artifact,'{}')||jsonb_build_object('superseded',true,'superseded_by',rid),
    updated_at=clock_timestamp() WHERE org_id=o AND id=(parent.document->>'draft_id')::uuid;
  ELSIF EXISTS(SELECT 1 FROM milo_director_runs WHERE org_id=o AND campaign_id=c.id AND superseded_by IS NULL) THEN
   RAISE EXCEPTION 'workflow_conflict: active director exists';
  END IF;
  r:=r||jsonb_build_object('version',0);
  INSERT INTO agent_runs(id,org_id,agent_slug,triggered_by,input_text,status)
   VALUES(rid,o,'milo','agent','Autonomous video director','running');
  INSERT INTO milo_director_runs(id,org_id,campaign_id,dedup_key,version,document)
   VALUES(rid,o,c.id,r->>'key',0,r);
  INSERT INTO milo_director_run_revisions(run_id,org_id,campaign_id,approved_revision,storyboard_revision,scenes)
   VALUES(rid,o,c.id,(r->>'approved_revision')::bigint,(r->>'storyboard_revision')::bigint,r->'scenes');
  n:=0;
 ELSE
  IF old.id IS NULL OR old.org_id<>o THEN RAISE EXCEPTION 'workflow_conflict: director owner'; END IF;
  IF old.version<>v OR old.superseded_by IS NOT NULL OR coalesce((old.document->>'document_fenced')::boolean,false) THEN RETURN NULL; END IF;
  IF r->>'campaign_id' IS DISTINCT FROM old.document->>'campaign_id'
   OR r->>'approved_revision' IS DISTINCT FROM old.document->>'approved_revision'
   OR r->>'storyboard_revision' IS DISTINCT FROM old.document->>'storyboard_revision'
   OR r->'transitions' IS DISTINCT FROM old.document->'transitions'
   OR r->>'background_asset_id' IS DISTINCT FROM old.document->>'background_asset_id'
   OR r->>'product_id' IS DISTINCT FROM old.document->>'product_id'
   OR r->>'reuse_context_hash' IS DISTINCT FROM old.document->>'reuse_context_hash' THEN
    RAISE EXCEPTION 'workflow_conflict: immutable director revision'; END IF;
  IF r->'reuse_context' IS DISTINCT FROM old.document->'reuse_context' THEN
    RAISE EXCEPTION 'workflow_conflict: immutable director revision'; END IF;
  IF p_args->'fence' IS NOT NULL AND p_args->'fence'<>'null'::jsonb THEN
   SELECT value INTO t FROM jsonb_array_elements(old.document->'tasks') WHERE value->>'id'=p_args->'fence'->>'id';
   IF t IS NULL OR (t->>'status'<>'completed' AND (t->>'lease_token' IS DISTINCT FROM p_args->'fence'->>'lease_token'
      OR (t->>'lease_until')::double precision<=extract(epoch FROM clock_timestamp()))) THEN
    RAISE EXCEPTION 'workflow_conflict: stale director fence'; END IF;
  END IF;
  n:=jsonb_array_length(old.document->'progress');
  r:=r||jsonb_build_object('version',v+1);
  UPDATE milo_director_runs SET version=v+1,document=r WHERE id=rid;
 END IF;
 FOR x IN SELECT jsonb_build_object('key',key,'fingerprint',value->>'fingerprint') FROM jsonb_each(coalesce(r->'recovery_receipts','{}')) LOOP
  IF EXISTS(SELECT 1 FROM milo_director_recovery_receipts WHERE org_id=o AND key=x->>'key' AND fingerprint<>x->>'fingerprint') THEN
   RAISE EXCEPTION 'workflow_conflict: director recovery key reused'; END IF;
  INSERT INTO milo_director_recovery_receipts(org_id,key,run_id,fingerprint)
   VALUES(o,x->>'key',rid,x->>'fingerprint') ON CONFLICT DO NOTHING;
 END LOOP;
 FOR x IN SELECT value FROM jsonb_array_elements(r->'tasks') LOOP
  IF x->>'kind'='scene' THEN
   INSERT INTO milo_director_scene_attempts(id,org_id,run_id,scene_index,attempt,parent_attempt_id,document)
    VALUES((x->>'id')::uuid,o,rid,(x->>'scene_index')::int,(x->>'attempt')::int,(x->>'parent_attempt_id')::uuid,x)
    ON CONFLICT(id) DO UPDATE SET document=excluded.document;
  ELSE
   INSERT INTO milo_director_master_attempts(id,org_id,run_id,attempt,parent_attempt_id,document)
    VALUES((x->>'id')::uuid,o,rid,(x->>'attempt')::int,(x->>'parent_attempt_id')::uuid,x)
    ON CONFLICT(id) DO UPDATE SET document=excluded.document;
  END IF;
  INSERT INTO milo_director_queue_intents(task_id,org_id,run_id,kind,status,lease_token,lease_until,idempotency_key,document)
   VALUES((x->>'id')::uuid,o,rid,x->>'kind',x->>'status',(x->>'lease_token')::uuid,
    to_timestamp((x->>'lease_until')::double precision),x->>'idempotency_key',x)
   ON CONFLICT(task_id) DO UPDATE SET status=excluded.status,lease_token=excluded.lease_token,
    lease_until=excluded.lease_until,document=excluded.document;
  IF x->'verification' IS NOT NULL AND x->'verification'<>'null'::jsonb THEN
   INSERT INTO milo_director_verifications(task_id,org_id,run_id,document)
    VALUES((x->>'id')::uuid,o,rid,x->'verification') ON CONFLICT DO NOTHING;
  END IF;
 END LOOP;
 FOR x IN SELECT value FROM jsonb_array_elements(r->'scenes') LOOP
  t:=x->'verified';
  IF t IS NOT NULL AND t<>'null'::jsonb AND EXISTS(SELECT 1 FROM milo_director_scene_attempts WHERE id=(t->>'source_attempt_id')::uuid AND org_id=o) THEN
   INSERT INTO milo_director_verified_tokens(token,org_id,run_id,task_id,specification_sha256,artifact_sha256,document)
    VALUES((t->>'token')::uuid,o,rid,(t->>'source_attempt_id')::uuid,x->>'spec_hash',t->>'artifact_sha256',t) ON CONFLICT DO NOTHING;
  END IF;
 END LOOP;
 FOR x IN SELECT value FROM jsonb_array_elements(r->'progress') WITH ORDINALITY AS a(value,ord) WHERE ord>n LOOP
  INSERT INTO agent_run_steps(id,agent_run_id,org_id,agent_slug,step_label,step_status,detail)
   VALUES((x->>'id')::uuid,rid,o,'milo',x->>'state',CASE WHEN x->>'state'='BLOCKED' THEN 'failed' ELSE 'completed' END,x::text);
 END LOOP;
 IF r->>'state'='AWAITING_HITL' AND r->>'draft_id' IS NOT NULL THEN
  INSERT INTO drafts(id,org_id,agent_slug,inbound_text,draft_content,status,generation_status,director_artifact)
   VALUES((r->>'draft_id')::uuid,o,'vea','Milo recommends approval · automated checks passed',
    (r->'master_result'||jsonb_build_object('director_run_id',rid,'inspection_report',r->'inspection_report'))::text,
    'AWAITING_HITL','completed',r->'master_result'||jsonb_build_object('director_run_id',rid,'inspection',jsonb_build_object('passed',true),
      'inspection_report',r->'inspection_report')) ON CONFLICT(id) DO NOTHING;
  UPDATE agent_runs SET status='awaiting_hitl' WHERE id=rid;
  UPDATE milo_campaigns SET build_status='completed',result=coalesce(result,'{}')||jsonb_build_object('draft_id',r->>'draft_id','director_run_id',rid),
    updated_at=clock_timestamp() WHERE id=(r->>'campaign_id')::uuid AND org_id=o;
 ELSIF r->>'state'='BLOCKED' THEN
  UPDATE agent_runs SET status='failed',completed_at=clock_timestamp() WHERE id=rid;
  UPDATE milo_campaigns SET build_status='failed',updated_at=clock_timestamp()
   WHERE id=(r->>'campaign_id')::uuid AND org_id=o;
 END IF;
 RETURN r;
END $$;

ALTER TABLE milo_director_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE milo_director_run_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE milo_director_scene_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE milo_director_master_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE milo_director_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE milo_director_verified_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE milo_director_queue_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE milo_director_recovery_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON FUNCTION milo_director_store(text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION milo_director_store(text,jsonb) TO service_role;
GRANT ALL ON milo_director_runs,milo_director_run_revisions,milo_director_scene_attempts,
 milo_director_master_attempts,milo_director_verifications,milo_director_verified_tokens,milo_director_queue_intents,milo_director_recovery_receipts TO service_role;
