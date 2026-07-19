# Real Settings Data Design

## Outcome

Every settings page either displays authenticated Supabase data or states honestly that the capability is unavailable. No setting may imply a connection, payment, token, memory, or researched insight that the live system cannot verify.

## Scope

Included:

- Merge Channels and Integrations into Connections.
- Bind Profile, Brand Passport, Target Audience, Billing, and Agent Memory to real data.
- Replace API Token examples with an honest empty state.
- Persist the selected paywall plan.
- Prove Brand Passport changes reach the next agent context.

Excluded:

- Models settings.
- Real OAuth or channel connections.
- Audience research and generated infographics.
- Real payment processing, invoices, payment methods, or usage metering.
- Secure API token generation, hashing, revocation, or usage tracking.

## Schema

Add migration `006_settings_real_data.sql`:

- `brand_passports.owner_role text` nullable.
- `brand_passports.selected_plan text` nullable with allowed values matching pricing configuration: `basic`, `pilot`, `operating-system`.

The existing `paywall_status` remains the payment-state source. No subscription table is invented.

## Backend Contract

All routes use the existing backend API key, Supabase session authentication, and `_assert_user_owns_org` check.

### Workspace settings

`GET /api/settings/{org_id}` returns only editable and displayable fields from the owned Brand Passport:

- `brand_name`
- `owner_name`
- `owner_role`
- `tone`
- `target_audience`
- `core_offer`
- `target_location`
- `channels_requested`
- `paywall_status`
- `selected_plan`

`PATCH /api/settings/{org_id}` accepts a typed partial update restricted to:

- Profile: `owner_name`, `owner_role`
- Brand: `brand_name`, `tone`, `target_audience`, `core_offer`, `target_location`

Unknown fields are rejected. Empty optional role is allowed. Required Brand Passport fields cannot be saved as blank strings.

Email is not stored or returned by this endpoint. The Profile page reads `auth.users.email` from the current Supabase browser session.

### Agent memory

`GET /api/settings/{org_id}/memory` returns real `agent_memory` rows in descending creation order. Rows expose `id`, `agent_slug`, `role`, `content`, and `created_at`. No delete endpoint is added in this scope because deletion behavior has not been requested or specified.

### Paywall selection

The existing stub-payment request receives `selected_plan` and stores it with `paywall_status = 'stub_completed'`. Billing maps status honestly:

- `pending`: invoice or plan selection pending.
- `stub_completed`: testing access enabled; no payment occurred.
- `paid`: paid manually.

## Frontend

### Connections

Create `/settings/connections` with two labeled sections:

- Communication Channels: Telegram, Instagram DM, TikTok, WhatsApp, website chat. Every row says `Coming soon`.
- Data Integrations: Shopify, Meta Ads, TikTok Ads, GA4, Klaviyo, Stripe, Slack, Google Ads. Every row offers `Connect`; clicking explains that the connector is not available yet and never marks it connected.

Settings navigation contains one Connections item. `/settings/channels` and `/settings/integrations` remain compatibility redirects, with no duplicate page implementations.

### Profile

Load owner name and role from the settings endpoint. Load email from the authenticated Supabase user. Save owner name and role through the PATCH endpoint. Replace fake timestamps and avatar controls with real save state and initials derived from the loaded owner name.

### Brand Passport

Load and edit the direct structured columns. Markets use the single existing `target_location` text field rather than inventing a list schema. Saving updates Supabase and local sidebar brand-name display. The next agent run reloads the Brand Passport through `context_assembler`, so no cache invalidation layer is needed.

### Target Audience

Load and edit only `target_audience`. Show a separate explanatory empty-state block for research: audience research is unavailable until a real research source is connected. No generated insight cards or inferred claims.

### Billing

Display only real `selected_plan` and `paywall_status`. Remove fabricated invoices, payment method, usage, and free-tier limits. Provide plain status copy and a link back to the pilot contact flow where appropriate.

### Agent Memory

Render only real rows from `agent_memory`, labeled by Milo, Sleyz, or Vea. When empty, show: `No memory yet - this fills in as your agents work.` Remove fake delete and wipe controls because no backed deletion contract exists.

### API Tokens

Show `No API tokens yet.` The New token button opens an honest notice that secure token creation is not available yet. It creates, reveals, copies, or revokes nothing.

## Error Handling

- Initial loads show an explicit loading state.
- Failed loads show the backend error and a retry action.
- Saves disable while pending and display `Saved` only after the server response returns.
- Settings pages never fall back to sample business data.
- Missing migration fields return an actionable migration message.

## Verification

Gate tests:

- No `Connected` text or connected state exists in Connections.
- Settings API rejects another user's org.
- PATCH allowlist rejects unknown fields.
- Profile and Brand Passport save/reload round trips return changed values.
- Empty memory produces the honest empty state; populated memory contains only returned rows.
- Billing status rendering covers pending, stub-completed, and paid states.
- Token examples and fake timestamps are absent.

End-to-end checks against the configured test account:

1. Edit owner role, reload Profile, and confirm persistence.
2. Edit Brand Passport tone, reload Brand Passport, and confirm persistence.
3. Send a fresh Milo request and confirm the assembled context contains the edited tone and the response follows it.
4. Confirm Target Audience displays the saved structured value.
5. Confirm Billing displays the saved plan and real paywall status.
6. Confirm Agent Memory matches the org's actual rows or displays the honest empty state.
7. Restore any temporary tone change after the production-path verification.

No real external connection, payment, token, or audience-research operation is performed by this change.
