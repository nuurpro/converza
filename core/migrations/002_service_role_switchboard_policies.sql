DROP POLICY IF EXISTS "service role full access" ON agent_runs;
CREATE POLICY "service role full access" ON agent_runs
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service role full access" ON agent_run_steps;
CREATE POLICY "service role full access" ON agent_run_steps
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service role full access" ON squad_messages;
CREATE POLICY "service role full access" ON squad_messages
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "service role full access" ON agent_memory;
CREATE POLICY "service role full access" ON agent_memory
  FOR ALL TO service_role USING (true) WITH CHECK (true);
