-- Durable storyboard editing and pending-run outbox. No production data backfill.
ALTER TABLE brand_passports ADD COLUMN IF NOT EXISTS negative_visual_constraints jsonb NOT NULL DEFAULT '[]';
CREATE TABLE IF NOT EXISTS milo_director_documents (
 org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 campaign_id uuid NOT NULL REFERENCES milo_campaigns(id) ON DELETE CASCADE,
 version bigint NOT NULL DEFAULT 0,
 document jsonb NOT NULL,
 PRIMARY KEY(org_id,campaign_id)
);
ALTER TABLE milo_director_documents ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON milo_director_documents FROM anon,authenticated;
GRANT ALL ON milo_director_documents TO service_role;

CREATE OR REPLACE FUNCTION milo_director_documents(p_action text,p_args jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE o uuid; c uuid; current_row milo_director_documents; j milo_jobs; active_run milo_director_runs; progress jsonb;
BEGIN
 IF p_action='pending' THEN
  RETURN coalesce((SELECT jsonb_agg(jsonb_build_object('org_id',org_id,'campaign_id',campaign_id)||document)
   FROM milo_director_documents WHERE document->>'pending_start'='true'),'[]'::jsonb);
 END IF;
 o:=(p_args->>'org')::uuid;
 IF p_action='handoff' THEN
  SELECT * INTO j FROM milo_jobs WHERE id=(p_args->>'job')::uuid AND org_id=o FOR UPDATE;
  IF NOT FOUND OR j.status<>'leased' OR j.lease_token::text IS DISTINCT FROM p_args->>'token'
     OR j.lease_until IS NULL OR j.lease_until<=clock_timestamp() THEN
   RAISE EXCEPTION 'workflow_conflict';
  END IF;
  UPDATE milo_jobs SET status='completed',lease_until=NULL WHERE id=j.id;
  UPDATE milo_campaigns SET build_status='running',updated_at=now() WHERE id=j.campaign_id AND org_id=o;
  RETURN '{}'::jsonb;
 END IF;
 c:=(p_args->>'campaign')::uuid;
 IF NOT EXISTS(SELECT 1 FROM milo_campaigns WHERE id=c AND org_id=o) THEN RAISE EXCEPTION 'workflow_conflict'; END IF;
 IF p_action='get' THEN RETURN (SELECT to_jsonb(d) FROM milo_director_documents d WHERE org_id=o AND campaign_id=c); END IF;
 IF p_action<>'commit' THEN RAISE EXCEPTION 'Unknown director document operation'; END IF;
 -- Same lock order as run commits: no old scene can promote after an edit commits.
 PERFORM workflow_lock(o);
 PERFORM pg_advisory_xact_lock(hashtextextended(o::text||c::text,16));
 SELECT * INTO current_row FROM milo_director_documents WHERE org_id=o AND campaign_id=c FOR UPDATE;
 IF coalesce(current_row.version,-1)<>(p_args->>'expected_version')::bigint THEN RETURN NULL; END IF;
 IF current_row.document->'storyboard'->>'revision' IS DISTINCT FROM p_args->'document'->'storyboard'->>'revision' THEN
  FOR active_run IN SELECT * FROM milo_director_runs WHERE org_id=o AND campaign_id=c AND superseded_by IS NULL FOR UPDATE LOOP
   progress:=jsonb_build_object('id',gen_random_uuid(),'run_id',active_run.id,'state','REVISION_PENDING',
     'storyboard_revision',p_args->'document'->'storyboard'->'revision','scene_count',jsonb_array_length(p_args->'document'->'storyboard'->'scenes'),
     'scene_index',active_run.document->'scene_index','attempt',0,'message','Storyboard changed; previous production fenced');
   UPDATE milo_director_runs SET version=version+1,document=document||jsonb_build_object('version',version+1,
      'document_fenced',true,'state','REVISION_PENDING','progress',(document->'progress')||jsonb_build_array(progress)) WHERE id=active_run.id;
   UPDATE drafts SET director_artifact=coalesce(director_artifact,'{}')||jsonb_build_object('superseded',true,
      'superseded_storyboard_revision',p_args->'document'->'storyboard'->'revision'),updated_at=clock_timestamp()
    WHERE org_id=o AND id=(active_run.document->>'draft_id')::uuid;
   INSERT INTO agent_run_steps(id,agent_run_id,org_id,agent_slug,step_label,step_status,detail)
    VALUES((progress->>'id')::uuid,active_run.id,o,'milo','REVISION_PENDING','completed',progress::text);
  END LOOP;
 END IF;
 INSERT INTO milo_director_documents(org_id,campaign_id,version,document)
 VALUES(o,c,coalesce(current_row.version,-1)+1,p_args->'document')
 ON CONFLICT(org_id,campaign_id) DO UPDATE SET version=excluded.version,document=excluded.document;
 RETURN '{}'::jsonb;
END $$;
REVOKE ALL ON FUNCTION milo_director_documents(text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION milo_director_documents(text,jsonb) TO service_role;

-- Bind the initial narration sign-off in the SAME transaction as campaign approval.
CREATE OR REPLACE FUNCTION milo_director_bind_initial_build() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE d milo_director_documents; approved jsonb; directed jsonb;
BEGIN
 IF NEW.kind<>'build' OR NEW.payload ? 'variant_id' THEN RETURN NEW; END IF;
 PERFORM workflow_lock(NEW.org_id);
 SELECT * INTO d FROM milo_director_documents WHERE org_id=NEW.org_id AND campaign_id=NEW.campaign_id FOR UPDATE;
 IF NOT FOUND THEN RETURN NEW; END IF;
 SELECT jsonb_agg(jsonb_build_object('spoken_narration',s->>'spoken_narration','on_screen_text',s->>'on_screen_text') ORDER BY n)
  INTO approved FROM jsonb_array_elements(NEW.payload->'video_script') WITH ORDINALITY a(s,n);
 SELECT jsonb_agg(jsonb_build_object('spoken_narration',s->>'narration_chunk','on_screen_text',s->'overlay_text'->>'text') ORDER BY n)
  INTO directed FROM jsonb_array_elements(d.document->'storyboard'->'scenes') WITH ORDINALITY a(s,n);
 IF approved IS NULL OR approved IS DISTINCT FROM directed THEN RAISE EXCEPTION 'workflow_conflict: storyboard changed before sign-off'; END IF;
 UPDATE milo_director_documents SET version=version+1,
  document=jsonb_set(document,'{storyboard,narration_approved}','true'::jsonb)||jsonb_build_object(
   'pending_start',true,'campaign_revision',(NEW.payload->>'script_revision')::bigint+1)
 WHERE org_id=NEW.org_id AND campaign_id=NEW.campaign_id;
 NEW.payload:=NEW.payload||jsonb_build_object('director_storyboard_revision',d.document->'storyboard'->'revision');
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS milo_director_bind_initial_build ON milo_jobs;
CREATE TRIGGER milo_director_bind_initial_build BEFORE INSERT ON milo_jobs FOR EACH ROW EXECUTE FUNCTION milo_director_bind_initial_build();
REVOKE ALL ON FUNCTION milo_director_bind_initial_build() FROM PUBLIC,anon,authenticated;
