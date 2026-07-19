# Real Settings Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace fabricated settings content with authenticated Supabase data and honest unavailable states.

**Architecture:** Add one org-owned settings repository and three FastAPI routes for workspace settings and memory. The Next.js settings pages consume those routes through the existing protected proxy; connection, payment, token, and research capabilities remain explicitly unavailable unless a real backing system exists.

**Tech Stack:** FastAPI, Pydantic, Supabase/PostgREST, Next.js App Router, React, TypeScript, Tailwind CSS, Node test runner, Python unittest.

---

## File Map

- Create `migrations/006_settings_real_data.sql`: optional owner role and selected plan fields.
- Create `lib/settings_repository.py`: Brand Passport settings and memory persistence boundary.
- Create `tests/test_settings_data.py`: backend contract, ownership, update, and context-refresh tests.
- Modify `main.py`: settings request models and authenticated routes; persist selected plan.
- Create `web/lib/api/settings.ts`: typed settings and memory API client.
- Create `web/lib/settings.ts`: deterministic billing status and agent-label formatting.
- Modify `web/lib/api/onboarding.ts`: submit selected plan during stub completion.
- Modify `web/app/onboarding/paywall/page.tsx`: pass selected plan.
- Create `web/app/settings/connections/page.tsx`: merged honest connection catalog.
- Modify `web/app/settings/channels/page.tsx`: redirect compatibility route.
- Modify `web/app/settings/integrations/page.tsx`: redirect compatibility route.
- Modify `web/app/settings/layout.tsx`: one Connections navigation entry.
- Modify `web/app/settings/profile/page.tsx`: authenticated profile form.
- Modify `web/app/settings/brand/page.tsx`: persisted Brand Passport form.
- Modify `web/app/settings/audience/page.tsx`: persisted audience form and honest research notice.
- Modify `web/app/settings/billing/page.tsx`: real plan/paywall state only.
- Modify `web/app/settings/memory/page.tsx`: real org memory or empty state.
- Modify `web/app/settings/tokens/page.tsx`: honest empty state.
- Create `web/tests/settings-data.test.ts`: deterministic UI/data contracts.
- Create `web/evals/settings-truthfulness.eval.mjs`: source-level anti-fabrication eval.

### Task 1: Remove False Connection Claims

**Files:**
- Create: `web/app/settings/connections/page.tsx`
- Modify: `web/app/settings/channels/page.tsx`
- Modify: `web/app/settings/integrations/page.tsx`
- Modify: `web/app/settings/layout.tsx`
- Test: `web/tests/settings-data.test.ts`

- [ ] **Step 1: Write the failing connection truthfulness test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const connections = readFileSync(
  new URL("../app/settings/connections/page.tsx", import.meta.url),
  "utf8",
);
const settingsLayout = readFileSync(
  new URL("../app/settings/layout.tsx", import.meta.url),
  "utf8",
);

test("connections never claim an unverified service is connected", () => {
  assert.doesNotMatch(connections, /Connected/);
  assert.match(connections, /Communication Channels/);
  assert.match(connections, /Data Integrations/);
  assert.match(connections, /Coming soon/);
  assert.match(connections, />Connect</);
});

test("settings navigation exposes one connections destination", () => {
  assert.match(settingsLayout, /href: "\/settings\/connections"/);
  assert.doesNotMatch(settingsLayout, /href: "\/settings\/(?:channels|integrations)"/);
});
```

- [ ] **Step 2: Run the test and verify the missing merged page fails**

Run: `cd web && node --test tests/settings-data.test.ts`

Expected: FAIL because `app/settings/connections/page.tsx` does not exist.

- [ ] **Step 3: Build the merged page and compatibility redirects**

Use static arrays with these exact states:

```tsx
const communicationChannels = [
  ["Telegram", "Customer conversations through Telegram Business"],
  ["Instagram DM", "Customer conversations from Instagram"],
  ["TikTok", "Customer conversations from TikTok"],
  ["WhatsApp", "Customer conversations through WhatsApp Business"],
  ["Website chat", "Customer conversations from your website"],
];

