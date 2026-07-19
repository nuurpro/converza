import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { agentName, billingStatusCopy } from "../lib/settings.ts";

test("billing status copy distinguishes test access from payment", () => {
  assert.equal(billingStatusCopy("pending"), "Invoice pending");
  assert.equal(
    billingStatusCopy("stub_completed"),
    "Testing access enabled - no payment recorded",
  );
  assert.equal(billingStatusCopy("paid"), "Paid manually");
});

test("memory labels only the real three-agent roster", () => {
  assert.equal(agentName("milo"), "Milo");
  assert.equal(agentName("sleyz"), "Sleyz");
  assert.equal(agentName("vea"), "Vea");
  assert.equal(agentName("budgetbrain"), "Unknown agent");
});

const profileSource = readFileSync(
  new URL("../app/settings/profile/page.tsx", import.meta.url),
  "utf8",
);
const brandSource = readFileSync(
  new URL("../app/settings/brand/page.tsx", import.meta.url),
  "utf8",
);
const audienceSource = readFileSync(
  new URL("../app/settings/audience/page.tsx", import.meta.url),
  "utf8",
);
const billingSource = readFileSync(
  new URL("../app/settings/billing/page.tsx", import.meta.url),
  "utf8",
);
const memorySource = readFileSync(
  new URL("../app/settings/memory/page.tsx", import.meta.url),
  "utf8",
);
const tokensSource = readFileSync(
  new URL("../app/settings/tokens/page.tsx", import.meta.url),
  "utf8",
);
const paywallSource = readFileSync(
  new URL("../app/onboarding/paywall/page.tsx", import.meta.url),
  "utf8",
);
const proxySource = readFileSync(
  new URL("../app/api/backend/[...path]/route.ts", import.meta.url),
  "utf8",
);
const brandCacheSource = readFileSync(
  new URL("../lib/brand-cache.ts", import.meta.url),
  "utf8",
);
const sidebarSource = readFileSync(
  new URL("../components/sidebar/Sidebar.tsx", import.meta.url),
  "utf8",
);
const mainLayoutSource = readFileSync(
  new URL("../components/layout/MainLayout.tsx", import.meta.url),
  "utf8",
);

test("backend proxy forwards settings PATCH requests", () => {
  assert.match(proxySource, /export async function PATCH/);
});

test("profile reads the authenticated user and persisted owner fields", () => {
  assert.doesNotMatch(profileSource, /Nodir Ergashxojaev|nodir@converza\.ai|12 minutes ago/);
  assert.match(profileSource, /fetchWorkspaceSettings/);
  assert.match(profileSource, /getSupabaseBrowserClient/);
  assert.match(profileSource, /updateWorkspaceSettings/);
});

test("brand passport edits only real structured fields", () => {
  assert.doesNotMatch(brandSource, /Osman Skincare|3 products in 1 bottle/);
  assert.match(brandSource, /fetchWorkspaceSettings/);
  assert.match(brandSource, /updateWorkspaceSettings/);
  for (const field of ["brand_name", "tone", "target_audience", "core_offer", "target_location"]) {
    assert.match(brandSource, new RegExp(field));
  }
  assert.match(brandSource, /dirtyUpdates/);
  assert.match(brandSource, /disabled=\{loading \|\| saving \|\| needsReload \|\| !orgId\}/);
});

test("brand name cache is scoped to the authenticated owner", () => {
  assert.match(brandCacheSource, /converza\.brandName\.\$\{ownerUserId\}/);
  assert.doesNotMatch(brandCacheSource, /getItem\("converza\.brandName"\)/);
  assert.match(sidebarSource, /converza:owner-user-updated/);
  assert.match(mainLayoutSource, /setActiveOwnerUserId/);
  assert.doesNotMatch(sidebarSource, />Nodir<|>Free<|Osman Skincare/);
});

test("settings forms expose retry states and accessible field hints", () => {
  for (const source of [profileSource, brandSource, audienceSource]) {
    assert.match(source, /Retry/);
    assert.match(source, /aria-describedby/);
  }
});

test("target audience persists real data and does not invent research", () => {
  assert.match(audienceSource, /fetchWorkspaceSettings/);
  assert.match(audienceSource, /updateWorkspaceSettings/);
  assert.match(audienceSource, /Audience research is not available yet/);
  assert.doesNotMatch(audienceSource, /upload|infographic|scrape/i);
});

test("billing displays only persisted plan and payment state", () => {
  assert.match(billingSource, /fetchWorkspaceSettings/);
  assert.match(billingSource, /billingStatusCopy/);
  assert.doesNotMatch(
    billingSource,
    /INV-|Payment method|Ads generated|Free forever|Campaigns shipped|Spend tracked/,
  );
});

test("paywall sends the selected plan during testing checkout", () => {
  assert.match(paywallSource, /completeStubPayment\(ownerUserId, selectedPlan\)/);
  assert.match(paywallSource, /setCheckoutError/);
  assert.doesNotMatch(paywallSource, /completeStubPayment\(ownerUserId, selectedPlan\)\.catch/);
});

test("settings saves include the loaded revision to prevent silent overwrites", () => {
  assert.match(profileSource, /expectedUpdatedAt/);
  assert.match(brandSource, /expectedUpdatedAt/);
  assert.match(audienceSource, /expectedUpdatedAt/);
  for (const source of [profileSource, brandSource, audienceSource]) {
    assert.match(source, /Reload latest/);
  }
});

test("memory renders only real agent_memory rows or an honest empty state", () => {
  assert.match(memorySource, /fetchAgentMemory/);
  assert.match(memorySource, /No memory yet/);
  assert.doesNotMatch(memorySource, /Co-Pilot|BudgetBrain|\$200\/day|@askar\.io/);
  assert.doesNotMatch(memorySource, /Wipe all memory|Forget this/);
});

test("API tokens are an honest unavailable empty state", () => {
  assert.match(tokensSource, /No API tokens yet/);
  assert.match(tokensSource, /Secure token creation is not available yet/);
  assert.doesNotMatch(tokensSource, /Production swarm|Webhook ingestion|tk_live_|lastUsed/);
  assert.doesNotMatch(tokensSource, /Reveal|Revoke|Copy token/);
});
