-- Optional one-time bridge for the inspected pre-workflow schema. Run before 004.
-- Run in one transaction with writers quiesced and a verified private backup.
-- No users are claimed, no source records deleted, no delivery is scheduled.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
LOCK TABLE public.orgs, public.brand_passports, public.prospects,
 public.messages, public.drafts, public.tg_connections IN ACCESS EXCLUSIVE MODE;

CREATE SCHEMA IF NOT EXISTS converza_private;
REVOKE ALL ON SCHEMA converza_private FROM PUBLIC,anon,authenticated;
CREATE TABLE IF NOT EXISTS converza_private.legacy_workspace_map (
 legacy_org_id text PRIMARY KEY,
 org_id uuid NOT NULL UNIQUE,
 migrated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE converza_private.legacy_workspace_map ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON converza_private.legacy_workspace_map FROM PUBLIC,anon,authenticated;

DO $$
DECLARE target text; has_blank boolean;
BEGIN
 IF to_regclass('public.workflow_events') IS NOT NULL THEN
  RAISE EXCEPTION 'legacy bridge is only for the pre-workflow schema';
 END IF;
 IF EXISTS(SELECT 1 FROM public.drafts d JOIN public.prospects p ON p.id=d.prospect_id WHERE d.org_id<>p.org_id)
  OR EXISTS(SELECT 1 FROM public.messages m JOIN public.prospects p ON p.id=m.prospect_id WHERE m.org_id<>p.org_id) THEN
  RAISE EXCEPTION 'legacy linked records disagree on tenant; verified repair required';
 END IF;
 FOREACH target IN ARRAY ARRAY['brand_passports','prospects','messages','drafts','tg_connections'] LOOP
  IF NOT EXISTS(SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name=target AND column_name='org_id' AND data_type='text') THEN
   RAISE EXCEPTION 'unexpected legacy tenant column: %',target;
  END IF;
  EXECUTE format('SELECT EXISTS(SELECT 1 FROM public.%I WHERE org_id IS NULL OR btrim(org_id)='''')',target) INTO has_blank;
  IF has_blank THEN RAISE EXCEPTION 'empty legacy tenant key in %',target; END IF;
 END LOOP;
END $$;

INSERT INTO converza_private.legacy_workspace_map(legacy_org_id,org_id)
 SELECT legacy_id,CASE WHEN pg_input_is_valid(legacy_id,'uuid')
   THEN legacy_id::uuid ELSE gen_random_uuid() END
 FROM (SELECT org_id AS legacy_id FROM public.brand_passports
  UNION SELECT org_id FROM public.prospects UNION SELECT org_id FROM public.messages
  UNION SELECT org_id FROM public.drafts UNION SELECT org_id FROM public.tg_connections) ids
 ON CONFLICT(legacy_org_id) DO NOTHING;

DO $$
DECLARE audit jsonb:=coalesce(nullif(current_setting('converza.legacy_org_audit',true),''),'[]')::jsonb;
BEGIN
 IF jsonb_typeof(audit)<>'array' THEN RAISE EXCEPTION 'invalid existing workspace audit'; END IF;
 IF EXISTS(SELECT 1 FROM converza_private.legacy_workspace_map m JOIN public.orgs o ON o.id=m.org_id
   WHERE EXISTS(SELECT 1 FROM public.brand_passports b WHERE b.org_id=m.legacy_org_id)
    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(audit) a
     WHERE a->>'id'=o.id::text AND o.name IS NOT DISTINCT FROM a->>'name'
       AND o.created_at IS NOT DISTINCT FROM (a->>'created_at')::timestamptz)) THEN
  RAISE EXCEPTION 'legacy tenant overlaps existing canonical workspace; explicit identity audit required';
 END IF;
END $$;

-- Exact legacy keys join across tables. Owners, names and emails never decide identity.
INSERT INTO public.orgs(id,name,created_at)
 SELECT m.org_id,coalesce(b.brand_name,'Recovered legacy workspace'),coalesce(b.created_at,now())
 FROM converza_private.legacy_workspace_map m
 LEFT JOIN public.brand_passports b ON b.org_id=m.legacy_org_id
 WHERE NOT EXISTS(SELECT 1 FROM public.orgs o WHERE o.id=m.org_id);

DO $$
DECLARE target text;
BEGIN
 FOREACH target IN ARRAY ARRAY['brand_passports','prospects','messages','drafts','tg_connections'] LOOP
  EXECUTE format('UPDATE public.%I t SET org_id=m.org_id::text FROM converza_private.legacy_workspace_map m WHERE t.org_id=m.legacy_org_id',target);
  EXECUTE format('ALTER TABLE public.%I ALTER COLUMN org_id TYPE uuid USING org_id::uuid',target);
  EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY(org_id) REFERENCES public.orgs(id) ON DELETE RESTRICT',target,target||'_canonical_org_fkey');
 END LOOP;
END $$;

-- Optional Telegram-only fields cannot prevent shared Instagram/simulated ingress.
ALTER TABLE public.prospects ALTER COLUMN tg_user_id DROP NOT NULL;
ALTER TABLE public.prospects ALTER COLUMN tg_chat_id DROP NOT NULL;
CREATE UNIQUE INDEX prospects_canonical_platform_identity
 ON public.prospects(org_id,platform,external_id);

NOTIFY pgrst, 'reload schema';
