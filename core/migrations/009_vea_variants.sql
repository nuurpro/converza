-- Independent deterministic VEA variants. Apply after 008; service role only.
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS vea_artifact jsonb;
CREATE TABLE IF NOT EXISTS vea_variants (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 campaign_id uuid NOT NULL REFERENCES milo_campaigns(id) ON DELETE CASCADE,
 product_id text,language text NOT NULL DEFAULT 'en' CHECK(language IN ('en','ru','uz')),
 approved_script_revision bigint NOT NULL CHECK(approved_script_revision>0),revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
 preset_id text NOT NULL CHECK(preset_id IN ('high_velocity_d2c','editorial_showcase')),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','rendering','completed','failed')),
 job_id uuid UNIQUE REFERENCES milo_jobs(id) ON DELETE SET NULL,draft_id uuid REFERENCES drafts(id) ON DELETE SET NULL,
 artifact jsonb,error text,is_default boolean NOT NULL DEFAULT false,
 composition_manifest jsonb,brand_snapshot jsonb NOT NULL DEFAULT '{}',clip_overrides jsonb NOT NULL DEFAULT '{}',
 created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS vea_default_variant ON vea_variants(org_id,campaign_id,approved_script_revision) WHERE is_default;
CREATE INDEX IF NOT EXISTS vea_variants_recent ON vea_variants(org_id,created_at DESC);
CREATE TABLE IF NOT EXISTS vea_variant_revisions (
 variant_id uuid NOT NULL REFERENCES vea_variants(id) ON DELETE CASCADE,revision bigint NOT NULL,snapshot jsonb NOT NULL,
 PRIMARY KEY(variant_id,revision)
);
CREATE TABLE IF NOT EXISTS vea_decisions (
 org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,key text NOT NULL,request jsonb NOT NULL,response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(org_id,key)
);

CREATE OR REPLACE FUNCTION vea_composition_config(v vea_variants,c milo_campaigns,p_reuse jsonb DEFAULT NULL) RETURNS jsonb
 LANGUAGE sql STABLE SET search_path=public AS $$
 SELECT jsonb_build_object('schema_version',1,'variant_id',v.id,'variant_revision',v.revision,'preset_id',v.preset_id,
  'preset_version',p_reuse->'preset'->'version','preset_sha256',p_reuse->'preset_sha256',
  'brand_snapshot',jsonb_build_object('revision',(c.artifact->>'brand_revision')::bigint,'hex_colors',coalesce((
    SELECT jsonb_agg(color ORDER BY n) FROM (
     SELECT value AS color,n FROM jsonb_array_elements_text(CASE WHEN jsonb_typeof(v.brand_snapshot->'hex_colors')='array' THEN v.brand_snapshot->'hex_colors' ELSE '[]'::jsonb END)
      WITH ORDINALITY p(value,n) WHERE value ~ '^#[a-fA-F0-9]{6}$' ORDER BY n LIMIT 12) colors),'[]')),
  'product_id',c.product_id,'clip_overrides',coalesce((SELECT jsonb_agg(jsonb_build_object('segment_id',key,'asset_id',value) ORDER BY key) FROM jsonb_each_text(v.clip_overrides)),'[]'),
  'reuse_manifest',p_reuse);
$$;

CREATE OR REPLACE FUNCTION vea_enqueue(p_id uuid,p_reuse jsonb DEFAULT NULL) RETURNS uuid
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE v vea_variants;c milo_campaigns;j uuid;
BEGIN
 SELECT * INTO v FROM vea_variants WHERE id=p_id FOR UPDATE;
 SELECT * INTO c FROM milo_campaigns WHERE id=v.campaign_id AND org_id=v.org_id FOR SHARE;
 INSERT INTO milo_jobs(org_id,kind,campaign_id,dedup_key,payload) VALUES(v.org_id,'build',c.id,'vea:'||v.id::text||':'||v.revision::text,
  jsonb_build_object('campaign_id',c.id,'script_revision',v.approved_script_revision,'video_script',c.artifact->'video_script',
   'language',coalesce(c.artifact->>'language',c.language,'en'),'submission_state','not_submitted','provider_attempt',1,
   'variant_id',v.id,'variant_revision',v.revision,'vea_config',vea_composition_config(v,c,p_reuse))) RETURNING id INTO j;
 UPDATE vea_variants SET job_id=j,status='queued',error=NULL,updated_at=clock_timestamp() WHERE id=v.id;
 IF v.is_default THEN UPDATE milo_campaigns SET build_status='queued',result=NULL,updated_at=clock_timestamp() WHERE id=c.id; END IF;
 RETURN j;
END $$;

-- Job lifecycle remains owned by Milo, including unknown submission fences.
CREATE OR REPLACE FUNCTION vea_sync_job() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE v vea_variants;
BEGIN
 IF NEW.payload->>'variant_id' IS NULL THEN RETURN NEW; END IF;
 UPDATE vea_variants SET status=CASE NEW.status WHEN 'leased' THEN 'rendering' WHEN 'pending' THEN 'queued' WHEN 'failed' THEN 'failed' ELSE status END,
  error=CASE WHEN NEW.status='failed' THEN coalesce(NEW.payload->>'render_error',NEW.last_error) ELSE NULL END,updated_at=clock_timestamp()
  WHERE id=(NEW.payload->>'variant_id')::uuid AND org_id=NEW.org_id AND job_id=NEW.id AND revision=(NEW.payload->>'variant_revision')::bigint RETURNING * INTO v;
 IF FOUND AND v.is_default THEN
  UPDATE milo_campaigns SET build_status=CASE v.status WHEN 'rendering' THEN 'running' ELSE v.status END,updated_at=clock_timestamp() WHERE id=v.campaign_id;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS vea_sync_job ON milo_jobs;
CREATE TRIGGER vea_sync_job AFTER UPDATE ON milo_jobs FOR EACH ROW EXECUTE FUNCTION vea_sync_job();

-- A manual variant must not overwrite compatibility fields for the default.
CREATE OR REPLACE FUNCTION vea_default_compatibility() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE v vea_variants;legacy milo_jobs;
BEGIN
 SELECT * INTO v FROM vea_variants WHERE campaign_id=NEW.id AND is_default AND approved_script_revision=NEW.revision-1 ORDER BY created_at DESC LIMIT 1;
 IF FOUND THEN
  NEW.build_status:=CASE v.status WHEN 'rendering' THEN 'running' ELSE v.status END;
  NEW.result:=CASE WHEN v.artifact IS NOT NULL THEN v.artifact||jsonb_build_object('draft_id',v.draft_id) ELSE NULL END;
 ELSIF EXISTS(SELECT 1 FROM vea_variants WHERE campaign_id=NEW.id AND NOT is_default) THEN
  -- Campaigns rendered before the feature have an unbound Milo default job.
  -- Derive its lifecycle instead of accepting a manual variant's claim/failure.
  SELECT * INTO legacy FROM milo_jobs WHERE campaign_id=NEW.id AND kind='build' AND payload->>'variant_id' IS NULL
   AND (payload->>'script_revision')::bigint=NEW.revision-1 ORDER BY created_at DESC LIMIT 1;
  IF FOUND THEN
   IF NOT (NEW.build_status='completed' AND NEW.result IS NOT NULL AND NEW.result IS DISTINCT FROM OLD.result) THEN
    NEW.build_status:=CASE legacy.status WHEN 'pending' THEN 'queued' WHEN 'leased' THEN 'running' ELSE legacy.status END;
    NEW.result:=OLD.result;
   END IF;
  ELSE
   NEW.build_status:=OLD.build_status;
   NEW.result:=OLD.result;
  END IF;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS vea_default_compatibility ON milo_campaigns;
CREATE TRIGGER vea_default_compatibility BEFORE UPDATE ON milo_campaigns FOR EACH ROW EXECUTE FUNCTION vea_default_compatibility();

CREATE OR REPLACE FUNCTION vea_store(p_action text,p_args jsonb DEFAULT '{}') RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE o uuid:=(p_args->>'org')::uuid;v vea_variants;c milo_campaigns;j milo_jobs;request jsonb;prior vea_decisions;
 result jsonb;manifest jsonb;d uuid;d_revision bigint;passport jsonb;cfg jsonb;
BEGIN
 IF p_action='list' THEN RETURN coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY created_at DESC) FROM vea_variants t WHERE org_id=o),'[]'); END IF;
 IF p_action='get' THEN RETURN (SELECT to_jsonb(t) FROM vea_variants t WHERE org_id=o AND id=(p_args->>'id')::uuid); END IF;
 IF p_action IN ('prepare','complete') THEN
  SELECT org_id INTO o FROM milo_jobs WHERE id=(p_args->>'job')::uuid;
 END IF;
 IF o IS NULL OR NOT EXISTS(SELECT 1 FROM orgs WHERE id=o) THEN RAISE EXCEPTION 'workflow_conflict: organization required'; END IF;
 PERFORM workflow_lock(o);
 IF p_action IN ('create','swap','retry','replay') THEN
  IF coalesce(trim(p_args->>'key'),'')='' OR length(p_args->>'key')>200 THEN RAISE EXCEPTION 'workflow_conflict: idempotency required'; END IF;
  request:=CASE p_action
   WHEN 'create' THEN jsonb_build_array('create',p_args->>'campaign_id',(p_args->>'revision')::bigint,p_args->>'preset_id')
   WHEN 'retry' THEN jsonb_build_array('retry',p_args->>'id',(p_args->>'revision')::bigint)
   ELSE p_args->'request' END;
  SELECT * INTO prior FROM vea_decisions WHERE org_id=o AND key=p_args->>'key';
  IF FOUND THEN
   IF prior.request<>request THEN RAISE EXCEPTION 'workflow_conflict: idempotency reused'; END IF;
   RETURN prior.response;
  END IF;
  IF p_action='replay' THEN RETURN NULL; END IF;
 END IF;
 IF p_action='create' THEN
  SELECT * INTO c FROM milo_campaigns WHERE org_id=o AND id=(p_args->>'campaign_id')::uuid FOR SHARE;
  IF NOT FOUND OR c.script_status<>'approved' OR c.revision<>(p_args->>'revision')::bigint THEN RAISE EXCEPTION 'workflow_conflict: approved revision required'; END IF;
  IF p_args->>'preset_id' NOT IN ('high_velocity_d2c','editorial_showcase') THEN RAISE EXCEPTION 'workflow_conflict: invalid preset'; END IF;
  PERFORM milo_assert_evidence(o,c.artifact);
  SELECT to_jsonb(b) INTO passport FROM brand_passports b WHERE org_id=o ORDER BY updated_at DESC LIMIT 1;
  INSERT INTO vea_variants(org_id,campaign_id,approved_script_revision,preset_id,brand_snapshot,product_id,language)
   VALUES(o,c.id,c.revision-1,p_args->>'preset_id',coalesce(passport,'{}'),c.product_id,coalesce(c.artifact->>'language',c.language,'en')) RETURNING * INTO v;
  PERFORM vea_enqueue(v.id);
 ELSIF p_action IN ('prepare','complete') THEN
  SELECT * INTO j FROM milo_jobs WHERE org_id=o AND id=(p_args->>'job')::uuid FOR UPDATE;
  IF NOT FOUND OR j.kind<>'build' OR j.status<>'leased' OR j.lease_token IS DISTINCT FROM (p_args->>'token')::uuid OR j.lease_until<=clock_timestamp()
   THEN RAISE EXCEPTION 'workflow_conflict: build lease expired'; END IF;
  SELECT * INTO c FROM milo_campaigns WHERE org_id=o AND id=j.campaign_id FOR SHARE;
  IF p_action='prepare' THEN
   IF j.payload->>'variant_id' IS NULL THEN
    IF c.script_status<>'approved' OR c.revision-1<>(j.payload->>'script_revision')::bigint THEN RAISE EXCEPTION 'workflow_conflict: approved revision changed'; END IF;
    PERFORM milo_assert_evidence(o,c.artifact);
    SELECT to_jsonb(b) INTO passport FROM brand_passports b WHERE org_id=o ORDER BY updated_at DESC LIMIT 1;
    INSERT INTO vea_variants(org_id,campaign_id,approved_script_revision,preset_id,status,job_id,is_default,brand_snapshot,product_id,language)
     VALUES(o,c.id,c.revision-1,'high_velocity_d2c','rendering',j.id,true,coalesce(passport,'{}'),c.product_id,coalesce(c.artifact->>'language',c.language,'en')) RETURNING * INTO v;
    cfg:=vea_composition_config(v,c);
    UPDATE milo_jobs SET payload=payload||jsonb_build_object('variant_id',v.id,'variant_revision',v.revision,'vea_config',cfg) WHERE id=j.id RETURNING * INTO j;
   ELSE
    SELECT * INTO v FROM vea_variants WHERE org_id=o AND id=(j.payload->>'variant_id')::uuid AND revision=(j.payload->>'variant_revision')::bigint AND job_id=j.id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'workflow_conflict: superseded build'; END IF;
    IF coalesce(j.payload->>'submission_state','not_submitted')='not_submitted' THEN
     IF c.script_status<>'approved' OR c.revision<>v.approved_script_revision+1 THEN RAISE EXCEPTION 'workflow_conflict: approved revision changed'; END IF;
     PERFORM milo_assert_evidence(o,c.artifact);
    END IF;
    UPDATE vea_variants SET status='rendering',updated_at=clock_timestamp() WHERE id=v.id;
   END IF;
   RETURN to_jsonb(j);
  END IF;
  SELECT * INTO v FROM vea_variants WHERE org_id=o AND id=(j.payload->>'variant_id')::uuid AND revision=(j.payload->>'variant_revision')::bigint AND job_id=j.id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'workflow_conflict: superseded build'; END IF;
  result:=p_args->'artifact';manifest:=p_args->'composition_manifest';
  IF result->>'id'<>v.id::text OR (result->>'variant_revision')::bigint<>v.revision OR result->>'source_milo_script_id'<>c.id::text
   OR (result->>'approved_script_revision')::bigint<>v.approved_script_revision OR result->>'preset_used'<>v.preset_id
   OR jsonb_typeof(manifest->'segments') IS DISTINCT FROM 'array' OR jsonb_array_length(manifest->'segments')=0
   THEN RAISE EXCEPTION 'workflow_conflict: artifact binding'; END IF;
  INSERT INTO drafts(org_id,agent_slug,inbound_text,draft_content,vea_artifact) VALUES(o,'vea','Milo approved video variant',result::text,result) RETURNING id,revision INTO d,d_revision;
  PERFORM workflow_transition(o,d,'ready',d_revision,'vea-built:'||j.id::text,result::text);
  UPDATE vea_variants SET status='completed',artifact=result,composition_manifest=manifest,draft_id=d,error=NULL,updated_at=clock_timestamp() WHERE id=v.id;
  IF v.is_default THEN UPDATE milo_campaigns SET build_status='completed',result=(p_args->'artifact')||jsonb_build_object('draft_id',d),updated_at=clock_timestamp() WHERE id=c.id; END IF;
  UPDATE milo_jobs SET status='completed',lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=j.id;
  RETURN (SELECT to_jsonb(t) FROM milo_campaigns t WHERE id=c.id);
 ELSIF p_action IN ('swap','retry','validate_review') THEN
  SELECT * INTO v FROM vea_variants WHERE org_id=o AND id=(p_args->>'id')::uuid AND revision=(p_args->>'revision')::bigint FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'workflow_conflict: variant revision'; END IF;
  SELECT * INTO c FROM milo_campaigns WHERE org_id=o AND id=v.campaign_id FOR SHARE;
  IF c.script_status<>'approved' OR c.revision<>v.approved_script_revision+1 THEN RAISE EXCEPTION 'workflow_conflict: approved revision'; END IF;
  PERFORM milo_assert_evidence(o,c.artifact);
  IF p_action='validate_review' THEN
   IF v.status<>'completed' OR v.draft_id IS DISTINCT FROM (p_args->>'draft_id')::uuid THEN RAISE EXCEPTION 'workflow_conflict: superseded draft'; END IF;
   RETURN jsonb_build_object('campaign',to_jsonb(c),'composition_manifest',v.composition_manifest);
  ELSIF p_action='swap' THEN
   IF v.status<>'completed' OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(v.composition_manifest->'segments') s WHERE s->>'segment_id'=p_args->>'segment_id')
    THEN RAISE EXCEPTION 'workflow_conflict: completed segment required'; END IF;
   INSERT INTO vea_variant_revisions(variant_id,revision,snapshot) VALUES(v.id,v.revision,to_jsonb(v));
   manifest:=v.composition_manifest;
   -- Retain historical media but invalidate any pending approval and mark all
   -- previous decisions stale before queuing the new immutable revision.
   UPDATE drafts SET status='REJECTED',final_content=NULL,decided_at=clock_timestamp(),
    vea_artifact=vea_artifact||'{"superseded":true}',revision=revision+1,updated_at=clock_timestamp() WHERE id=v.draft_id AND org_id=o;
   UPDATE vea_variants SET revision=revision+1,artifact=NULL,draft_id=NULL,
    clip_overrides=clip_overrides||jsonb_build_object(p_args->>'segment_id',p_args->>'asset_id') WHERE id=v.id;
   PERFORM vea_enqueue(v.id,manifest);
  ELSE
   IF v.status<>'failed' THEN RAISE EXCEPTION 'workflow_conflict: failed variant required'; END IF;
   -- Existing Milo RPC owns definitive failure retry vs uncertain receipt recovery.
   PERFORM milo_store('retry',jsonb_build_object('org',o,'id',v.job_id,'key','vea:'||(p_args->>'key')));
  END IF;
 ELSE RAISE EXCEPTION 'workflow_conflict: unknown VEA operation'; END IF;
 SELECT * INTO v FROM vea_variants WHERE id=v.id;
 result:=to_jsonb(v);
 INSERT INTO vea_decisions(org_id,key,request,response) VALUES(o,p_args->>'key',request,result);
 RETURN result;
