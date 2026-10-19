-- Durable inbound sales processing. Apply after 006; all worker RPCs are service-only.
ALTER TABLE brand_products ADD COLUMN IF NOT EXISTS sku text,
 ADD COLUMN IF NOT EXISTS stock_count integer CHECK(stock_count>=0),
 ADD COLUMN IF NOT EXISTS checkout_url_template text CHECK(checkout_url_template IS NULL OR checkout_url_template ~ '^https://[^/[:space:]]+');
UPDATE brand_products p SET sku=trim(p.metadata->>'sku')
 WHERE p.sku IS NULL AND nullif(trim(p.metadata->>'sku'),'') IS NOT NULL AND p.deleted_at IS NULL
 AND NOT EXISTS(SELECT 1 FROM brand_products x WHERE x.org_id=p.org_id AND x.id<>p.id AND x.deleted_at IS NULL
   AND (trim(x.metadata->>'sku')=trim(p.metadata->>'sku') OR x.sku=trim(p.metadata->>'sku')));
CREATE UNIQUE INDEX IF NOT EXISTS brand_products_active_sku ON brand_products(org_id,sku) WHERE deleted_at IS NULL AND sku IS NOT NULL;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS platform text, ADD COLUMN IF NOT EXISTS external_id text,
 ADD COLUMN IF NOT EXISTS customer_handle text, ADD COLUMN IF NOT EXISTS metadata jsonb NOT NULL DEFAULT '{}',
 ADD COLUMN IF NOT EXISTS tg_chat_id bigint, ADD COLUMN IF NOT EXISTS business_connection_id text;
CREATE UNIQUE INDEX IF NOT EXISTS prospects_platform_identity ON prospects(org_id,platform,external_id)
 WHERE platform IS NOT NULL AND external_id IS NOT NULL;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS sleyz_artifact jsonb,
 ADD COLUMN IF NOT EXISTS simulated boolean NOT NULL DEFAULT false,
 ADD COLUMN IF NOT EXISTS platform text CHECK(platform IN ('telegram','instagram')),
 ADD COLUMN IF NOT EXISTS inbound_id uuid,
 ADD COLUMN IF NOT EXISTS superseded_by uuid REFERENCES drafts(id),
 ADD COLUMN IF NOT EXISTS learning_status text CHECK(learning_status IN ('pending','running','completed','failed','skipped')),
 ADD COLUMN IF NOT EXISTS learning_error text;
ALTER TABLE memory_sources DROP CONSTRAINT IF EXISTS memory_sources_kind_check;
ALTER TABLE memory_sources ADD CONSTRAINT memory_sources_kind_check CHECK(kind IN ('passport','product','faq','manual','objection','correction'));

CREATE TABLE IF NOT EXISTS sleyz_inbound (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 platform text NOT NULL CHECK(platform IN ('telegram','instagram')), connection_id text NOT NULL,
 external_message_id text NOT NULL, prospect_id uuid NOT NULL REFERENCES prospects(id) ON DELETE CASCADE,
 draft_id uuid NOT NULL UNIQUE REFERENCES drafts(id) ON DELETE CASCADE, envelope jsonb NOT NULL,
 received_at timestamptz NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','leased','completed','failed')),
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, lease_token uuid, last_error text, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(org_id,platform,connection_id,external_message_id)
);
ALTER TABLE drafts ADD CONSTRAINT drafts_sleyz_inbound_fkey FOREIGN KEY(inbound_id) REFERENCES sleyz_inbound(id) DEFERRABLE INITIALLY DEFERRED;
CREATE TABLE IF NOT EXISTS sleyz_learning_jobs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 draft_id uuid NOT NULL REFERENCES drafts(id) ON DELETE CASCADE, approved_revision bigint NOT NULL,
 original_content text NOT NULL, final_content text NOT NULL, approved_at timestamptz NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','leased','completed','failed')),
 attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz, lease_token uuid, last_error text, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(draft_id,approved_revision)
);
CREATE TABLE IF NOT EXISTS objection_telemetry (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 inbound_id uuid NOT NULL REFERENCES sleyz_inbound(id) ON DELETE CASCADE,
 prospect_id uuid NOT NULL REFERENCES prospects(id) ON DELETE CASCADE, draft_id uuid NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
 objection_type text NOT NULL, buyer_text text NOT NULL, span_start integer NOT NULL CHECK(span_start>=0),
 span_end integer NOT NULL CHECK(span_end>=span_start), created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(inbound_id,objection_type,span_start,span_end)
);
CREATE INDEX IF NOT EXISTS sleyz_inbound_claim ON sleyz_inbound(available_at,created_at) WHERE status IN ('pending','leased');
CREATE INDEX IF NOT EXISTS sleyz_inbound_history ON sleyz_inbound(org_id,prospect_id,received_at DESC);
CREATE INDEX IF NOT EXISTS sleyz_learning_claim ON sleyz_learning_jobs(available_at,created_at) WHERE status IN ('pending','leased');

