# Managed Marketing Calendar

This is the paid-workspace onboarding layer. It does not change the public signup, 15-question onboarding, reveal, or paywall flow.

## Runtime flow

1. The paid dashboard checks for the newest `marketing_calendars` row owned by the signed-in user's org.
2. With no calendar, Milo presents a seven-step constrained interview.
3. The backend writes the structured Brand Passport fields, raw literacy signals, and deterministic literacy level.
4. One Groq call creates a 14- or 30-day skeleton. Every day is persisted with `status = skeleton`.
5. Opening a skeleton day makes one bounded Milo detail-generation action. The theme must exactly match the skeleton theme.
6. Approving a drafted day calls the existing Vea switchboard path. The day becomes `rendering`, then `awaiting_hitl` when the existing Vea draft is ready.
7. The existing HITL approve/reject endpoints synchronize the calendar day to `completed` or `failed`.

No calendar state claims that a post was published. No publishing integration exists yet.

## Deterministic controls

- More than two platforms always triggers the same hard-block result.
- An explicit confirmation is required to override the two-platform recommendation.
- The override, metrics answer, current process, and selected platform count remain in `marketing_literacy_signals`.
- Literacy level is derived in `lib/marketing_calendar.py`; no model assigns it.
- Hours per week determine the film-it-yourself count. Vea renders do not consume the user's filming time.
- Generated themes cannot request testimonials or customer proof unless the Brand Passport contains proof.
- Detailed scripts reject mismatched themes, fake contact details, unsupported people, and unsupported operational/outcome claims. One correction attempt is allowed, then the run fails visibly.

## Deployment prerequisite

Run `migrations/005_managed_marketing_calendar.sql` in Supabase before deploying the frontend and backend changes. Verify read-only readiness with:

```bash
python -m scripts.check_calendar_schema
```

## Deferred own-footage path

MoneyPrinterTurbo currently receives `video_source = pexels` and has no Converza contract for raw user uploads, cut points, or caption placement. The UI therefore labels own-footage assembly unavailable instead of silently substituting stock footage.