END $$;

-- SQL callers receive the same structured-artifact safety rules as Python.
CREATE OR REPLACE FUNCTION vea_guard_draft() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE v vea_variants;c milo_campaigns;
BEGIN
 IF OLD.vea_artifact IS NULL THEN RETURN NEW; END IF;
 IF NEW.status='EDITED' OR NEW.status='PUBLISHED' OR (NEW.delivery_status='sending' AND OLD.delivery_status IS DISTINCT FROM NEW.delivery_status)
  OR NEW.draft_content IS DISTINCT FROM OLD.draft_content OR NEW.delivery_claimed_at IS DISTINCT FROM OLD.delivery_claimed_at
  THEN RAISE EXCEPTION 'workflow_conflict: video supports approval and export only'; END IF;
 IF NEW.status='APPROVED' AND OLD.status IS DISTINCT FROM NEW.status THEN
  SELECT * INTO v FROM vea_variants WHERE org_id=OLD.org_id AND id=(OLD.vea_artifact->>'id')::uuid FOR SHARE;
  IF NOT FOUND OR v.draft_id<>OLD.id OR v.revision<>(OLD.vea_artifact->>'variant_revision')::bigint OR v.status<>'completed'
   OR coalesce((OLD.vea_artifact->>'superseded')::boolean,false) THEN RAISE EXCEPTION 'workflow_conflict: superseded video'; END IF;
  SELECT * INTO c FROM milo_campaigns WHERE id=v.campaign_id AND org_id=v.org_id FOR SHARE;
  IF c.script_status<>'approved' OR c.revision<>v.approved_script_revision+1 THEN RAISE EXCEPTION 'workflow_conflict: source changed'; END IF;
  PERFORM milo_assert_evidence(v.org_id,c.artifact);
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS vea_guard_draft ON drafts;
CREATE TRIGGER vea_guard_draft BEFORE UPDATE ON drafts FOR EACH ROW EXECUTE FUNCTION vea_guard_draft();

ALTER TABLE vea_variants ENABLE ROW LEVEL SECURITY;
ALTER TABLE vea_variant_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE vea_decisions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON vea_variants,vea_variant_revisions,vea_decisions FROM anon,authenticated;
GRANT ALL ON vea_variants,vea_variant_revisions,vea_decisions TO service_role;
REVOKE ALL ON FUNCTION vea_store(text,jsonb),vea_enqueue(uuid,jsonb),vea_composition_config(vea_variants,milo_campaigns,jsonb),vea_sync_job(),vea_default_compatibility(),vea_guard_draft() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION vea_store(text,jsonb) TO service_role;