CREATE OR REPLACE FUNCTION sleyz_draft_guard() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
 IF TG_OP='UPDATE' AND (NEW.simulated OR NEW.superseded_by IS NOT NULL) AND
  ((NEW.delivery_status IN ('sending','delivered') AND NEW.delivery_status IS DISTINCT FROM OLD.delivery_status)
   OR NEW.delivered_at IS DISTINCT FROM OLD.delivered_at OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at) THEN
  RAISE EXCEPTION 'workflow_conflict: simulated or superseded delivery forbidden';
 END IF;
 IF TG_OP='UPDATE' AND NEW.agent_slug='sleyz' AND NEW.status='EDITED' AND OLD.status='AWAITING_HITL'
  AND NOT NEW.simulated AND NEW.sleyz_artifact IS NOT NULL AND NEW.final_content IS DISTINCT FROM NEW.draft_content THEN
  INSERT INTO sleyz_learning_jobs(org_id,draft_id,approved_revision,original_content,final_content,approved_at)
   VALUES(NEW.org_id,NEW.id,NEW.revision,NEW.draft_content,NEW.final_content,NEW.decided_at) ON CONFLICT DO NOTHING;
  NEW.learning_status:='pending'; NEW.learning_error:=NULL;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER zz_sleyz_draft_guard BEFORE UPDATE ON drafts FOR EACH ROW EXECUTE FUNCTION sleyz_draft_guard();

