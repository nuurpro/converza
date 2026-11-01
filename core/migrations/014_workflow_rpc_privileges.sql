-- Supabase default ACLs can directly grant EXECUTE to browser roles. Revoking
-- PUBLIC alone (005) does not remove those direct grants from definer RPCs.
REVOKE ALL ON FUNCTION public.workflow_lock(uuid), public.workflow_row_lock(),
 public.workflow_row_event(),
 public.workflow_transition(uuid,uuid,text,bigint,text,text,jsonb,text),
 public.workflow_snapshot(uuid), public.workflow_read_events(uuid,bigint,integer)
 FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.workflow_lock(uuid), public.workflow_row_lock(),
 public.workflow_row_event(),
 public.workflow_transition(uuid,uuid,text,bigint,text,text,jsonb,text),
 public.workflow_snapshot(uuid), public.workflow_read_events(uuid,bigint,integer)
 TO service_role;
NOTIFY pgrst, 'reload schema';
