-- Destinations are hydrated by the server, never taken from HITL callback data.
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS tg_chat_id bigint;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS business_connection_id text;
ALTER TABLE tg_connections ADD COLUMN IF NOT EXISTS business_connection_id text;
CREATE INDEX IF NOT EXISTS idx_tg_connections_business_connection
  ON tg_connections(business_connection_id) WHERE business_connection_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_prospects_telegram_org ON prospects(org_id,tg_chat_id)
  WHERE tg_chat_id IS NOT NULL;
