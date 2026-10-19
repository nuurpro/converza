-- Additive, trigger-driven organization memory. Apply before 005; draft JSON reads tolerate new columns.
ALTER TABLE brand_passports ADD COLUMN IF NOT EXISTS voice_rules jsonb NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS negative_constraints jsonb NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS brand_products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (length(trim(name)) > 0), description text NOT NULL DEFAULT '',
  price numeric CHECK(price >= 0 AND price != 'NaN'::numeric), currency text NOT NULL DEFAULT 'USD' CHECK(currency ~ '^[A-Z]{3}$'),
  metadata jsonb NOT NULL DEFAULT '{}', revision bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE TABLE IF NOT EXISTS brand_knowledge (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  kind text NOT NULL DEFAULT 'manual' CHECK(kind IN ('manual','faq')), title text NOT NULL DEFAULT '',
  content text NOT NULL CHECK(length(trim(content)) > 0), revision bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE TABLE IF NOT EXISTS memory_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK(kind IN ('passport','product','faq','manual','objection')),
  external_id text NOT NULL, title text NOT NULL, content text NOT NULL, metadata jsonb NOT NULL DEFAULT '{}',
  revision bigint NOT NULL DEFAULT 1, indexed_revision bigint, summary text NOT NULL DEFAULT '', atoms jsonb NOT NULL DEFAULT '[]',
  indexing_status text NOT NULL DEFAULT 'pending' CHECK(indexing_status IN ('pending','processing','ready','failed','deleted')),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz, forgotten_at timestamptz,
  UNIQUE(org_id,kind,external_id)
);
CREATE TABLE IF NOT EXISTS memory_source_revisions (
  source_id uuid NOT NULL REFERENCES memory_sources(id) ON DELETE CASCADE, revision bigint NOT NULL,
  org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE, kind text NOT NULL, title text NOT NULL,
  content text NOT NULL, metadata jsonb NOT NULL, updated_at timestamptz NOT NULL, deleted_at timestamptz,
  PRIMARY KEY(source_id,revision)
);
CREATE TABLE IF NOT EXISTS memory_index_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  source_id uuid NOT NULL, source_revision bigint NOT NULL, status text NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending','leased','completed','failed','obsolete')),
  attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
  lease_until timestamptz, lease_token uuid, last_error text, created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
  UNIQUE(source_id,source_revision),
  FOREIGN KEY(source_id,source_revision) REFERENCES memory_source_revisions(source_id,revision) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS memory_price_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  product_id uuid NOT NULL, price numeric NOT NULL, currency text NOT NULL, recorded_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(org_id,product_id,price,currency)
);
CREATE INDEX IF NOT EXISTS memory_sources_org_current ON memory_sources(org_id,updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS memory_jobs_claim ON memory_index_jobs(available_at,created_at) WHERE status IN ('pending','leased');

CREATE OR REPLACE FUNCTION memory_stamp_record() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW.org_id IS DISTINCT FROM OLD.org_id THEN RAISE EXCEPTION 'organization is immutable'; END IF;
  IF TG_OP = 'UPDATE' THEN NEW.revision := OLD.revision+1; ELSE NEW.revision := 1; END IF;
  NEW.updated_at := clock_timestamp();
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS memory_product_stamp ON brand_products;
CREATE TRIGGER memory_product_stamp BEFORE INSERT OR UPDATE ON brand_products FOR EACH ROW EXECUTE FUNCTION memory_stamp_record();
DROP TRIGGER IF EXISTS memory_knowledge_stamp ON brand_knowledge;
CREATE TRIGGER memory_knowledge_stamp BEFORE INSERT OR UPDATE ON brand_knowledge FOR EACH ROW EXECUTE FUNCTION memory_stamp_record();

CREATE OR REPLACE FUNCTION memory_stamp_passport() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.org_id IS DISTINCT FROM OLD.org_id THEN RAISE EXCEPTION 'organization is immutable'; END IF;
  NEW.updated_at:=clock_timestamp();
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS memory_passport_stamp ON brand_passports;
CREATE TRIGGER memory_passport_stamp BEFORE UPDATE ON brand_passports FOR EACH ROW EXECUTE FUNCTION memory_stamp_passport();

CREATE OR REPLACE FUNCTION memory_capture(p_org uuid,p_kind text,p_external text,p_title text,p_content text,p_metadata jsonb,p_deleted boolean DEFAULT false,p_updated_at timestamptz DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s memory_sources;
BEGIN
  -- Writers for a single source serialize revision creation, including first insert.
  PERFORM pg_advisory_xact_lock(hashtextextended(p_org::text||p_kind||p_external,0));
  SELECT * INTO s FROM memory_sources WHERE org_id=p_org AND kind=p_kind AND external_id=p_external FOR UPDATE;
  IF FOUND AND s.forgotten_at IS NOT NULL THEN RETURN s.id; END IF;
  IF FOUND AND s.title=p_title AND s.content=p_content AND s.metadata=p_metadata AND (s.deleted_at IS NOT NULL)=p_deleted THEN RETURN s.id; END IF;
  INSERT INTO memory_sources(org_id,kind,external_id,title,content,metadata,deleted_at,indexing_status,updated_at)
    VALUES(p_org,p_kind,p_external,p_title,p_content,p_metadata,CASE WHEN p_deleted THEN clock_timestamp() END,CASE WHEN p_deleted THEN 'deleted' ELSE 'pending' END,coalesce(p_updated_at,clock_timestamp()))
    ON CONFLICT(org_id,kind,external_id) DO UPDATE SET title=excluded.title,content=excluded.content,metadata=excluded.metadata,
      revision=memory_sources.revision+1,summary='',atoms='[]',indexed_revision=NULL,updated_at=excluded.updated_at,
      deleted_at=excluded.deleted_at,indexing_status=excluded.indexing_status RETURNING * INTO s;
  INSERT INTO memory_source_revisions(source_id,revision,org_id,kind,title,content,metadata,updated_at,deleted_at)
    VALUES(s.id,s.revision,s.org_id,s.kind,s.title,s.content,s.metadata,s.updated_at,s.deleted_at);
  UPDATE memory_index_jobs SET status='obsolete',lease_until=NULL,lease_token=NULL,completed_at=clock_timestamp()
    WHERE source_id=s.id AND status IN ('pending','leased','failed') AND source_revision<s.revision;
  IF NOT p_deleted THEN INSERT INTO memory_index_jobs(org_id,source_id,source_revision) VALUES(p_org,s.id,s.revision) ON CONFLICT DO NOTHING; END IF;
  RETURN s.id;
END $$;

CREATE OR REPLACE FUNCTION memory_capture_passport_fields(p_org uuid,p_id text,p_record jsonb,p_deleted boolean,p_updated_at timestamptz)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE field text; value jsonb; gone boolean; source_kind text; tier jsonb; amount text[];
BEGIN
  FOREACH field IN ARRAY ARRAY['faq','pricing','objections'] LOOP
    value:=p_record->field;
    gone:=p_deleted OR value IS NULL OR value IN ('null'::jsonb,'[]'::jsonb,'{}'::jsonb,'""'::jsonb);
    source_kind:=CASE WHEN field='faq' THEN 'faq' ELSE 'manual' END;
    IF NOT gone OR EXISTS(SELECT 1 FROM memory_sources WHERE org_id=p_org AND kind=source_kind AND external_id='passport:'||p_id||':'||field) THEN
      PERFORM memory_capture(p_org,source_kind,'passport:'||p_id||':'||field,
        'Passport '||field,CASE WHEN gone THEN '' ELSE field||E'\n'||value::text END,
        jsonb_build_object('passport_id',p_id,'source_field',field,'origin','passport','unverified_history',field='objections'),gone,p_updated_at);
    END IF;
    -- Existing Telegram onboarding stores textual prices, e.g. "$100/mo".
    -- Keep all numeric claims for suppression in historical retrieval after a revision.
    IF field='pricing' AND NOT gone AND jsonb_typeof(value)='array' THEN
      FOR tier IN SELECT * FROM jsonb_array_elements(value) LOOP
        FOR amount IN SELECT regexp_matches(replace(coalesce(tier->>'price',''),',',''),'[0-9]+(?:\.[0-9]+)?','g') LOOP
          INSERT INTO memory_price_history(org_id,product_id,price,currency) VALUES(p_org,p_id::uuid,amount[1]::numeric,'LEGACY') ON CONFLICT DO NOTHING;
        END LOOP;
      END LOOP;
    END IF;
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION memory_sync_record() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE r jsonb; prior jsonb; k text; deleted boolean; body text; metadata jsonb; eligible boolean;
BEGIN
  IF TG_OP='DELETE' THEN r:=to_jsonb(OLD); ELSE r:=to_jsonb(NEW); END IF;
  -- Parent-org cascade already removes every memory row. Do not resurrect children.
  IF NOT EXISTS(SELECT 1 FROM orgs WHERE id=(r->>'org_id')::uuid) THEN RETURN NULL; END IF;
  deleted := TG_OP='DELETE' OR (r->>'deleted_at') IS NOT NULL;
  IF TG_TABLE_NAME='brand_products' THEN
    k:='product';
    body:=coalesce(r->>'name','')||E'\n'||coalesce(r->>'description','')||E'\nCurrent price: '||coalesce(r->>'price','not specified')||' '||coalesce(r->>'currency','');
    metadata:=r-'updated_at'-'revision'-'created_at';
    IF r->>'price' IS NOT NULL THEN
      INSERT INTO memory_price_history(org_id,product_id,price,currency) VALUES((r->>'org_id')::uuid,(r->>'id')::uuid,(r->>'price')::numeric,r->>'currency') ON CONFLICT DO NOTHING;
    END IF;
  ELSIF TG_TABLE_NAME='brand_passports' THEN
    k:='passport'; metadata:=r-'updated_at'-'created_at'; body:=metadata::text;
  ELSIF TG_TABLE_NAME='brand_knowledge' THEN
    k:=r->>'kind'; metadata:='{}'; body:=r->>'content';
    IF TG_OP='UPDATE' AND OLD.kind<>NEW.kind THEN
      PERFORM memory_capture(OLD.org_id,OLD.kind,OLD.id::text,OLD.title,OLD.content,'{}',true);
    END IF;
  ELSIF TG_TABLE_NAME='drafts' THEN
    k:='objection';
    eligible:=(r->>'status'='PUBLISHED' AND r->>'agent_slug'='sleyz' AND r->>'prospect_id' IS NOT NULL AND r->>'resolved_at' IS NOT NULL AND r->>'delivered_at' IS NOT NULL AND r->>'delivery_receipt' IS NOT NULL);
    IF NOT coalesce(eligible,false) THEN
      IF EXISTS(SELECT 1 FROM memory_sources WHERE org_id=(r->>'org_id')::uuid AND kind=k AND external_id=r->>'id') THEN deleted:=true; ELSE RETURN NULL; END IF;
    END IF;
    body:=coalesce(r->>'inbound_text','')||E'\n'||coalesce(r->>'final_content',r->>'draft_content','');
    metadata:=jsonb_build_object('status',r->>'status','inbound_text',r->>'inbound_text','final_content',coalesce(r->>'final_content',r->>'draft_content'),
      'resolved_at',r->>'resolved_at','delivered_at',r->>'delivered_at','draft_id',r->>'id','agent_slug',r->>'agent_slug','prospect_id',r->>'prospect_id');
  ELSE RAISE EXCEPTION 'unsupported memory source'; END IF;
  PERFORM memory_capture((r->>'org_id')::uuid,k,r->>'id',coalesce(r->>'title',r->>'name',r->>'brand_name',k),body,metadata,deleted,coalesce((r->>'updated_at')::timestamptz,(r->>'resolved_at')::timestamptz,clock_timestamp()));
  IF TG_TABLE_NAME='brand_passports' THEN
    PERFORM memory_capture_passport_fields((r->>'org_id')::uuid,r->>'id',r,deleted,coalesce((r->>'updated_at')::timestamptz,clock_timestamp()));
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS memory_product_sync ON brand_products;
CREATE TRIGGER memory_product_sync AFTER INSERT OR UPDATE OR DELETE ON brand_products FOR EACH ROW EXECUTE FUNCTION memory_sync_record();
DROP TRIGGER IF EXISTS memory_passport_sync ON brand_passports;
CREATE TRIGGER memory_passport_sync AFTER INSERT OR UPDATE OR DELETE ON brand_passports FOR EACH ROW EXECUTE FUNCTION memory_sync_record();
DROP TRIGGER IF EXISTS memory_knowledge_sync ON brand_knowledge;
CREATE TRIGGER memory_knowledge_sync AFTER INSERT OR UPDATE OR DELETE ON brand_knowledge FOR EACH ROW EXECUTE FUNCTION memory_sync_record();
DROP TRIGGER IF EXISTS memory_draft_sync ON drafts;
CREATE TRIGGER memory_draft_sync AFTER INSERT OR UPDATE OR DELETE ON drafts FOR EACH ROW EXECUTE FUNCTION memory_sync_record();

CREATE OR REPLACE FUNCTION memory_claim_jobs(p_limit integer DEFAULT 1,p_lease_seconds integer DEFAULT 120)
RETURNS SETOF memory_index_jobs LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE expired record;
BEGIN
  -- Exhausted crash recovery follows the same source->job lock order as capture/completion.
  FOR expired IN SELECT s.id source_id,j.id job_id FROM memory_sources s JOIN memory_index_jobs j ON j.source_id=s.id AND j.source_revision=s.revision
      WHERE j.status='leased' AND j.lease_until<clock_timestamp() AND j.attempts>=5 AND s.deleted_at IS NULL FOR UPDATE OF s SKIP LOCKED LOOP
    UPDATE memory_index_jobs SET status='failed',last_error=coalesce(last_error,'worker lease expired after maximum attempts'),lease_token=NULL,lease_until=NULL
      WHERE id=expired.job_id AND status='leased' AND lease_until<clock_timestamp() AND attempts>=5;
    IF FOUND THEN UPDATE memory_sources SET indexing_status='failed' WHERE id=expired.source_id; END IF;
  END LOOP;
  RETURN QUERY WITH claimed AS (
    SELECT j.id FROM memory_index_jobs j JOIN memory_sources s ON s.id=j.source_id AND s.revision=j.source_revision
    WHERE s.deleted_at IS NULL AND j.attempts<5 AND
      ((j.status='pending' AND j.available_at<=clock_timestamp()) OR (j.status='leased' AND j.lease_until<clock_timestamp()))
    ORDER BY j.available_at,j.created_at FOR UPDATE OF j SKIP LOCKED LIMIT greatest(1,least(p_limit,100))
  ) UPDATE memory_index_jobs j SET status='leased',attempts=attempts+1,lease_token=gen_random_uuid(),
      lease_until=clock_timestamp()+make_interval(secs=>greatest(10,least(p_lease_seconds,3600)))
    FROM claimed WHERE j.id=claimed.id RETURNING j.*;
END $$;

CREATE OR REPLACE FUNCTION memory_complete_job(p_job uuid,p_token uuid,p_summary text,p_atoms jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j memory_index_jobs; s memory_sources;
BEGIN
  -- Lock source first, matching capture's source->job lock order.
  SELECT s0.* INTO s FROM memory_sources s0 JOIN memory_index_jobs j0 ON j0.source_id=s0.id WHERE j0.id=p_job FOR UPDATE OF s0;
  SELECT * INTO j FROM memory_index_jobs WHERE id=p_job FOR UPDATE;
  IF NOT FOUND OR j.status<>'leased' OR j.lease_token IS DISTINCT FROM p_token OR j.lease_until<=clock_timestamp() THEN RETURN false; END IF;
  IF s.revision<>j.source_revision OR s.deleted_at IS NOT NULL THEN
    UPDATE memory_index_jobs SET status='obsolete',completed_at=clock_timestamp(),lease_token=NULL,lease_until=NULL WHERE id=p_job; RETURN false;
  END IF;
  UPDATE memory_sources SET summary=p_summary,atoms=p_atoms,indexed_revision=revision,indexing_status='ready' WHERE id=s.id;
  UPDATE memory_index_jobs SET status='completed',completed_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,last_error=NULL WHERE id=p_job;
  RETURN true;
END $$;

CREATE OR REPLACE FUNCTION memory_fail_job(p_job uuid,p_token uuid,p_error text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE j memory_index_jobs; s memory_sources;
BEGIN
  SELECT s0.* INTO s FROM memory_sources s0 JOIN memory_index_jobs j0 ON j0.source_id=s0.id WHERE j0.id=p_job FOR UPDATE OF s0;
  SELECT * INTO j FROM memory_index_jobs WHERE id=p_job FOR UPDATE;
  IF NOT FOUND OR j.status<>'leased' OR j.lease_token IS DISTINCT FROM p_token OR j.lease_until<=clock_timestamp() THEN RETURN false; END IF;
  UPDATE memory_index_jobs SET status=CASE WHEN attempts>=5 THEN 'failed' ELSE 'pending' END,
    available_at=clock_timestamp()+make_interval(secs=>least(3600,power(2,attempts)::int*5)),
    lease_token=NULL,lease_until=NULL,last_error=left(p_error,2000) WHERE id=p_job;
  UPDATE memory_sources SET indexing_status=CASE WHEN j.attempts>=5 THEN 'failed' ELSE 'pending' END WHERE id=j.source_id AND revision=j.source_revision AND deleted_at IS NULL;
  RETURN true;
END $$;

CREATE OR REPLACE FUNCTION memory_retry_job(p_org uuid,p_job uuid) RETURNS SETOF memory_index_jobs
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
  PERFORM 1 FROM memory_sources s JOIN memory_index_jobs j ON j.source_id=s.id
    WHERE j.id=p_job AND j.org_id=p_org AND s.org_id=p_org FOR UPDATE OF s;
  RETURN QUERY UPDATE memory_index_jobs j SET status='pending',attempts=0,available_at=clock_timestamp(),last_error=NULL,lease_until=NULL,lease_token=NULL
    FROM memory_sources s WHERE j.id=p_job AND j.org_id=p_org AND j.status='failed' AND s.id=j.source_id AND s.org_id=p_org AND s.revision=j.source_revision AND s.deleted_at IS NULL RETURNING j.*;
  UPDATE memory_sources s SET indexing_status='pending' FROM memory_index_jobs j WHERE j.id=p_job AND j.org_id=p_org AND j.status='pending' AND s.id=j.source_id AND s.revision=j.source_revision;
END $$;

CREATE OR REPLACE FUNCTION memory_forget(p_org uuid,p_kind text,p_id uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
  IF p_kind='product' THEN UPDATE brand_products SET deleted_at=clock_timestamp() WHERE org_id=p_org AND id=p_id AND deleted_at IS NULL;
  ELSIF p_kind='knowledge' THEN UPDATE brand_knowledge SET deleted_at=clock_timestamp() WHERE org_id=p_org AND id=p_id AND deleted_at IS NULL;
  ELSE RAISE EXCEPTION 'unsupported source kind'; END IF;
  RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION memory_forget_source(p_org uuid,p_source uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s memory_sources;
BEGIN
  SELECT * INTO s FROM memory_sources WHERE org_id=p_org AND id=p_source;
  IF NOT FOUND OR s.deleted_at IS NOT NULL THEN RETURN false; END IF;
  IF s.kind='passport' THEN RAISE EXCEPTION 'identity cannot be forgotten';
  ELSIF s.kind='product' THEN RETURN memory_forget(p_org,'product',s.external_id::uuid);
  ELSIF s.kind IN ('faq','manual') AND s.metadata->>'origin' IS DISTINCT FROM 'passport' THEN RETURN memory_forget(p_org,'knowledge',s.external_id::uuid);
  END IF;
  -- Match capture's advisory->source lock order; canonical deletions above lock their row first.
  PERFORM pg_advisory_xact_lock(hashtextextended(p_org::text||s.kind||s.external_id,0));
  SELECT * INTO s FROM memory_sources WHERE org_id=p_org AND id=p_source FOR UPDATE;
  IF s.deleted_at IS NOT NULL THEN RETURN false; END IF;
  PERFORM memory_capture(p_org,s.kind,s.external_id,s.title,s.content,s.metadata,true);
  UPDATE memory_sources SET forgotten_at=clock_timestamp() WHERE id=s.id;
  RETURN true;
END $$;

-- Idempotent backfill includes facts/identity only. Historical approval is never resolution.
CREATE OR REPLACE FUNCTION memory_backfill(p_org uuid DEFAULT NULL) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE n integer:=0; r record;
BEGIN
  FOR r IN SELECT * FROM brand_passports WHERE p_org IS NULL OR org_id=p_org LOOP
    PERFORM memory_capture(r.org_id,'passport',r.id::text,coalesce(to_jsonb(r)->>'brand_name','passport'),(to_jsonb(r)-'updated_at'-'created_at')::text,to_jsonb(r)-'updated_at'-'created_at',false,r.updated_at); n:=n+1;
    PERFORM memory_capture_passport_fields(r.org_id,r.id::text,to_jsonb(r),false,r.updated_at);
  END LOOP;
  FOR r IN SELECT * FROM brand_products WHERE (p_org IS NULL OR org_id=p_org) AND deleted_at IS NULL LOOP
    PERFORM memory_capture(r.org_id,'product',r.id::text,r.name,r.name||E'\n'||r.description||E'\nCurrent price: '||coalesce(r.price::text,'not specified')||' '||r.currency,to_jsonb(r)-'updated_at'-'revision'-'created_at',false,r.updated_at);
    IF r.price IS NOT NULL THEN INSERT INTO memory_price_history(org_id,product_id,price,currency) VALUES(r.org_id,r.id,r.price,r.currency) ON CONFLICT DO NOTHING; END IF;
    n:=n+1;
  END LOOP;
  FOR r IN SELECT * FROM brand_knowledge WHERE (p_org IS NULL OR org_id=p_org) AND deleted_at IS NULL LOOP
    PERFORM memory_capture(r.org_id,r.kind,r.id::text,r.title,r.content,'{}',false,r.updated_at); n:=n+1;
  END LOOP;
  RETURN n;
END $$;

-- Browser access goes through authenticated backend org authorization. RPCs are service-only.
ALTER TABLE brand_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE brand_knowledge ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_source_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_index_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_price_history ENABLE ROW LEVEL SECURITY;
DO $$ DECLARE t text; f record; BEGIN
  FOREACH t IN ARRAY ARRAY['brand_products','brand_knowledge','memory_sources','memory_source_revisions','memory_index_jobs','memory_price_history'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS memory_service_role ON %I',t);
    EXECUTE format('CREATE POLICY memory_service_role ON %I FOR ALL TO service_role USING (true) WITH CHECK (true)',t);
    EXECUTE format('GRANT ALL ON %I TO service_role',t);
  END LOOP;
  FOR f IN SELECT oid::regprocedure signature FROM pg_proc WHERE pronamespace='public'::regnamespace AND proname LIKE 'memory_%' LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated',f.signature);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role',f.signature);
  END LOOP;
END $$;
