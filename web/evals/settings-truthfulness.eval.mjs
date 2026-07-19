import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

function source(path) {
  return readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
}

const pages = {
  connections: source("app/settings/connections/page.tsx"),
  profile: source("app/settings/profile/page.tsx"),
  brand: source("app/settings/brand/page.tsx"),
  billing: source("app/settings/billing/page.tsx"),
  memory: source("app/settings/memory/page.tsx"),
  tokens: source("app/settings/tokens/page.tsx"),
};

test("settings pages contain no fabricated customer records", () => {
  const allSettings = Object.values(pages).join("\n");
  for (const forbidden of [
    /Nodir Ergashxojaev/,
    /nodir@converza\.ai/,
    /Osman Skincare/,
    /Co-Pilot/,
    /BudgetBrain/,
    /Production swarm/,
    /Webhook ingestion/,
    /INV-\d+/,
    /tk_live_/,
  ]) {
    assert.doesNotMatch(allSettings, forbidden);
  }
});

test("connections never present unavailable services as connected", () => {
  assert.doesNotMatch(pages.connections, /Connected/);
  assert.match(pages.connections, /Coming soon/);
  assert.match(pages.connections, />\s*Connect\s*</);
});

test("truthful settings pages are wired to real data or explicit empty states", () => {
  assert.match(pages.profile, /fetchWorkspaceSettings/);
  assert.match(pages.brand, /fetchWorkspaceSettings/);
  assert.match(pages.billing, /fetchWorkspaceSettings/);
  assert.match(pages.memory, /fetchAgentMemory/);
  assert.match(pages.tokens, /No API tokens yet/);
});