CREATE OR REPLACE FUNCTION sleyz_accept_inbound(p_envelope jsonb) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE o uuid:=(p_envelope->>'org_id')::uuid; i sleyz_inbound; p uuid; d uuid; iid uuid:=gen_random_uuid(); ext text; sim boolean:=coalesce((p_envelope->>'simulated')::boolean,false);
BEGIN
 IF coalesce(p_envelope->>'platform','') NOT IN ('telegram','instagram') OR coalesce(length(trim(p_envelope->>'text')),0)=0 OR length(p_envelope->>'text')>16000
  OR coalesce(p_envelope->>'connection_id','')='' OR coalesce(p_envelope->>'external_message_id','')='' OR coalesce(p_envelope->>'customer_id','')='' THEN
  RAISE EXCEPTION 'workflow_conflict: invalid inbound envelope'; END IF;
 PERFORM workflow_lock(o);
 SELECT * INTO i FROM sleyz_inbound WHERE org_id=o AND platform=p_envelope->>'platform' AND connection_id=p_envelope->>'connection_id' AND external_message_id=p_envelope->>'external_message_id';
 IF FOUND THEN RETURN jsonb_build_object('inbound_id',i.id,'draft_id',i.draft_id,'duplicate',true); END IF;
 ext:=CASE WHEN sim THEN 'simulation:' ELSE '' END||(p_envelope->>'customer_id');
 INSERT INTO prospects(org_id,platform,external_id,customer_handle,metadata,tg_chat_id,business_connection_id)
 VALUES(o,p_envelope->>'platform',ext,coalesce(nullif(p_envelope->>'customer_handle',''),p_envelope->>'customer_id'),
  jsonb_build_object('connection_id',p_envelope->>'connection_id','received_at',p_envelope->>'received_at'),
  CASE WHEN p_envelope->>'platform'='telegram' THEN (p_envelope->>'tg_chat_id')::bigint END,p_envelope->>'business_connection_id')
 ON CONFLICT(org_id,platform,external_id) WHERE platform IS NOT NULL AND external_id IS NOT NULL
 DO UPDATE SET customer_handle=excluded.customer_handle,metadata=excluded.metadata,
 tg_chat_id=coalesce(excluded.tg_chat_id,prospects.tg_chat_id),business_connection_id=excluded.business_connection_id
 RETURNING id INTO p;
 INSERT INTO drafts(org_id,agent_slug,prospect_id,inbound_text,draft_content,status,platform,simulated,inbound_id)
 VALUES(o,'sleyz',p,p_envelope->>'text','','PENDING_DRAFT',p_envelope->>'platform',sim,iid) RETURNING id INTO d;
 INSERT INTO sleyz_inbound(id,org_id,platform,connection_id,external_message_id,prospect_id,draft_id,envelope,received_at)
 VALUES(iid,o,p_envelope->>'platform',p_envelope->>'connection_id',p_envelope->>'external_message_id',p,d,p_envelope,(p_envelope->>'received_at')::timestamptz);
 RETURN jsonb_build_object('inbound_id',iid,'draft_id',d,'duplicate',false);
END $$;

CREATE OR REPLACE FUNCTION sleyz_claim_jobs(p_limit integer DEFAULT 1,p_lease_seconds integer DEFAULT 600) RETURNS SETOF sleyz_inbound LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j sleyz_inbound;
BEGIN
 -- Draft rows share workflow's organization lock. Select candidates without locking jobs first.
 FOR j IN SELECT * FROM sleyz_inbound WHERE status='leased' AND lease_until<=clock_timestamp() AND attempts>=3 LOOP
  PERFORM workflow_lock(j.org_id);
  UPDATE sleyz_inbound SET status='failed',lease_token=NULL,lease_until=NULL,last_error='Worker lease expired after maximum attempts'
   WHERE id=j.id AND status='leased' AND lease_until<=clock_timestamp() AND attempts>=3;
  IF FOUND THEN UPDATE drafts SET generation_status='failed',generation_error='Draft generation exhausted worker retries',revision=revision+1,updated_at=clock_timestamp() WHERE id=j.draft_id; END IF;
 END LOOP;
 FOR j IN SELECT * FROM sleyz_inbound WHERE attempts<3 AND ((status='pending' AND available_at<=clock_timestamp()) OR (status='leased' AND lease_until<=clock_timestamp())) ORDER BY available_at,created_at LIMIT greatest(1,least(p_limit,100)) LOOP
  -- Try the organization lock rather than wait behind another worker; recheck after locking.
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sleyz:'||j.org_id::text,0)) THEN CONTINUE; END IF;
  PERFORM workflow_lock(j.org_id);
  UPDATE sleyz_inbound SET status='leased',attempts=attempts+1,lease_token=gen_random_uuid(),lease_until=clock_timestamp()+make_interval(secs=>greatest(10,least(p_lease_seconds,3600)))
   WHERE id=j.id AND attempts<3 AND ((status='pending' AND available_at<=clock_timestamp()) OR (status='leased' AND lease_until<=clock_timestamp())) RETURNING * INTO j;
  IF FOUND THEN
   UPDATE drafts SET generation_status='running',generation_error=NULL,revision=revision+1,updated_at=clock_timestamp() WHERE id=j.draft_id AND status='PENDING_DRAFT';
   RETURN NEXT j;
  END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION sleyz_ready_job(p_job uuid,p_token uuid,p_artifact jsonb) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j sleyz_inbound; d drafts; result jsonb;
