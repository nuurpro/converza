-- Canonical transactional HITL and commit-ordered organization event log.
-- Apply after 004. RPCs are service-role only; browser clients use authenticated APIs.
ALTER TABLE drafts DROP CONSTRAINT IF EXISTS drafts_status_check;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 1;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS generation_error text;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS generation_status text NOT NULL DEFAULT 'pending';
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS delivery_status text NOT NULL DEFAULT 'idle';
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS delivery_error text;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS delivery_attempt_id text;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS delivery_claimed_at timestamptz;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS delivery_receipt jsonb;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS delivered_at timestamptz;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS resolved_at timestamptz;
ALTER TABLE drafts ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
UPDATE drafts SET status = CASE lower(status)
 WHEN 'pending' THEN 'AWAITING_HITL' WHEN 'approved' THEN 'APPROVED'
 WHEN 'edited' THEN 'EDITED' WHEN 'rejected' THEN 'REJECTED' ELSE upper(status) END;
ALTER TABLE drafts ALTER COLUMN status SET DEFAULT 'PENDING_DRAFT';
ALTER TABLE drafts ADD CONSTRAINT drafts_status_check CHECK
 (status IN ('PENDING_DRAFT','AWAITING_HITL','APPROVED','EDITED','REJECTED','PUBLISHED'));
ALTER TABLE drafts ADD CONSTRAINT drafts_delivery_status_check CHECK
 (delivery_status IN ('idle','sending','failed','ambiguous','delivered'));
ALTER TABLE drafts ADD CONSTRAINT drafts_published_receipt_check CHECK
 (status <> 'PUBLISHED' OR (delivered_at IS NOT NULL AND delivery_receipt IS NOT NULL));
ALTER TABLE drafts ADD CONSTRAINT drafts_resolution_check CHECK
 (resolved_at IS NULL OR (status='PUBLISHED' AND delivered_at IS NOT NULL));

CREATE TABLE workflow_event_cursors (
 org_id uuid PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE,
 sequence bigint NOT NULL DEFAULT 0
);
CREATE TABLE workflow_events (
 org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 id bigint NOT NULL,
 schema_version integer NOT NULL DEFAULT 1,
 type text NOT NULL,
 payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (org_id,id)
);
CREATE TABLE workflow_idempotency (
 org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 key text NOT NULL, request jsonb NOT NULL, response jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(org_id,key)
);
ALTER TABLE workflow_event_cursors ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_idempotency ENABLE ROW LEVEL SECURITY;

