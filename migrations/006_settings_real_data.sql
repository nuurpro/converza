ALTER TABLE brand_passports
  ADD COLUMN IF NOT EXISTS owner_role text,
  ADD COLUMN IF NOT EXISTS selected_plan text
    CHECK (selected_plan IN ('basic', 'pilot', 'operating-system'));
