-- Director masters have their own artifact contract and final human gate.
CREATE OR REPLACE FUNCTION milo_director_guard_draft() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r milo_director_runs; d milo_director_documents; c milo_campaigns;
BEGIN
 IF OLD.director_artifact IS NULL THEN RETURN NEW; END IF;
 IF NEW.status IN ('EDITED','PUBLISHED') OR NEW.delivery_status IN ('sending','delivered')
  OR NEW.draft_content IS DISTINCT FROM OLD.draft_content
  OR (NEW.director_artifact-'superseded'-'superseded_by'-'superseded_storyboard_revision')
      IS DISTINCT FROM (OLD.director_artifact-'superseded'-'superseded_by'-'superseded_storyboard_revision')
  OR NEW.delivery_claimed_at IS DISTINCT FROM OLD.delivery_claimed_at THEN
   RAISE EXCEPTION 'workflow_conflict: director masters support approval and export only';
 END IF;
 IF NEW.status='APPROVED' AND OLD.status IS DISTINCT FROM NEW.status THEN
  PERFORM workflow_lock(OLD.org_id);
  SELECT * INTO r FROM milo_director_runs WHERE org_id=OLD.org_id AND id=(OLD.director_artifact->>'director_run_id')::uuid FOR SHARE;
  IF NOT FOUND OR r.superseded_by IS NOT NULL OR coalesce((r.document->>'document_fenced')::boolean,false)
   OR r.document->>'state'<>'AWAITING_HITL' OR r.document->>'draft_id'<>OLD.id::text
   OR coalesce((OLD.director_artifact->>'superseded')::boolean,false)
   OR OLD.director_artifact->'inspection'->>'passed' IS DISTINCT FROM 'true' THEN
   RAISE EXCEPTION 'workflow_conflict: stale or uninspected director master';
  END IF;
  SELECT * INTO d FROM milo_director_documents WHERE org_id=OLD.org_id AND campaign_id=r.campaign_id FOR SHARE;
  IF d.document->'storyboard'->>'narration_approved' IS DISTINCT FROM 'true'
    OR d.document->'storyboard'->>'revision' IS DISTINCT FROM r.document->>'storyboard_revision'
    OR d.document->>'campaign_revision' IS DISTINCT FROM r.document->>'approved_revision' THEN
   RAISE EXCEPTION 'workflow_conflict: narration changed';
  END IF;
  SELECT * INTO c FROM milo_campaigns WHERE org_id=OLD.org_id AND id=r.campaign_id FOR SHARE;
  IF NOT FOUND OR c.script_status<>'approved' OR c.revision<>(r.document->>'approved_revision')::bigint
    OR c.product_id IS DISTINCT FROM r.document->>'product_id' THEN
   RAISE EXCEPTION 'workflow_conflict: approved campaign scope changed'; END IF;
  PERFORM milo_assert_product(OLD.org_id,c.product_id);
  IF c.artifact IS NOT NULL THEN PERFORM milo_assert_evidence(OLD.org_id,c.artifact); END IF;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS milo_director_guard_draft ON drafts;
CREATE TRIGGER milo_director_guard_draft BEFORE UPDATE ON drafts FOR EACH ROW EXECUTE FUNCTION milo_director_guard_draft();
REVOKE ALL ON FUNCTION milo_director_guard_draft() FROM PUBLIC,anon,authenticated;