BEGIN
 SELECT * INTO j FROM sleyz_inbound WHERE id=p_job;
 IF NOT FOUND THEN RAISE EXCEPTION 'workflow_not_found'; END IF;
 PERFORM workflow_lock(j.org_id);
 SELECT * INTO j FROM sleyz_inbound WHERE id=p_job FOR UPDATE;
 IF j.status<>'leased' OR j.lease_token IS DISTINCT FROM p_token OR j.lease_until<=clock_timestamp() THEN RAISE EXCEPTION 'workflow_conflict: stale lease'; END IF;
 SELECT * INTO d FROM drafts WHERE id=j.draft_id FOR UPDATE;
 UPDATE drafts SET sleyz_artifact=p_artifact WHERE id=d.id;
 result:=workflow_transition(j.org_id,d.id,'ready',d.revision,'sleyz-ready:'||p_token,p_artifact->>'draft_reply');
 UPDATE sleyz_inbound SET status='completed',lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=p_job;
 INSERT INTO squad_messages(org_id,sender_slug,content,hitl_draft_id) VALUES(j.org_id,'sleyz','Inbound reply ready for review',d.id);
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION sleyz_fail_job(p_job uuid,p_token uuid,p_error text) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j sleyz_inbound;
BEGIN
 SELECT * INTO j FROM sleyz_inbound WHERE id=p_job;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM workflow_lock(j.org_id);
 UPDATE sleyz_inbound SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,
  available_at=clock_timestamp()+make_interval(secs=>5*power(2,attempts)::int),lease_token=NULL,lease_until=NULL,last_error='Draft generation failed; retry available.'
  WHERE id=p_job AND status='leased' AND lease_token=p_token AND lease_until>clock_timestamp() RETURNING * INTO j;
 IF NOT FOUND THEN RETURN false; END IF;
 UPDATE drafts SET generation_status=CASE WHEN j.status='failed' THEN 'failed' ELSE 'pending' END,generation_error='Draft generation failed; retry available.',revision=revision+1,updated_at=clock_timestamp() WHERE id=j.draft_id;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION sleyz_claim_learning(p_limit integer DEFAULT 1,p_lease_seconds integer DEFAULT 600) RETURNS SETOF sleyz_learning_jobs LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j sleyz_learning_jobs;
BEGIN
 FOR j IN SELECT * FROM sleyz_learning_jobs WHERE status='leased' AND lease_until<=clock_timestamp() AND attempts>=3 LOOP
  PERFORM workflow_lock(j.org_id);
  UPDATE sleyz_learning_jobs SET status='failed',lease_token=NULL,lease_until=NULL,last_error='Learning worker exhausted retries' WHERE id=j.id AND status='leased' AND lease_until<=clock_timestamp() AND attempts>=3;
  IF FOUND THEN UPDATE drafts SET learning_status='failed',learning_error='Learning worker exhausted retries',revision=revision+1,updated_at=clock_timestamp() WHERE id=j.draft_id; END IF;
 END LOOP;
 FOR j IN SELECT * FROM sleyz_learning_jobs WHERE attempts<3 AND ((status='pending' AND available_at<=clock_timestamp()) OR (status='leased' AND lease_until<=clock_timestamp())) ORDER BY available_at,created_at LIMIT greatest(1,least(p_limit,100)) LOOP
  IF NOT pg_try_advisory_xact_lock(hashtextextended('sleyz-learning:'||j.org_id::text,0)) THEN CONTINUE; END IF;
  PERFORM workflow_lock(j.org_id);
  UPDATE sleyz_learning_jobs SET status='leased',attempts=attempts+1,lease_token=gen_random_uuid(),lease_until=clock_timestamp()+make_interval(secs=>greatest(10,least(p_lease_seconds,3600)))
   WHERE id=j.id AND attempts<3 AND ((status='pending' AND available_at<=clock_timestamp()) OR (status='leased' AND lease_until<=clock_timestamp())) RETURNING * INTO j;
  IF FOUND THEN UPDATE drafts SET learning_status='running',learning_error=NULL,revision=revision+1,updated_at=clock_timestamp() WHERE id=j.draft_id; RETURN NEXT j; END IF;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION sleyz_complete_learning(p_job uuid,p_token uuid,p_correction jsonb) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j sleyz_learning_jobs; source uuid; meta jsonb; rule text;
