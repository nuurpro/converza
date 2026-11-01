-- Additive, service-only onboarding transaction. Apply separately in production.
CREATE OR REPLACE FUNCTION public.workspace_save_passport(
  p_owner uuid, p_expected_org uuid, p_payload jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  current_passport public.brand_passports%ROWTYPE;
  incoming public.brand_passports%ROWTYPE;
  passport_count integer;
  workspace_id uuid;
BEGIN
  IF p_owner IS NULL OR NOT EXISTS (SELECT 1 FROM auth.users WHERE id=p_owner) THEN
    RAISE EXCEPTION 'workspace_ownership_invalid_owner';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('workspace:' || p_owner::text, 0));
  SELECT count(*) INTO passport_count FROM public.brand_passports WHERE owner_user_id=p_owner;
  IF passport_count > 1 THEN RAISE EXCEPTION 'workspace_ownership_ambiguous'; END IF;
  SELECT * INTO current_passport FROM public.brand_passports WHERE owner_user_id=p_owner FOR UPDATE;
  IF FOUND THEN
    workspace_id := current_passport.org_id;
    IF workspace_id IS NULL OR (p_expected_org IS NOT NULL AND workspace_id<>p_expected_org) THEN
      RAISE EXCEPTION 'workspace_ownership_unresolved';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.orgs WHERE id=workspace_id) THEN
      RAISE EXCEPTION 'workspace_ownership_missing_org';
    END IF;
  ELSE
    -- Never claim an existing unlinked passport or trust an organization supplied by a browser.
    IF p_expected_org IS NOT NULL THEN RAISE EXCEPTION 'workspace_ownership_unresolved'; END IF;
    INSERT INTO public.orgs(name,created_at) VALUES(coalesce(nullif(p_payload->>'brand_name',''), 'Untitled brand'),now()) RETURNING id INTO workspace_id;
    INSERT INTO public.brand_passports(org_id,owner_user_id,brand_name) VALUES(workspace_id,p_owner,coalesce(p_payload->>'brand_name','Untitled brand')) RETURNING * INTO current_passport;
  END IF;
  incoming := jsonb_populate_record(NULL::public.brand_passports, p_payload);
  -- Deliberately exclude identity, approval, completion, and payment fields from client updates.
  UPDATE public.brand_passports SET
    onboarding_answers=coalesce(incoming.onboarding_answers,'{}'::jsonb),
    brand_name=incoming.brand_name, industry=incoming.industry, core_offer=incoming.core_offer,
    target_audience=incoming.target_audience,target_location=incoming.target_location,
    tone=incoming.tone,hex_colors=incoming.hex_colors,
    current_marketing_handler=incoming.current_marketing_handler,
    current_marketing_spend=incoming.current_marketing_spend,
    current_reply_handler=incoming.current_reply_handler,weekly_message_volume=incoming.weekly_message_volume,
    primary_pain_point=incoming.primary_pain_point,primary_goal=incoming.primary_goal,
    channels_requested=incoming.channels_requested,owner_name=incoming.owner_name,owner_contact=incoming.owner_contact,
    updated_at=now()
    WHERE id=current_passport.id RETURNING * INTO current_passport;
  RETURN to_jsonb(current_passport);
END $$;
REVOKE ALL ON FUNCTION public.workspace_save_passport(uuid,uuid,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.workspace_save_passport(uuid,uuid,jsonb) TO service_role;
