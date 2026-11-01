-- Read-only central approval projection. Apply after 010 and 011 in a separate
-- migration rollout. Only the authenticated core API may call this service RPC.
CREATE INDEX IF NOT EXISTS drafts_pending_feed ON public.drafts(org_id, created_at, id)
 WHERE status='AWAITING_HITL' AND superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS milo_pending_feed ON public.milo_campaigns(org_id, created_at, id)
 WHERE script_status='pending' AND status IN ('awaiting_review','blocked','needs_evidence');

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
    'restrictions',jsonb_build_object('can_approve',true,'can_edit',coalesce(d.vea_artifact,'null'::jsonb) IN ('null'::jsonb,'{}'::jsonb),
      'can_reject',true,'reasons','[]'::jsonb),
    'payload',jsonb_build_object('draft',to_jsonb(d))) AS item
  FROM public.drafts d
  WHERE d.org_id=p_org_id AND d.status='AWAITING_HITL' AND d.superseded_by IS NULL
   AND coalesce(d.vea_artifact->>'superseded','false') <> 'true'
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