CREATE FUNCTION workflow_lock(p_org_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
 INSERT INTO workflow_event_cursors(org_id) VALUES(p_org_id) ON CONFLICT DO NOTHING;
 PERFORM 1 FROM workflow_event_cursors WHERE org_id=p_org_id FOR UPDATE;
END $$;

CREATE FUNCTION workflow_row_lock() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=public AS $$
BEGIN
 PERFORM workflow_lock(NEW.org_id);
 RETURN NEW;
END $$;
CREATE FUNCTION workflow_row_event() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=public AS $$
DECLARE seq bigint;
BEGIN
 UPDATE workflow_event_cursors SET sequence=sequence+1 WHERE org_id=NEW.org_id RETURNING sequence INTO seq;
 INSERT INTO workflow_events(org_id,id,type,payload)
 VALUES(NEW.org_id,seq,TG_ARGV[0],jsonb_build_object('row',to_jsonb(NEW)));
 RETURN NEW;
END $$;
CREATE TRIGGER workflow_draft_lock BEFORE INSERT OR UPDATE ON drafts FOR EACH ROW EXECUTE FUNCTION workflow_row_lock();
CREATE TRIGGER workflow_draft_event AFTER INSERT OR UPDATE ON drafts FOR EACH ROW EXECUTE FUNCTION workflow_row_event('draft_transition');
CREATE TRIGGER workflow_message_lock BEFORE INSERT ON squad_messages FOR EACH ROW EXECUTE FUNCTION workflow_row_lock();
CREATE TRIGGER workflow_message_event AFTER INSERT ON squad_messages FOR EACH ROW EXECUTE FUNCTION workflow_row_event('squad_message');
CREATE TRIGGER workflow_step_lock BEFORE INSERT ON agent_run_steps FOR EACH ROW EXECUTE FUNCTION workflow_row_lock();
CREATE TRIGGER workflow_step_event AFTER INSERT ON agent_run_steps FOR EACH ROW EXECUTE FUNCTION workflow_row_event('agent_run_step');

CREATE FUNCTION workflow_transition(p_org_id uuid, p_draft_id uuid, p_action text,
 p_expected_revision bigint, p_idempotency_key text, p_content text DEFAULT NULL,
 p_receipt jsonb DEFAULT NULL, p_error text DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE d drafts%ROWTYPE; prior workflow_idempotency%ROWTYPE; request jsonb; result jsonb; linked_run uuid;
BEGIN
 IF p_idempotency_key IS NULL OR length(trim(p_idempotency_key))=0 THEN
  RAISE EXCEPTION 'workflow_conflict: idempotency key required'; END IF;
 PERFORM workflow_lock(p_org_id);
 request := jsonb_build_array(p_draft_id,p_action,p_expected_revision,p_content,p_receipt,p_error);
 SELECT * INTO prior FROM workflow_idempotency WHERE org_id=p_org_id AND key=p_idempotency_key;
 IF FOUND THEN
  IF prior.request <> request THEN RAISE EXCEPTION 'workflow_conflict: idempotency key reused'; END IF;
  RETURN prior.response;
 END IF;
 SELECT * INTO d FROM drafts WHERE id=p_draft_id AND org_id=p_org_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'workflow_not_found'; END IF;
 IF d.revision <> p_expected_revision THEN RAISE EXCEPTION 'workflow_conflict: stale revision'; END IF;
 IF p_action='ready' AND d.status='PENDING_DRAFT' THEN
  IF coalesce(length(trim(p_content)),0)=0 THEN RAISE EXCEPTION 'workflow_conflict: empty generated content'; END IF;
  d.status := 'AWAITING_HITL'; d.draft_content := p_content; d.generation_error := NULL; d.generation_status := 'completed';
 ELSIF p_action='generation_started' AND d.status='PENDING_DRAFT' AND d.generation_status='pending' THEN
  d.generation_status := 'running';
 ELSIF p_action IN ('generation_failed','retry_generation') AND d.status='PENDING_DRAFT' THEN
  IF p_action='retry_generation' AND d.generation_status <> 'failed' THEN RAISE EXCEPTION 'workflow_conflict: generation not failed'; END IF;
  d.generation_status := CASE WHEN p_action='generation_failed' THEN 'failed' ELSE 'pending' END;
  d.generation_error := CASE WHEN p_action='generation_failed' THEN p_error ELSE NULL END;
 ELSIF p_action IN ('approve','edit','reject') AND d.status='AWAITING_HITL' THEN
  IF p_action='edit' AND coalesce(length(trim(p_content)),0)=0 THEN RAISE EXCEPTION 'workflow_conflict: final_content required'; END IF;
  d.status := CASE p_action WHEN 'approve' THEN 'APPROVED' WHEN 'edit' THEN 'EDITED' ELSE 'REJECTED' END;
  d.final_content := CASE p_action WHEN 'edit' THEN trim(p_content) WHEN 'approve' THEN d.draft_content ELSE NULL END;
  d.decided_at := clock_timestamp();
 ELSIF p_action IN ('publish','begin_delivery','delivery_failed','delivery_ambiguous','claim_delivery') AND d.status IN ('APPROVED','EDITED') THEN
  IF p_action='publish' THEN
   IF coalesce(p_receipt->>'channel','')='' OR coalesce(p_receipt->>'message_id','')='' OR d.delivery_attempt_id IS NULL OR p_receipt->>'attempt_id' IS DISTINCT FROM d.delivery_attempt_id THEN
    RAISE EXCEPTION 'workflow_conflict: publisher receipt required'; END IF;
   d.status := 'PUBLISHED'; d.delivery_status := 'delivered'; d.delivery_receipt := p_receipt;
   d.delivered_at := clock_timestamp(); d.delivery_error := NULL;
  ELSIF p_action='begin_delivery' THEN
   IF d.delivery_status IN ('ambiguous','sending') THEN RAISE EXCEPTION 'workflow_conflict: reconciliation required'; END IF;
   IF coalesce(p_receipt->>'attempt_id','')='' THEN RAISE EXCEPTION 'workflow_conflict: attempt id required'; END IF;
   d.delivery_status := 'sending'; d.delivery_error := NULL; d.delivery_attempt_id := p_receipt->>'attempt_id'; d.delivery_claimed_at := NULL;
  ELSIF p_action='claim_delivery' THEN
   IF d.delivery_status <> 'sending' OR d.delivery_claimed_at IS NOT NULL OR p_receipt->>'attempt_id' IS DISTINCT FROM d.delivery_attempt_id THEN RAISE EXCEPTION 'workflow_conflict: delivery already claimed'; END IF;
   d.delivery_claimed_at := clock_timestamp();
  ELSE
   d.delivery_status := CASE p_action WHEN 'delivery_failed' THEN 'failed' ELSE 'ambiguous' END;
   d.delivery_error := p_error;
  END IF;
 ELSIF p_action='resolve' AND d.agent_slug='sleyz' AND d.prospect_id IS NOT NULL AND d.status='PUBLISHED' AND d.delivered_at IS NOT NULL
  AND d.delivery_receipt IS NOT NULL AND d.resolved_at IS NULL THEN
  d.resolved_at := clock_timestamp();
 ELSE RAISE EXCEPTION 'workflow_conflict: invalid transition % from %',p_action,d.status;
 END IF;
 UPDATE drafts SET status=d.status, draft_content=d.draft_content, final_content=d.final_content,
  generation_status=d.generation_status, generation_error=d.generation_error, delivery_status=d.delivery_status, delivery_error=d.delivery_error,
  delivery_claimed_at=d.delivery_claimed_at, delivery_attempt_id=d.delivery_attempt_id, delivery_receipt=d.delivery_receipt, delivered_at=d.delivered_at, resolved_at=d.resolved_at,
  decided_at=d.decided_at, revision=d.revision+1, updated_at=clock_timestamp()
 WHERE id=p_draft_id RETURNING to_jsonb(drafts.*) INTO result;
 IF p_action IN ('approve','edit','reject') THEN
  SELECT related_run_id INTO linked_run FROM squad_messages WHERE org_id=p_org_id AND hitl_draft_id=p_draft_id
   AND related_run_id IS NOT NULL ORDER BY created_at DESC LIMIT 1;
  IF linked_run IS NOT NULL THEN
   UPDATE agent_runs SET status=CASE WHEN p_action='reject' THEN 'failed' ELSE 'completed' END,
    completed_at=clock_timestamp() WHERE id=linked_run AND org_id=p_org_id;
  END IF;
  INSERT INTO squad_messages(org_id,sender_slug,content,related_run_id,hitl_draft_id)
   VALUES(p_org_id,'converza','HITL '||d.status||': draft '||p_draft_id,linked_run,p_draft_id);
 END IF;
 INSERT INTO workflow_idempotency(org_id,key,request,response) VALUES(p_org_id,p_idempotency_key,request,result);
 RETURN result;
END $$;

CREATE FUNCTION workflow_snapshot(p_org_id uuid) RETURNS jsonb LANGUAGE plpgsql
SECURITY DEFINER SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
 PERFORM workflow_lock(p_org_id);
 SELECT jsonb_build_object('cursor',(SELECT sequence FROM workflow_event_cursors WHERE org_id=p_org_id),
 'drafts',coalesce((SELECT jsonb_agg(to_jsonb(d) ORDER BY created_at,id) FROM drafts d WHERE org_id=p_org_id),'[]'::jsonb),
 'messages',coalesce((SELECT jsonb_agg(to_jsonb(m) ORDER BY created_at,id) FROM squad_messages m WHERE org_id=p_org_id),'[]'::jsonb),
 'steps',coalesce((SELECT jsonb_agg(to_jsonb(s) ORDER BY created_at,id) FROM agent_run_steps s WHERE org_id=p_org_id),'[]'::jsonb)) INTO result;
 RETURN result;
END $$;
CREATE FUNCTION workflow_read_events(p_org_id uuid,p_after bigint,p_limit integer DEFAULT 200)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public AS $$
 SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY id),'[]'::jsonb) FROM
 (SELECT * FROM workflow_events WHERE org_id=p_org_id AND id>p_after ORDER BY id LIMIT greatest(1,least(p_limit,1000))) e;
$$;
-- No event retention is applied: cursors remain replayable. Future retention must return an explicit expired-cursor result.
REVOKE ALL ON FUNCTION workflow_lock(uuid), workflow_row_lock(), workflow_row_event(),
 workflow_transition(uuid,uuid,text,bigint,text,text,jsonb,text),workflow_snapshot(uuid),workflow_read_events(uuid,bigint,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION workflow_transition(uuid,uuid,text,bigint,text,text,jsonb,text),
 workflow_snapshot(uuid),workflow_read_events(uuid,bigint,integer) TO service_role;
GRANT ALL ON workflow_event_cursors,workflow_events,workflow_idempotency TO service_role;