BEGIN
 SELECT * INTO j FROM sleyz_learning_jobs WHERE id=p_job;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM workflow_lock(j.org_id);
 SELECT * INTO j FROM sleyz_learning_jobs WHERE id=p_job FOR UPDATE;
 IF j.status<>'leased' OR j.lease_token IS DISTINCT FROM p_token OR j.lease_until<=clock_timestamp() THEN RETURN false; END IF;
 IF p_correction IS NOT NULL AND p_correction<>'null'::jsonb THEN
  rule:=coalesce(p_correction->>'rule',p_correction->>'content');
  IF coalesce(length(trim(rule)),0)=0 THEN RAISE EXCEPTION 'workflow_conflict: correction rule required'; END IF;
  meta:=jsonb_build_object('draft_id',j.draft_id,'approved_revision',j.approved_revision,'approved_at',j.approved_at,
   'original_content',j.original_content,'final_content',j.final_content,'priority',2,'rule_type',p_correction->>'rule_type','supporting_spans',coalesce(p_correction->'supporting_spans','[]'));
  source:=memory_capture(j.org_id,'correction',j.draft_id::text||':'||j.approved_revision,'Approved reply correction',rule,meta,false,j.approved_at);
  UPDATE memory_sources SET summary=rule,atoms=jsonb_build_array(meta||jsonb_build_object('kind','correction','text',rule,'source_id',source,'source_revision',revision,'span',jsonb_build_array(0,length(rule)))),indexed_revision=revision,indexing_status='ready' WHERE id=source AND forgotten_at IS NULL AND deleted_at IS NULL;
  UPDATE memory_index_jobs SET status='completed',lease_token=NULL,lease_until=NULL,completed_at=clock_timestamp() WHERE source_id=source AND status IN ('pending','leased');
 END IF;
 UPDATE sleyz_learning_jobs SET status='completed',lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=p_job;
 UPDATE drafts SET learning_status=CASE WHEN p_correction IS NULL OR p_correction='null'::jsonb THEN 'skipped' ELSE 'completed' END,learning_error=NULL,revision=revision+1,updated_at=clock_timestamp() WHERE id=j.draft_id;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION sleyz_fail_learning(p_job uuid,p_token uuid,p_error text) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j sleyz_learning_jobs;
BEGIN
 SELECT * INTO j FROM sleyz_learning_jobs WHERE id=p_job;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM workflow_lock(j.org_id);
 UPDATE sleyz_learning_jobs SET status=CASE WHEN attempts>=3 THEN 'failed' ELSE 'pending' END,
  available_at=clock_timestamp()+make_interval(secs=>5*power(2,attempts)::int),lease_token=NULL,lease_until=NULL,last_error='Learning analysis failed; retry available.'
  WHERE id=p_job AND status='leased' AND lease_token=p_token AND lease_until>clock_timestamp() RETURNING * INTO j;
 IF NOT FOUND THEN RETURN false; END IF;
 UPDATE drafts SET learning_status=CASE WHEN j.status='failed' THEN 'failed' ELSE 'pending' END,learning_error='Learning analysis failed; retry available.',revision=revision+1,updated_at=clock_timestamp() WHERE id=j.draft_id;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION sleyz_retry_learning(p_org uuid,p_draft uuid) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j sleyz_learning_jobs;
