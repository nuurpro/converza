ALTER TABLE brand_passports
  ADD COLUMN IF NOT EXISTS owner_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS onboarding_answers jsonb DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS current_marketing_handler text,
  ADD COLUMN IF NOT EXISTS current_marketing_spend numeric,
  ADD COLUMN IF NOT EXISTS current_reply_handler text,
  ADD COLUMN IF NOT EXISTS weekly_message_volume int,
  ADD COLUMN IF NOT EXISTS primary_pain_point text,
  ADD COLUMN IF NOT EXISTS primary_goal text,
  ADD COLUMN IF NOT EXISTS channels_requested text[],
  ADD COLUMN IF NOT EXISTS owner_name text,
  ADD COLUMN IF NOT EXISTS owner_contact text,
  ADD COLUMN IF NOT EXISTS onboarding_completed_at timestamptz,
  ADD COLUMN IF NOT EXISTS paywall_status text DEFAULT 'pending'
    CHECK (paywall_status IN ('pending', 'stub_completed', 'paid'));

CREATE INDEX IF NOT EXISTS idx_brand_passports_owner_user_id
  ON brand_passports(owner_user_id);
