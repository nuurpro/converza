-- Additive upgrade after 010 (011/012 are independent onboarding/feed changes).
-- Catalog validation, request-scope idempotency and approved build scope are atomic.
-- Retain the full service-only RPC so prior migrations remain immutable.
CREATE OR REPLACE FUNCTION milo_assert_product(p_org uuid,p_product text) RETURNS void
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
 IF p_product IS NULL THEN RETURN; END IF;
 IF p_product='' OR p_product<>btrim(p_product) THEN
  RAISE EXCEPTION 'workflow_conflict: invalid selected product';
 END IF;
 -- FOR SHARE fences a concurrent soft-delete/update through transaction commit.
 PERFORM 1 FROM brand_products WHERE org_id=p_org AND id::text=p_product AND deleted_at IS NULL FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'workflow_conflict: selected product outside active brand catalog'; END IF;
END $$;
REVOKE ALL ON FUNCTION milo_assert_product(uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION milo_assert_product(uuid,text) TO service_role;
CREATE OR REPLACE FUNCTION milo_store(p_action text,p_args jsonb DEFAULT '{}') RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE o uuid:=(p_args->>'org')::uuid; c milo_campaigns;j milo_jobs;x jsonb;result jsonb;cfg jsonb;
 defaults jsonb:='{"daily_enabled":true,"spike_enabled":true,"daily_hour":9,"timezone":"Asia/Tashkent","spike_threshold":5,"window_days":7,"cooldown_hours":24}';
 fingerprint jsonb;old_fingerprint jsonb;v_key text;cutoff timestamptz;source memory_sources;brand_revision bigint;
 d uuid;draft_revision bigint;new_status text;input text;s integer;e integer;prior_evidence jsonb;
BEGIN
 IF p_action='organizations' THEN
  RETURN coalesce((SELECT jsonb_agg(org_id) FROM (SELECT org_id FROM brand_passports UNION SELECT org_id FROM milo_settings) t),'[]');
 END IF;
 IF p_action IN ('settings','save_settings','enqueue','decide','retry','reconcile') THEN
  IF o IS NULL OR NOT EXISTS(SELECT 1 FROM orgs WHERE id=o) THEN RAISE EXCEPTION 'workflow_conflict: organization required'; END IF;
  PERFORM workflow_lock(o);
 END IF;
 IF p_action='replay_reconcile' THEN
  fingerprint:=jsonb_build_object('operation','reconcile','id',p_args->>'id','task_id',p_args->>'task_id');
  SELECT m.fingerprint,m.result INTO old_fingerprint,result FROM milo_decisions m WHERE m.org_id=o AND m.key=p_args->>'key';
  IF FOUND AND fingerprint<>old_fingerprint THEN RAISE EXCEPTION 'workflow_conflict: reused key'; END IF;
  RETURN result;
 END IF;
 IF p_action IN ('retry','reconcile') AND nullif(p_args->>'key','') IS NOT NULL THEN
  v_key:=p_args->>'key';fingerprint:=jsonb_build_object('operation',p_action,'id',p_args->>'id','task_id',p_args->>'task_id');
  SELECT m.fingerprint,m.result INTO old_fingerprint,result FROM milo_decisions m WHERE m.org_id=o AND m.key=v_key;
  IF FOUND THEN
   IF fingerprint<>old_fingerprint THEN RAISE EXCEPTION 'workflow_conflict: reused key'; END IF;
   RETURN result;
  END IF;
 END IF;
 SELECT defaults||coalesce(values,'{}') INTO cfg FROM milo_settings WHERE org_id=o;
 cfg:=coalesce(cfg,defaults);
 IF p_action='settings' THEN RETURN cfg;
 ELSIF p_action='save_settings' THEN
  cfg:=cfg||coalesce(p_args->'values','{}');
  IF (cfg->>'daily_hour')::int NOT BETWEEN 0 AND 23 OR (cfg->>'spike_threshold')::int NOT BETWEEN 1 AND 1000
   OR (cfg->>'window_days')::int NOT BETWEEN 1 AND 365 OR (cfg->>'cooldown_hours')::int NOT BETWEEN 1 AND 720
   OR NOT EXISTS(SELECT 1 FROM pg_timezone_names WHERE name=cfg->>'timezone')
   OR jsonb_typeof(cfg->'daily_enabled')<>'boolean' OR jsonb_typeof(cfg->'spike_enabled')<>'boolean'
   THEN RAISE EXCEPTION 'workflow_conflict: invalid settings'; END IF;
  INSERT INTO milo_settings(org_id,values) VALUES(o,cfg) ON CONFLICT(org_id) DO UPDATE SET values=excluded.values,updated_at=clock_timestamp();
  RETURN cfg;
 ELSIF p_action='enqueue' THEN
  v_key:=coalesce(nullif(p_args->>'key',''),gen_random_uuid()::text);
  SELECT * INTO c FROM milo_campaigns WHERE org_id=o AND dedup_key=v_key;
  IF FOUND THEN
   IF p_args->>'trigger'='manual' THEN
    SELECT payload INTO x FROM milo_jobs WHERE campaign_id=c.id AND kind='generate' AND org_id=o;
    IF c.trigger IS DISTINCT FROM p_args->>'trigger' OR c.prompt IS DISTINCT FROM p_args->>'prompt'
     OR c.language IS DISTINCT FROM p_args->>'language'
     OR (x ? 'requested_product_id' AND ((x->>'requested_product_id') IS DISTINCT FROM (p_args->>'product_id')
      OR (x->>'requested_topic') IS DISTINCT FROM (p_args->>'topic')))
     OR (NOT coalesce(x ? 'requested_product_id',false) AND p_args->>'product_id' IS NOT NULL
      AND c.product_id IS DISTINCT FROM p_args->>'product_id')
     THEN RAISE EXCEPTION 'workflow_conflict: reused key'; END IF;
   END IF;
   RETURN to_jsonb(c);
  END IF;
  PERFORM milo_assert_product(o,p_args->>'product_id');
  IF p_args->>'trigger'<>'manual' AND NOT (cfg->>((p_args->>'trigger')||'_enabled'))::boolean THEN RETURN NULL; END IF;
  IF p_args->>'trigger'<>'manual' AND jsonb_typeof(p_args->'evidence_ids')='array' THEN
   SELECT evidence_ids INTO prior_evidence FROM milo_campaigns WHERE org_id=o AND trigger<>'manual'
    AND topic IS NOT DISTINCT FROM p_args->>'topic' AND product_id IS NOT DISTINCT FROM p_args->>'product_id' ORDER BY created_at DESC LIMIT 1;
   IF jsonb_array_length(p_args->'evidence_ids')=0 OR (prior_evidence IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM jsonb_array_elements_text(p_args->'evidence_ids') AS t(id) WHERE NOT prior_evidence ? t.id)) THEN RETURN NULL; END IF;
  END IF;
  IF p_args->>'trigger'<>'manual' AND EXISTS(SELECT 1 FROM milo_campaigns WHERE org_id=o AND trigger<>'manual'
   AND topic IS NOT DISTINCT FROM p_args->>'topic' AND product_id IS NOT DISTINCT FROM p_args->>'product_id'
   AND created_at>clock_timestamp()-make_interval(hours=>(cfg->>'cooldown_hours')::int)) THEN RETURN NULL; END IF;
  IF p_args->>'trigger'='daily' AND EXISTS(SELECT 1 FROM milo_campaigns WHERE org_id=o AND daily_key=(clock_timestamp() AT TIME ZONE (cfg->>'timezone'))::date::text) THEN RETURN NULL; END IF;
  INSERT INTO milo_campaigns(org_id,trigger,prompt,language,dedup_key,topic,product_id,daily_key,evidence_ids)
   VALUES(o,p_args->>'trigger',coalesce(p_args->>'prompt',''),p_args->>'language',v_key,p_args->>'topic',p_args->>'product_id',
   CASE WHEN p_args->>'trigger'='daily' THEN (clock_timestamp() AT TIME ZONE (cfg->>'timezone'))::date::text END,
   CASE WHEN jsonb_typeof(p_args->'evidence_ids')='array' THEN p_args->'evidence_ids' ELSE '[]' END) RETURNING * INTO c;
  INSERT INTO milo_jobs(org_id,kind,payload,dedup_key,campaign_id) VALUES(o,'generate',jsonb_build_object('campaign_id',c.id,'requested_product_id',p_args->>'product_id','requested_topic',p_args->>'topic'),c.id::text,c.id);
  RETURN to_jsonb(c);
 ELSIF p_action='list' THEN
  RETURN coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY t.created_at DESC) FROM milo_campaigns t WHERE org_id=o),'[]');
 ELSIF p_action='get' THEN RETURN (SELECT to_jsonb(t) FROM milo_campaigns t WHERE org_id=o AND id=(p_args->>'id')::uuid);
 ELSIF p_action='jobs' THEN RETURN coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY t.created_at) FROM milo_jobs t WHERE org_id=o),'[]');
 ELSIF p_action='objections' THEN
  RETURN coalesce((SELECT jsonb_agg(to_jsonb(t) ORDER BY t.created_at) FROM milo_objections t WHERE org_id=o AND created_at>=(p_args->>'since')::timestamptz),'[]');
 ELSIF p_action='claim' THEN
  result:='[]';
  -- Exhaust expired jobs first. Preserve submission state for later operator reconciliation.
  FOR j IN UPDATE milo_jobs SET status='failed',lease_token=NULL,lease_until=NULL,last_error='Worker retries exhausted'
   WHERE kind=p_args->>'kind' AND status='leased' AND lease_until<=clock_timestamp() AND attempts>=3 RETURNING * LOOP
   UPDATE milo_campaigns SET status=CASE WHEN j.kind='generate' THEN 'failed' ELSE status END,
    build_status=CASE WHEN j.kind='build' THEN 'failed' ELSE build_status END,updated_at=clock_timestamp() WHERE id=j.campaign_id;
  END LOOP;
  FOR j IN SELECT * FROM milo_jobs WHERE kind=p_args->>'kind' AND attempts<3
    AND ((status='pending' AND available_at<=clock_timestamp()) OR (status='leased' AND lease_until<=clock_timestamp()))
    ORDER BY available_at,created_at FOR UPDATE SKIP LOCKED LIMIT greatest(1,least(coalesce((p_args->>'limit')::int,1),100)) LOOP
   UPDATE milo_jobs SET status='leased',attempts=attempts+1,lease_token=gen_random_uuid(),
    lease_until=clock_timestamp()+make_interval(secs=>greatest(10,least(coalesce((p_args->>'lease_seconds')::int,600),3600))) WHERE id=j.id RETURNING * INTO j;
   UPDATE milo_campaigns SET status=CASE WHEN j.kind='generate' THEN 'generating' ELSE status END,
    build_status=CASE WHEN j.kind='build' THEN 'running' ELSE build_status END,updated_at=clock_timestamp() WHERE id=j.campaign_id;
   result:=result||jsonb_build_array(to_jsonb(j));
  END LOOP;
  RETURN result;
 ELSIF p_action='decide' THEN
  v_key:=p_args->>'key'; fingerprint:=p_args-'org'-'key'-'compliance';
  IF coalesce(v_key,'')='' THEN RAISE EXCEPTION 'workflow_conflict: idempotency key required'; END IF;
  SELECT m.fingerprint,m.result INTO old_fingerprint,result FROM milo_decisions m WHERE m.org_id=o AND m.key=v_key;
  IF FOUND THEN
   IF fingerprint<>old_fingerprint THEN RAISE EXCEPTION 'workflow_conflict: reused key'; END IF;
   RETURN result;
  END IF;
  SELECT * INTO c FROM milo_campaigns WHERE org_id=o AND id=(p_args->>'id')::uuid FOR UPDATE;
  IF NOT FOUND OR c.revision<>(p_args->>'revision')::bigint OR c.status NOT IN ('awaiting_review','blocked') OR c.script_status<>'pending'
   THEN RAISE EXCEPTION 'workflow_conflict: campaign revision'; END IF;
  IF p_args->>'action'='approve' THEN
   PERFORM milo_assert_product(o,c.product_id);
   x:=CASE WHEN jsonb_typeof(p_args->'compliance')='object' THEN p_args->'compliance' ELSE c.compliance END;
   IF NOT coalesce((x->>'passed')::boolean,false) OR NOT coalesce((x->>'semantic_checked')::boolean,false)
     OR (x->>'checked_brand_revision')::bigint IS DISTINCT FROM (c.artifact->>'brand_revision')::bigint OR c.missing_evidence<>'[]'
     THEN RAISE EXCEPTION 'workflow_conflict: compliance required'; END IF;
   PERFORM milo_assert_evidence(o,c.artifact);
   INSERT INTO milo_jobs(org_id,kind,payload,dedup_key,campaign_id) VALUES(o,'build',jsonb_build_object('campaign_id',c.id,
    'product_id',c.product_id,'script_revision',c.revision,'video_script',c.artifact->'video_script','language',coalesce(c.artifact->>'language',c.language,'en'),'submission_state','not_submitted','provider_attempt',1),c.id::text||':'||c.revision::text,c.id)
    ON CONFLICT DO NOTHING;
   UPDATE milo_campaigns SET script_status='approved',build_status='queued',compliance=x,revision=revision+1,updated_at=clock_timestamp() WHERE id=c.id RETURNING * INTO c;
  ELSIF p_args->>'action'='edit' THEN
   IF jsonb_typeof(p_args->'script')<>'array' OR jsonb_array_length(p_args->'script')=0 THEN RAISE EXCEPTION 'workflow_conflict: script required'; END IF;
   x:=CASE WHEN jsonb_typeof(p_args->'compliance')='object' THEN p_args->'compliance' ELSE '{}' END;
   UPDATE milo_campaigns SET artifact=jsonb_set(artifact,'{video_script}',p_args->'script'),compliance=x,
    status=CASE WHEN coalesce((x->>'passed')::boolean,false) THEN 'awaiting_review' ELSE 'blocked' END,revision=revision+1,updated_at=clock_timestamp() WHERE id=c.id RETURNING * INTO c;
  ELSIF p_args->>'action'='reject' THEN
   UPDATE milo_campaigns SET script_status='rejected',revision=revision+1,updated_at=clock_timestamp() WHERE id=c.id RETURNING * INTO c;
  ELSE RAISE EXCEPTION 'workflow_conflict: invalid action'; END IF;
  result:=to_jsonb(c);
  INSERT INTO milo_decisions(org_id,key,fingerprint,result) VALUES(o,v_key,fingerprint,result);
  RETURN result;
 ELSIF p_action='reconcile' THEN
  UPDATE milo_jobs SET payload=payload||jsonb_build_object('provider_task_id',p_args->>'task_id','task_id',p_args->>'task_id','submission_state','submitted'),
   status='pending',attempts=0,available_at=clock_timestamp(),lease_until=NULL,lease_token=NULL,last_error=NULL
   WHERE org_id=o AND id=(p_args->>'id')::uuid AND kind='build' AND status='failed'
   AND payload->>'submission_state' IN ('submitting','submission_started','ambiguous')
   AND nullif(payload->>'provider_task_id','') IS NULL AND nullif(payload->>'task_id','') IS NULL RETURNING * INTO j;
  IF NOT FOUND OR coalesce(trim(p_args->>'task_id'),'')='' THEN RAISE EXCEPTION 'workflow_conflict: receipt not applicable'; END IF;
  UPDATE milo_campaigns SET build_status='queued',updated_at=clock_timestamp() WHERE id=j.campaign_id;
  result:=to_jsonb(j);
  IF v_key IS NOT NULL THEN INSERT INTO milo_decisions(org_id,key,fingerprint,result) VALUES(o,v_key,fingerprint,result); END IF;
  RETURN result;
 ELSIF p_action='retry' THEN
  SELECT * INTO j FROM milo_jobs WHERE org_id=o AND id=(p_args->>'id')::uuid FOR UPDATE;
  IF FOUND AND j.kind='build' AND j.payload->>'submission_state' IN ('submitting','submission_started','ambiguous')
   AND nullif(j.payload->>'provider_task_id','') IS NULL AND nullif(j.payload->>'task_id','') IS NULL
   THEN RAISE EXCEPTION 'workflow_conflict: provider receipt reconciliation required'; END IF;
  UPDATE milo_jobs SET status='pending',attempts=0,available_at=clock_timestamp(),lease_until=NULL,lease_token=NULL,last_error=NULL,
   payload=CASE WHEN kind='build' AND payload->>'submission_state'='provider_failed' THEN
    (payload-'provider_task_id'-'task_id')||jsonb_build_object('submission_state','not_submitted','provider_attempt',coalesce((payload->>'provider_attempt')::int,1)+1,
     'provider_attempts',coalesce(payload->'provider_attempts','[]'::jsonb)||jsonb_build_array(jsonb_build_object(
      'provider_attempt',coalesce((payload->>'provider_attempt')::int,1),'provider_task_id',coalesce(payload->>'provider_task_id',payload->>'task_id'),
      'submission_state','provider_failed','finished_at',clock_timestamp()))) ELSE payload END
   WHERE org_id=o AND id=(p_args->>'id')::uuid AND status='failed' RETURNING * INTO j;
  IF NOT FOUND THEN RAISE EXCEPTION 'workflow_conflict: only failed jobs can retry'; END IF;
  UPDATE milo_campaigns SET status=CASE WHEN j.kind='generate' THEN 'queued' ELSE status END,
   build_status=CASE WHEN j.kind='build' THEN 'queued' ELSE build_status END,updated_at=clock_timestamp() WHERE id=j.campaign_id;
  result:=to_jsonb(j);
  IF v_key IS NOT NULL THEN INSERT INTO milo_decisions(org_id,key,fingerprint,result) VALUES(o,v_key,fingerprint,result); END IF;
  RETURN result;
 END IF;
 -- All completion and provider progress writes are fenced by the active lease.
 SELECT * INTO j FROM milo_jobs WHERE id=(p_args->>'job')::uuid FOR UPDATE;
 IF NOT FOUND OR j.status<>'leased' OR j.lease_token IS DISTINCT FROM (p_args->>'token')::uuid OR j.lease_until<=clock_timestamp() THEN
  IF p_action='fail' THEN RETURN 'false'; END IF;
  RAISE EXCEPTION 'workflow_conflict: stale lease';
 END IF;
 IF p_action='renew' THEN
  UPDATE milo_jobs SET lease_until=clock_timestamp()+make_interval(secs=>greatest(10,least(coalesce((p_args->>'lease_seconds')::int,600),3600)))
   WHERE id=j.id RETURNING to_jsonb(milo_jobs.*) INTO result;
  RETURN result;
 ELSIF p_action='extracted' AND j.kind='extract' THEN
  -- Check all spans before inserting any. PostgreSQL substring is one-based.
  input:=j.payload->>'text';
  FOR x IN SELECT value FROM jsonb_array_elements(p_args->'items') LOOP
   s:=(x->>'span_start')::int;e:=(x->>'span_end')::int;
   IF s<0 OR e<=s OR substring(input FROM s+1 FOR e-s) IS DISTINCT FROM x->>'buyer_text' OR coalesce(trim(x->>'topic'),'')=''
    THEN RAISE EXCEPTION 'workflow_conflict: invalid buyer span'; END IF;
   IF x->>'product_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM brand_products WHERE org_id=j.org_id AND id::text=x->>'product_id' AND deleted_at IS NULL)
    THEN RAISE EXCEPTION 'workflow_conflict: objection product outside brand catalog'; END IF;
  END LOOP;
  FOR x IN SELECT value FROM jsonb_array_elements(p_args->'items') LOOP
   INSERT INTO milo_objections(org_id,inbound_id,prospect_id,product_id,topic,objection_type,buyer_text,span_start,span_end,created_at)
    VALUES(j.org_id,(j.payload->>'inbound_id')::uuid,(j.payload->>'prospect_id')::uuid,x->>'product_id',x->>'topic',x->>'objection_type',x->>'buyer_text',
     (x->>'span_start')::int,(x->>'span_end')::int,(j.payload->>'received_at')::timestamptz) ON CONFLICT DO NOTHING;
  END LOOP;
  result:='true';
 ELSIF p_action='generated' AND j.kind='generate' THEN
  SELECT * INTO c FROM milo_campaigns WHERE id=j.campaign_id AND org_id=j.org_id FOR UPDATE;
  x:=p_args->'selected_scope';
  IF x IS NOT NULL AND x<>'null'::jsonb THEN
   IF jsonb_typeof(x)<>'object' THEN RAISE EXCEPTION 'workflow_conflict: invalid generation scope'; END IF;
   IF NOT (x ? 'product_id' AND x ? 'topic') OR x-'product_id'-'topic'<>'{}'::jsonb
    OR coalesce(x->>'topic','') NOT IN ('price','durability','trust','timing','fit','availability','payment','delivery','returns','usability','other')
    OR jsonb_typeof(x->'product_id') NOT IN ('null','string')
    OR (jsonb_typeof(x->'product_id')='string' AND length(btrim(x->>'product_id'))=0)
    THEN RAISE EXCEPTION 'workflow_conflict: invalid generation scope'; END IF;
   IF (c.topic IS NOT NULL AND (c.topic IS DISTINCT FROM x->>'topic' OR c.product_id IS DISTINCT FROM x->>'product_id'))
    OR (c.product_id IS NOT NULL AND c.product_id IS DISTINCT FROM x->>'product_id')
    THEN RAISE EXCEPTION 'workflow_conflict: generation scope differs from reserved evidence'; END IF;
  END IF;
  PERFORM milo_assert_product(j.org_id,CASE WHEN jsonb_typeof(x)='object' THEN x->>'product_id' ELSE c.product_id END);
  UPDATE milo_campaigns SET
   product_id=CASE WHEN jsonb_typeof(x)='object' THEN x->>'product_id' ELSE product_id END,
   topic=CASE WHEN jsonb_typeof(x)='object' THEN x->>'topic' ELSE topic END,
   artifact=p_args->'artifact',compliance=p_args->'compliance',missing_evidence=p_args->'missing',
   status=CASE WHEN p_args->'missing'<>'[]' THEN 'needs_evidence' WHEN coalesce((p_args->'compliance'->>'passed')::boolean,false) THEN 'awaiting_review' ELSE 'blocked' END,
   revision=revision+1,updated_at=clock_timestamp() WHERE id=j.campaign_id RETURNING to_jsonb(milo_campaigns.*) INTO result;
 ELSIF p_action='update_build' AND j.kind='build' THEN
  IF p_args->'values' ? 'product_id' AND (p_args->'values'->>'product_id') IS DISTINCT FROM
    (SELECT product_id FROM milo_campaigns WHERE id=j.campaign_id AND org_id=j.org_id)
   THEN RAISE EXCEPTION 'workflow_conflict: cannot replace approved product scope'; END IF;
  IF p_args->'values'->>'submission_state' IN ('submission_started','submitting')
   AND nullif(j.payload->>'provider_task_id','') IS NULL AND nullif(j.payload->>'task_id','') IS NULL THEN
   SELECT * INTO c FROM milo_campaigns WHERE org_id=j.org_id AND id=j.campaign_id FOR SHARE;
   PERFORM milo_assert_evidence(j.org_id,c.artifact);
  END IF;
  UPDATE milo_jobs SET payload=payload||(p_args->'values') WHERE id=j.id RETURNING to_jsonb(milo_jobs.*) INTO result;
  RETURN result;
 ELSIF p_action='built' AND j.kind='build' THEN
  -- Video remains behind the existing HITL review gate.
  PERFORM workflow_lock(j.org_id);
  INSERT INTO drafts(org_id,agent_slug,inbound_text,draft_content,status) VALUES(j.org_id,'vea','Milo approved video script',(p_args->'result')::text,'PENDING_DRAFT') RETURNING id,revision INTO d,draft_revision;
  PERFORM workflow_transition(j.org_id,d,'ready',draft_revision,'milo-built:'||j.id::text,(p_args->'result')::text);
  INSERT INTO squad_messages(org_id,sender_slug,content,hitl_draft_id) VALUES(j.org_id,'vea','Milo video ready for review',d);
  UPDATE milo_campaigns SET build_status='completed',result=(p_args->'result')||jsonb_build_object('draft_id',d),updated_at=clock_timestamp()
   WHERE id=j.campaign_id RETURNING to_jsonb(milo_campaigns.*) INTO result;
 ELSIF p_action='fail' THEN
  new_status:=CASE WHEN j.attempts>=3 OR p_args->>'error'='LanguageServiceUnavailable' OR (j.kind='build' AND j.payload->>'submission_state'='provider_failed') OR (j.kind='build' AND j.payload->>'submission_state' IN ('submitting','submission_started','ambiguous')
   AND nullif(j.payload->>'provider_task_id','') IS NULL AND nullif(j.payload->>'task_id','') IS NULL) THEN 'failed' ELSE 'pending' END;
  UPDATE milo_jobs SET status=new_status,payload=CASE WHEN j.kind='build' AND new_status='failed'
   AND payload->>'submission_state' IN ('submitting','submission_started','ambiguous') AND nullif(payload->>'provider_task_id','') IS NULL AND nullif(payload->>'task_id','') IS NULL
   THEN payload||'{"submission_state":"ambiguous"}'::jsonb ELSE payload END,available_at=clock_timestamp()+make_interval(secs=>5*power(2,attempts)::int),
   lease_token=NULL,lease_until=NULL,last_error=CASE WHEN p_args->>'error'='LanguageServiceUnavailable'
    THEN 'The configured language service is temporarily unavailable. Retry after provider recovery.'
    ELSE 'Milo processing failed; retry available.' END WHERE id=j.id;
  UPDATE milo_campaigns SET status=CASE WHEN j.kind='generate' THEN CASE WHEN new_status='failed' THEN 'failed' ELSE 'queued' END ELSE status END,
   build_status=CASE WHEN j.kind='build' THEN CASE WHEN new_status='failed' THEN 'failed' ELSE 'queued' END ELSE build_status END,
   updated_at=clock_timestamp() WHERE id=j.campaign_id;
  RETURN 'true';
 ELSE RAISE EXCEPTION 'workflow_conflict: invalid worker operation'; END IF;
 UPDATE milo_jobs SET status='completed',lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=j.id;
 RETURN result;
END $$;

REVOKE ALL ON FUNCTION milo_store(text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION milo_store(text,jsonb) TO service_role;