-- Preserve snapshot pagination while excluding superseded director masters.
CREATE OR REPLACE FUNCTION public.pending_approval_feed(
 p_org_id uuid, p_limit integer DEFAULT 50,
 p_after_created timestamptz DEFAULT NULL, p_after_id text DEFAULT NULL,
 p_snapshot timestamptz DEFAULT NULL
) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
 WITH boundary AS (
  SELECT coalesce(p_snapshot, statement_timestamp()) AS snapshot_at
 ), pending AS (
  SELECT 'workflow:' || d.id::text AS id, d.created_at,
   jsonb_build_object('id','workflow:' || d.id::text,'kind','workflow','source_id',d.id,
    'revision',d.revision,'created_at',d.created_at,
    'restrictions',jsonb_build_object('can_approve',true,'can_edit',(coalesce(d.vea_artifact,'null'::jsonb) IN ('null'::jsonb,'{}'::jsonb) AND coalesce(d.director_artifact,'null'::jsonb) IN ('null'::jsonb,'{}'::jsonb)),
      'can_reject',true,'reasons','[]'::jsonb),
    'payload',jsonb_build_object('draft',to_jsonb(d))) AS item
  FROM public.drafts d
  WHERE d.org_id=p_org_id AND d.status='AWAITING_HITL' AND d.superseded_by IS NULL
   AND coalesce(d.vea_artifact->>'superseded','false') <> 'true'
   AND coalesce(d.director_artifact->>'superseded','false') <> 'true'
  UNION ALL
  SELECT 'milo:' || c.id::text, c.created_at,
   jsonb_build_object('id','milo:' || c.id::text,'kind','milo','source_id',c.id,
    'revision',c.revision,'created_at',c.created_at,
    'restrictions',jsonb_build_object(
     'can_approve',(coalesce(jsonb_typeof(c.artifact),'null')='object' AND c.artifact<>'{}'::jsonb) AND c.status='awaiting_review' AND c.build_status IS NULL AND coalesce(c.compliance->>'passed','false')='true',
     'can_edit',(coalesce(jsonb_typeof(c.artifact),'null')='object' AND c.artifact<>'{}'::jsonb) AND c.status IN ('awaiting_review','blocked') AND c.build_status IS NULL,
     'can_reject',(coalesce(jsonb_typeof(c.artifact),'null')='object' AND c.artifact<>'{}'::jsonb) AND c.status IN ('awaiting_review','blocked') AND c.build_status IS NULL,
     'reasons', CASE
      WHEN coalesce(c.compliance->'violations','[]'::jsonb) || c.missing_evidence <> '[]'::jsonb
       THEN coalesce(c.compliance->'violations','[]'::jsonb) || c.missing_evidence
      WHEN NOT ((coalesce(jsonb_typeof(c.artifact),'null')='object' AND c.artifact<>'{}'::jsonb) AND c.status='awaiting_review' AND c.build_status IS NULL AND coalesce(c.compliance->>'passed','false')='true')
       THEN '["Campaign requires evidence or compliance review before approval"]'::jsonb
      ELSE '[]'::jsonb END),
    'payload',jsonb_build_object('campaign',to_jsonb(c),'review_href','/agents/milo#campaign-' || c.id::text))
  FROM public.milo_campaigns c
  WHERE c.org_id=p_org_id AND c.script_status='pending'
   AND c.status IN ('awaiting_review','blocked','needs_evidence')
 ), candidates AS MATERIALIZED (
  SELECT p.* FROM pending p CROSS JOIN boundary b
  WHERE p.created_at <= b.snapshot_at
   AND (p_after_created IS NULL OR p.created_at > p_after_created
        OR (p.created_at=p_after_created AND p.id COLLATE "C" > p_after_id COLLATE "C"))
  ORDER BY p.created_at, p.id COLLATE "C" LIMIT greatest(1,least(p_limit,100))+1
 ), page AS (
  SELECT * FROM candidates ORDER BY created_at,id COLLATE "C" LIMIT greatest(1,least(p_limit,100))
 ) SELECT jsonb_build_object(
   'items',coalesce((SELECT jsonb_agg(item ORDER BY created_at,id COLLATE "C") FROM page),'[]'::jsonb),
   'has_more',(SELECT count(*) FROM candidates)>greatest(1,least(p_limit,100)),
   'snapshot_at',(SELECT snapshot_at FROM boundary)
 );
$$;
REVOKE ALL ON FUNCTION public.pending_approval_feed(uuid,integer,timestamptz,text,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.pending_approval_feed(uuid,integer,timestamptz,text,timestamptz) TO service_role;