BEGIN
 PERFORM workflow_lock(p_org);
 UPDATE sleyz_learning_jobs SET status='pending',attempts=0,available_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,last_error=NULL
  WHERE org_id=p_org AND draft_id=p_draft AND status='failed' RETURNING * INTO j;
 IF NOT FOUND THEN RAISE EXCEPTION 'workflow_conflict: no failed learning job'; END IF;
 UPDATE drafts SET learning_status='pending',learning_error=NULL,revision=revision+1,updated_at=clock_timestamp() WHERE org_id=p_org AND id=p_draft;
 RETURN to_jsonb(j);
END $$;

CREATE OR REPLACE FUNCTION sleyz_retry_generation(p_org uuid,p_draft uuid,p_revision bigint,p_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE d drafts; j sleyz_inbound; result jsonb; prior workflow_idempotency; request jsonb:=jsonb_build_array(p_draft,p_revision,'sleyz-retry-generation');
BEGIN
 IF coalesce(length(trim(p_key)),0)=0 THEN RAISE EXCEPTION 'workflow_conflict: idempotency key required'; END IF;
 PERFORM workflow_lock(p_org);
 SELECT * INTO prior FROM workflow_idempotency WHERE org_id=p_org AND key=p_key;
 IF FOUND THEN IF prior.request<>request THEN RAISE EXCEPTION 'workflow_conflict: idempotency key reused'; END IF; RETURN prior.response; END IF;
 SELECT * INTO d FROM drafts WHERE org_id=p_org AND id=p_draft FOR UPDATE;
 IF NOT FOUND OR d.revision<>p_revision OR d.status<>'PENDING_DRAFT' OR d.generation_status<>'failed' THEN RAISE EXCEPTION 'workflow_conflict: no failed inbound generation at this revision'; END IF;
 SELECT * INTO j FROM sleyz_inbound WHERE org_id=p_org AND id=d.inbound_id FOR UPDATE;
 IF NOT FOUND OR j.status<>'failed' THEN RAISE EXCEPTION 'workflow_conflict: inbox is not failed'; END IF;
 UPDATE sleyz_inbound SET status='pending',attempts=0,available_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=j.id;
 UPDATE drafts SET generation_status='pending',generation_error=NULL,revision=revision+1,updated_at=clock_timestamp() WHERE id=p_draft RETURNING to_jsonb(drafts.*) INTO result;
 INSERT INTO workflow_idempotency(org_id,key,request,response) VALUES(p_org,p_key,request,result);
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION sleyz_telemetry(p_job uuid,p_objections jsonb) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j sleyz_inbound; objection jsonb; start_pos integer; end_pos integer;
BEGIN
 SELECT * INTO j FROM sleyz_inbound WHERE id=p_job;
 IF NOT FOUND THEN RAISE EXCEPTION 'workflow_not_found'; END IF;
 FOR objection IN SELECT * FROM jsonb_array_elements(p_objections) LOOP
  start_pos:=(objection->'span'->>0)::integer; end_pos:=(objection->'span'->>1)::integer;
  IF start_pos<0 OR end_pos<start_pos OR substring(j.envelope->>'text' FROM start_pos+1 FOR end_pos-start_pos) IS DISTINCT FROM objection->>'text' THEN RAISE EXCEPTION 'workflow_conflict: invalid objection span'; END IF;
  INSERT INTO objection_telemetry(org_id,inbound_id,prospect_id,draft_id,objection_type,buyer_text,span_start,span_end)
  VALUES(j.org_id,j.id,j.prospect_id,j.draft_id,objection->>'type',objection->>'text',start_pos,end_pos) ON CONFLICT DO NOTHING;
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION sleyz_refresh(p_org uuid,p_draft uuid,p_revision bigint,p_key text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE d drafts; env jsonb; result jsonb; prior workflow_idempotency; request jsonb:=jsonb_build_array(p_draft,p_revision,'sleyz-refresh');
BEGIN
 IF coalesce(length(trim(p_key)),0)=0 THEN RAISE EXCEPTION 'workflow_conflict: idempotency key required'; END IF;
 PERFORM workflow_lock(p_org);
 SELECT * INTO prior FROM workflow_idempotency WHERE org_id=p_org AND key=p_key;
 IF FOUND THEN IF prior.request<>request THEN RAISE EXCEPTION 'workflow_conflict: idempotency key reused'; END IF; RETURN prior.response; END IF;
 SELECT * INTO d FROM drafts WHERE org_id=p_org AND id=p_draft FOR UPDATE;
 IF NOT FOUND OR d.revision<>p_revision OR d.superseded_by IS NOT NULL OR d.status NOT IN ('AWAITING_HITL','APPROVED','EDITED') OR d.delivery_status IN ('sending','ambiguous','delivered') THEN RAISE EXCEPTION 'workflow_conflict: draft cannot be refreshed'; END IF;
 SELECT envelope INTO env FROM sleyz_inbound WHERE org_id=p_org AND id=d.inbound_id;
 IF env IS NULL THEN RAISE EXCEPTION 'workflow_conflict: inbound unavailable'; END IF;
 env:=jsonb_set(env,'{external_message_id}',to_jsonb((env->>'external_message_id')||':refresh:'||p_key));
 result:=sleyz_accept_inbound(env);
 UPDATE drafts SET superseded_by=(result->>'draft_id')::uuid,revision=revision+1,updated_at=clock_timestamp() WHERE id=p_draft;
 INSERT INTO workflow_idempotency(org_id,key,request,response) VALUES(p_org,p_key,request,result);
 RETURN result;
END $$;

ALTER TABLE sleyz_inbound ENABLE ROW LEVEL SECURITY;
ALTER TABLE sleyz_learning_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE objection_telemetry ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sleyz_inbound,sleyz_learning_jobs,objection_telemetry FROM PUBLIC,anon,authenticated;
GRANT ALL ON sleyz_inbound,sleyz_learning_jobs,objection_telemetry TO service_role;
CREATE POLICY sleyz_inbound_service ON sleyz_inbound FOR ALL TO service_role USING(true) WITH CHECK(true);
CREATE POLICY sleyz_learning_service ON sleyz_learning_jobs FOR ALL TO service_role USING(true) WITH CHECK(true);
CREATE POLICY sleyz_telemetry_service ON objection_telemetry FOR ALL TO service_role USING(true) WITH CHECK(true);
REVOKE ALL ON FUNCTION sleyz_draft_guard(),sleyz_accept_inbound(jsonb),sleyz_claim_jobs(integer,integer),sleyz_ready_job(uuid,uuid,jsonb),sleyz_fail_job(uuid,uuid,text),
 sleyz_claim_learning(integer,integer),sleyz_complete_learning(uuid,uuid,jsonb),sleyz_fail_learning(uuid,uuid,text),sleyz_retry_learning(uuid,uuid),sleyz_retry_generation(uuid,uuid,bigint,text),sleyz_telemetry(uuid,jsonb),sleyz_refresh(uuid,uuid,bigint,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION sleyz_accept_inbound(jsonb),sleyz_claim_jobs(integer,integer),sleyz_ready_job(uuid,uuid,jsonb),sleyz_fail_job(uuid,uuid,text),
 sleyz_claim_learning(integer,integer),sleyz_complete_learning(uuid,uuid,jsonb),sleyz_fail_learning(uuid,uuid,text),sleyz_retry_learning(uuid,uuid),sleyz_retry_generation(uuid,uuid,bigint,text),sleyz_telemetry(uuid,jsonb),sleyz_refresh(uuid,uuid,bigint,text) TO service_role;
