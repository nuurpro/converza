CREATE TABLE IF NOT EXISTS marketing_calendars (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
  duration_days int NOT NULL CHECK (duration_days IN (14, 30)),
  platforms text[] NOT NULL,
  hours_per_week numeric,
  target_video_count int,
  days jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_marketing_calendars_org_created
  ON marketing_calendars(org_id, created_at DESC);

ALTER TABLE brand_passports
  ADD COLUMN IF NOT EXISTS marketing_literacy_level text
    CHECK (marketing_literacy_level IN ('new', 'some_experience', 'experienced')),
  ADD COLUMN IF NOT EXISTS marketing_literacy_signals jsonb DEFAULT '{}';

ALTER TABLE marketing_calendars ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service role full access" ON marketing_calendars;
CREATE POLICY "service role full access" ON marketing_calendars
  FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMENT ON COLUMN marketing_calendars.days IS
  'Day objects use skeleton, draft, rendering, awaiting_hitl, completed, or failed. No published state is claimed until a real publisher exists.';