const dataIntegrations = [
  ["Shopify", "Catalog, orders, and customer events"],
  ["Meta Ads", "Facebook and Instagram campaign data"],
  ["TikTok Ads", "Campaign and creative performance data"],
  ["GA4", "Website analytics and attribution"],
  ["Klaviyo", "Email and SMS lifecycle data"],
  ["Stripe", "Revenue and refund signals"],
  ["Slack", "Approval notifications and summaries"],
  ["Google Ads", "Search and campaign performance data"],
];
```

Communication rows render a neutral `Coming soon` label. Data rows render a `Connect` button that opens an inline notice: `This connector is not available yet.` It must not mutate row state.

Replace both old pages with:

```tsx
import { redirect } from "next/navigation";

export default function ConnectionsRedirect() {
  redirect("/settings/connections");
}
```

Replace the two settings navigation entries with:

```ts
{
  id: "connections",
  label: "Connections",
  href: "/settings/connections",
  icon: Plug,
  hint: "Channels and agent data sources",
}
```

- [ ] **Step 4: Run the test and verify Tier 0 passes**

Run: `cd web && node --test tests/settings-data.test.ts`

Expected: PASS with two tests.

- [ ] **Step 5: Commit Tier 0 independently**

```bash
git add web/app/settings/connections/page.tsx web/app/settings/channels/page.tsx web/app/settings/integrations/page.tsx web/app/settings/layout.tsx web/tests/settings-data.test.ts
git commit -m "fix-honest-connections-settings"
```

### Task 2: Add Real Settings Persistence Boundary

**Files:**
- Create: `migrations/006_settings_real_data.sql`
- Create: `lib/settings_repository.py`
- Test: `tests/test_settings_data.py`

- [ ] **Step 1: Write repository round-trip tests**

Create a fake Supabase table/query that records `.update()` payloads and filters. Add these tests:

```python
def test_settings_repository_reads_owned_passport():
    repo = SettingsRepository(fake_client_with_passport())
    passport = repo.get_passport("org-1")
    assert passport["brand_name"] == "Northstar"


def test_settings_repository_updates_only_supplied_fields():
    client = fake_client_with_passport()
    repo = SettingsRepository(client)
    updated = repo.update_passport("org-1", {"tone": "direct, warm"})
    assert updated["tone"] == "direct, warm"
    assert client.last_update == {"tone": "direct, warm"}


def test_settings_repository_returns_real_memory_rows():
    repo = SettingsRepository(fake_client_with_memory())
    rows = repo.get_memory("org-1")
    assert [row["agent_slug"] for row in rows] == ["milo", "sleyz"]
```

- [ ] **Step 2: Run the repository tests and verify import failure**

Run: `python -m unittest tests.test_settings_data`

Expected: FAIL with `ModuleNotFoundError: lib.settings_repository`.

- [ ] **Step 3: Add the migration**

```sql
ALTER TABLE brand_passports
  ADD COLUMN IF NOT EXISTS owner_role text,
  ADD COLUMN IF NOT EXISTS selected_plan text
    CHECK (selected_plan IN ('basic', 'pilot', 'operating-system'));
```

- [ ] **Step 4: Implement `SettingsRepository`**

```python
from datetime import datetime, timezone
from typing import Any


