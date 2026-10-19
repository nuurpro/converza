-- Disposable PostgreSQL test database only. Not a production base-schema migration.
DO $$ BEGIN CREATE ROLE anon; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS orgs (id uuid PRIMARY KEY DEFAULT gen_random_uuid());
CREATE TABLE IF NOT EXISTS brand_passports (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 brand_name text, tone text, updated_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS drafts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
 status text, agent_slug text, prospect_id uuid, inbound_text text, final_content text, draft_content text,
 resolved_at timestamptz, delivered_at timestamptz, delivery_receipt jsonb
);