class SettingsRepository:
    def __init__(self, client: Any) -> None:
        self.client = client

    def get_passport(self, org_id: str) -> dict[str, Any] | None:
        result = (
            self.client.table("brand_passports")
            .select("id,org_id,owner_user_id,brand_name,owner_name,owner_role,tone,target_audience,core_offer,target_location,channels_requested,paywall_status,selected_plan")
            .eq("org_id", org_id)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def update_passport(self, org_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        payload = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
        result = self.client.table("brand_passports").update(payload).eq("org_id", org_id).execute()
        if not result.data:
            raise KeyError(org_id)
        return result.data[0]

    def get_memory(self, org_id: str) -> list[dict[str, Any]]:
        result = (
            self.client.table("agent_memory")
            .select("id,agent_slug,role,content,created_at")
            .eq("org_id", org_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
```

- [ ] **Step 5: Run repository tests**

Run: `python -m unittest tests.test_settings_data`

Expected: PASS for repository tests.

- [ ] **Step 6: Commit schema and repository**

```bash
git add migrations/006_settings_real_data.sql lib/settings_repository.py tests/test_settings_data.py
git commit -m "add-real-settings-storage"
```

### Task 3: Add Authenticated Settings APIs

**Files:**
- Modify: `main.py`
- Modify: `tests/test_settings_data.py`

- [ ] **Step 1: Write failing API contract and ownership tests**

```python
def test_settings_update_rejects_unknown_fields():
    with self.assertRaises(HTTPException) as raised:
        main._validate_settings_updates({"fake_subscription": "active"})
    self.assertEqual(raised.exception.status_code, 400)


def test_settings_update_rejects_blank_required_brand_fields():
    with self.assertRaises(HTTPException):
        main._validate_settings_updates({"tone": "   "})


def test_owned_settings_route_updates_passport():
    auth = main.AuthContext(user_id="user-1")
    request = main.WorkspaceSettingsUpdateRequest(org_id="org-1", updates={"owner_role": "Founder"})
    with patch.object(main, "_assert_user_owns_org") as ownership, patch.object(
        main, "get_settings_repo", return_value=fake_repo
    ):
        result = asyncio.run(main.update_workspace_settings(request, auth))
    ownership.assert_called_once_with("user-1", "org-1")
    self.assertEqual(result["settings"]["owner_role"], "Founder")
```

- [ ] **Step 2: Run tests and verify missing API helpers fail**

Run: `python -m unittest tests.test_settings_data`

Expected: FAIL because `_validate_settings_updates`, `get_settings_repo`, and route functions do not exist.

- [ ] **Step 3: Add request models, validation, and routes**

Add:

```python
SETTINGS_UPDATE_FIELDS = {
    "owner_name",
    "owner_role",
    "brand_name",
    "tone",
    "target_audience",
    "core_offer",
    "target_location",
}
REQUIRED_SETTINGS_FIELDS = {
    "owner_name",
    "brand_name",
    "tone",
    "target_audience",
    "core_offer",
    "target_location",
}


class WorkspaceSettingsUpdateRequest(BaseModel):
    org_id: str
    updates: dict[str, Any]


def get_settings_repo() -> SettingsRepository:
    return SettingsRepository(get_supabase())


def _validate_settings_updates(updates: dict[str, Any]) -> dict[str, Any]:
    unknown = set(updates) - SETTINGS_UPDATE_FIELDS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported settings fields: {', '.join(sorted(unknown))}")
    cleaned = dict(updates)
    for key in REQUIRED_SETTINGS_FIELDS & set(cleaned):
        if not isinstance(cleaned[key], str) or not cleaned[key].strip():
            raise HTTPException(status_code=400, detail=f"{key} cannot be blank")
        cleaned[key] = cleaned[key].strip()
    if "owner_role" in cleaned and isinstance(cleaned["owner_role"], str):
        cleaned["owner_role"] = cleaned["owner_role"].strip() or None
    return cleaned
```

Add protected routes:

```python
@app.get("/api/settings/{org_id}")
async def get_workspace_settings(org_id: str, auth: AuthContext = Depends(require_authenticated_user)):
    _assert_user_owns_org(auth.user_id, org_id)
    settings = get_settings_repo().get_passport(org_id)
    if not settings:
        raise HTTPException(status_code=404, detail="Brand Passport not found")
    return {"settings": settings}


@app.patch("/api/settings")
async def update_workspace_settings(
    request: WorkspaceSettingsUpdateRequest,
    auth: AuthContext = Depends(require_authenticated_user),
):
    _assert_user_owns_org(auth.user_id, request.org_id)
    settings = get_settings_repo().update_passport(
        request.org_id,
        _validate_settings_updates(request.updates),
    )
    return {"settings": settings}


@app.get("/api/settings/{org_id}/memory")
async def get_workspace_memory(org_id: str, auth: AuthContext = Depends(require_authenticated_user)):
    _assert_user_owns_org(auth.user_id, org_id)
    return {"memory": get_settings_repo().get_memory(org_id)}
```

Translate missing `owner_role` or `selected_plan` schema errors into a `503` response naming migration `006_settings_real_data.sql`.

- [ ] **Step 4: Prove agent context reloads changed Brand Passport data**

Add a repository-backed test that updates `tone`, then calls `assemble_context` with the same org and asserts `context["brand_passport"]["tone"]` equals the new value. Do not mock `assemble_context`; use a fake repository whose `get_brand_passport` reads the mutable fake table.

- [ ] **Step 5: Run backend tests**

Run: `python -m unittest tests.test_settings_data tests.test_security_ownership tests.test_backend_switchboard`

Expected: PASS.

- [ ] **Step 6: Commit backend routes**

```bash
git add main.py tests/test_settings_data.py
git commit -m "add-authenticated-settings-api"
```

### Task 4: Build the Typed Frontend Data Layer

**Files:**
- Create: `web/lib/api/settings.ts`
- Create: `web/lib/settings.ts`
- Modify: `web/tests/settings-data.test.ts`

- [ ] **Step 1: Write failing deterministic formatter tests**

```ts
import { billingStatusCopy, agentName } from "../lib/settings.ts";

test("billing status copy never promotes test access to payment", () => {
  assert.equal(billingStatusCopy("stub_completed"), "Testing access enabled — no payment recorded");
  assert.equal(billingStatusCopy("pending"), "Invoice pending");
  assert.equal(billingStatusCopy("paid"), "Paid manually");
});

test("memory exposes only the real three-agent roster", () => {
  assert.equal(agentName("milo"), "Milo");
  assert.equal(agentName("sleyz"), "Sleyz");
  assert.equal(agentName("vea"), "Vea");
  assert.equal(agentName("budgetbrain"), "Unknown agent");
});
```

- [ ] **Step 2: Run test and verify imports fail**

Run: `cd web && node --test tests/settings-data.test.ts`

Expected: FAIL because `lib/settings.ts` does not exist.

- [ ] **Step 3: Implement types, formatters, and proxy calls**

`web/lib/settings.ts`:

```ts
export type PaywallStatus = "pending" | "stub_completed" | "paid";

export function billingStatusCopy(status: PaywallStatus) {
  if (status === "paid") return "Paid manually";
  if (status === "stub_completed") return "Testing access enabled — no payment recorded";
  return "Invoice pending";
}

export function agentName(slug: string) {
  return { milo: "Milo", sleyz: "Sleyz", vea: "Vea" }[slug] ?? "Unknown agent";
}
```

`web/lib/api/settings.ts` defines `WorkspaceSettings`, `AgentMemoryRow`, `fetchWorkspaceSettings`, `updateWorkspaceSettings`, and `fetchAgentMemory`. Each uses `authHeaders`, `/api/backend`, and `getCurrentOrgId`, matching the existing API modules.

- [ ] **Step 4: Run frontend tests**

Run: `cd web && node --test tests/settings-data.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit frontend data layer**

```bash
git add web/lib/api/settings.ts web/lib/settings.ts web/tests/settings-data.test.ts
git commit -m "add-settings-data-client"
```

### Task 5: Bind Profile, Brand Passport, and Audience

**Files:**
- Modify: `web/app/settings/profile/page.tsx`
- Modify: `web/app/settings/brand/page.tsx`
- Modify: `web/app/settings/audience/page.tsx`
- Modify: `web/tests/settings-data.test.ts`

- [ ] **Step 1: Add source-contract tests that reject sample data**

Read the three page sources and assert:

```ts
assert.doesNotMatch(profileSource, /Nodir Ergashxojaev|nodir@converza\.ai|12 minutes ago/);
assert.doesNotMatch(brandSource, /Osman Skincare|3 products in 1 bottle/);
assert.match(profileSource, /fetchWorkspaceSettings/);
assert.match(profileSource, /getSupabaseBrowserClient/);
assert.match(brandSource, /updateWorkspaceSettings/);
assert.match(audienceSource, /Audience research is not available yet/);
```

- [ ] **Step 2: Run test and verify sample-data assertions fail**

Run: `cd web && node --test tests/settings-data.test.ts`

Expected: FAIL on the current hardcoded profile and brand values.

- [ ] **Step 3: Replace Profile with real load/save state**

On mount, fetch settings and `supabase.auth.getUser()` concurrently. Populate owner name, owner role, and session email. Save with:

```ts
const saved = await updateWorkspaceSettings({ owner_name: name, owner_role: role || null });
setName(saved.owner_name || "");
setRole(saved.owner_role || "");
setSaveState("saved");
```

Derive initials from the loaded name. Remove upload/remove avatar controls and fake last-saved text.

- [ ] **Step 4: Replace Brand Passport with structured fields**

Load `brand_name`, `tone`, `target_audience`, `core_offer`, and `target_location`. Save only those fields. On successful brand-name save, update `converza.brandName` and dispatch `converza:brand-name-updated` so the sidebar changes immediately.

- [ ] **Step 5: Replace Target Audience with one persisted field**

Load and save `target_audience`. Add this fixed notice below the form:

```text
Audience research is not available yet.
We will add researched audience evidence only after a real research source is connected. No generated audience claims are shown here.
```

- [ ] **Step 6: Run frontend tests and build**

Run: `cd web && node --test tests/settings-data.test.ts && npm run build`

Expected: tests PASS and Next build exits 0.

- [ ] **Step 7: Commit the real forms**

```bash
git add web/app/settings/profile/page.tsx web/app/settings/brand/page.tsx web/app/settings/audience/page.tsx web/tests/settings-data.test.ts
git commit -m "bind-real-profile-and-brand-settings"
```

### Task 6: Persist and Display Real Billing State

**Files:**
- Modify: `main.py`
- Modify: `web/lib/api/onboarding.ts`
- Modify: `web/app/onboarding/paywall/page.tsx`
- Modify: `web/app/settings/billing/page.tsx`
- Modify: `tests/test_settings_data.py`
- Modify: `web/tests/settings-data.test.ts`

- [ ] **Step 1: Write failing selected-plan persistence tests**

Backend test:

```python
def test_stub_completion_stores_selected_plan_without_claiming_payment():
    updates = main._stub_payment_updates("pilot")
    self.assertEqual(updates, {"paywall_status": "stub_completed", "selected_plan": "pilot"})
```

Frontend source tests assert Billing imports `billingStatusCopy` and contains none of `INV-`, `Payment method`, `Ads generated`, or `Free forever`.

- [ ] **Step 2: Run tests and verify failures**

Run: `python -m unittest tests.test_settings_data`

Run: `cd web && node --test tests/settings-data.test.ts`

Expected: both fail because plan persistence and real Billing do not exist.

- [ ] **Step 3: Persist selected plan during test checkout**

Extend the onboarding action request with `selected_plan: str | None = None`. Validate against `{"basic", "pilot", "operating-system"}`. Update stub completion with both fields. Change:

```ts
completeStubPayment(ownerUserId, selectedPlan)
```

and send `selected_plan` in the request body.

- [ ] **Step 4: Replace Billing with real status only**

Fetch workspace settings. Resolve plan names from the existing `PRICING_TIERS`; show `No plan selected` if null. Show `billingStatusCopy(paywall_status)`. Remove all invoice, usage, payment method, and fake plan-feature UI.

- [ ] **Step 5: Run backend and frontend tests**

Run: `python -m unittest tests.test_settings_data`

Run: `cd web && node --test tests/settings-data.test.ts && npm run build`

Expected: PASS and build exit 0.

- [ ] **Step 6: Commit billing truthfulness**

```bash
git add main.py tests/test_settings_data.py web/lib/api/onboarding.ts web/app/onboarding/paywall/page.tsx web/app/settings/billing/page.tsx web/tests/settings-data.test.ts
git commit -m "bind-real-billing-state"
```

### Task 7: Replace Memory and Token Fabrication

**Files:**
- Modify: `web/app/settings/memory/page.tsx`
- Modify: `web/app/settings/tokens/page.tsx`
- Modify: `web/tests/settings-data.test.ts`

- [ ] **Step 1: Write failing anti-fabrication tests**

```ts
assert.doesNotMatch(memorySource, /Co-Pilot|BudgetBrain|\$200\/day|@askar\.io/);
assert.match(memorySource, /No memory yet/);
assert.match(memorySource, /fetchAgentMemory/);
assert.doesNotMatch(tokensSource, /Production swarm|Webhook ingestion|tk_live_|lastUsed/);
assert.match(tokensSource, /No API tokens yet/);
assert.match(tokensSource, /Secure token creation is not available yet/);
```

- [ ] **Step 2: Run test and verify fabricated examples fail**

Run: `cd web && node --test tests/settings-data.test.ts`

Expected: FAIL on existing fake memory and token strings.

- [ ] **Step 3: Bind Agent Memory**

Fetch real rows, format only known agent slugs, and display content, role, and actual creation date. Empty response renders exactly `No memory yet - this fills in as your agents work.` Remove Forget and Wipe controls because no deletion endpoint exists.

- [ ] **Step 4: Build the honest token empty state**

The New token button toggles one local explanatory panel containing `Secure token creation is not available yet.` It must not create token-like text, dates, reveal controls, copy controls, or revoke controls.

- [ ] **Step 5: Run frontend tests and build**

Run: `cd web && node --test tests/settings-data.test.ts && npm run build`

Expected: PASS and build exit 0.

- [ ] **Step 6: Commit honest empty states**

```bash
git add web/app/settings/memory/page.tsx web/app/settings/tokens/page.tsx web/tests/settings-data.test.ts
git commit -m "remove-fake-memory-and-token-data"
```

### Task 8: Add Eval and Verify the Real Round Trip

**Files:**
- Create: `web/evals/settings-truthfulness.eval.mjs`
- Modify: `web/package.json`

- [ ] **Step 1: Add the truthfulness eval**

The eval reads all settings page sources and fails if it finds:

```js
const forbidden = [
  /Connected/,
  /Nodir Ergashxojaev/,
  /Osman Skincare/,
  /Co-Pilot/,
  /BudgetBrain/,
  /Production swarm/,
  /Webhook ingestion/,
  /INV-\d+/,
  /tk_live_/,
];
```

Scope the `Connected` check to `settings/connections/page.tsx` so explanatory legal copy elsewhere is unaffected. Add `"eval:settings": "node --test evals/settings-truthfulness.eval.mjs"`.

- [ ] **Step 2: Run all gate tests and evals**

Run: `python -m unittest tests.test_settings_data tests.test_security_ownership tests.test_backend_switchboard tests.test_marketing_calendar`

Run: `python -m compileall -q main.py lib tests`

Run: `cd web && node --test tests/onboarding.test.ts tests/marketing-calendar.test.mjs tests/settings-data.test.ts`

Run: `cd web && npm run eval:settings && npm run eval:onboarding-backend && npm run build`

Expected: every command exits 0.

- [ ] **Step 3: Apply migration to the configured Supabase test project**

Print `migrations/006_settings_real_data.sql`, then run it through the project's established Supabase migration process. Do not expose keys in logs.

Expected: `owner_role` and `selected_plan` appear in the PostgREST schema after cache refresh.

- [ ] **Step 4: Verify Profile edit and reload**

Using the authenticated test account, change Role to `Founder`, save, reload `/settings/profile`, and confirm the field still reads `Founder`.

- [ ] **Step 5: Verify Brand Passport tone through Milo**

Record the current tone. Change it to `concise, formal, evidence-led`, save, reload, and confirm persistence. Send Milo: `Write one short campaign hook for our current offer. Follow the Brand Passport tone.` Confirm the backend run assembles the edited tone and the response is concise and formal. Restore the original tone and confirm the restore after reload.

- [ ] **Step 6: Verify remaining real states**

Confirm Target Audience equals the Brand Passport structured column. Confirm Billing matches `selected_plan` and `paywall_status`. Compare Agent Memory rows in the UI with the backend response for the same org, or confirm both are empty. Confirm Connections has no Connected labels and Tokens has no token-like values.

- [ ] **Step 7: Commit eval and final verification hooks**

```bash
git add web/evals/settings-truthfulness.eval.mjs web/package.json
git commit -m "add-settings-truthfulness-eval"
```

- [ ] **Step 8: Final repository checks**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors and no uncommitted implementation files.
