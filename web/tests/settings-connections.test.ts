import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function readSource(relativePath: string) {
  try {
    return readFileSync(path.join(webRoot, relativePath), "utf8");
  } catch {
    return "";
  }
}

const connectionsSource = readSource("app/settings/connections/page.tsx");
const channelsSource = readSource("app/settings/channels/page.tsx");
const integrationsSource = readSource("app/settings/integrations/page.tsx");
const layoutSource = readSource("app/settings/layout.tsx");

test("connections page combines all unavailable communication channels", () => {
  assert.match(connectionsSource, /Communication Channels/);

  for (const channel of [
    "Telegram",
    "Instagram DM",
    "TikTok",
    "WhatsApp",
    "Website chat",
  ]) {
    assert.match(connectionsSource, new RegExp(`name: ["']${channel}["']`));
  }

  assert.match(connectionsSource, /channels\.map/);
  assert.match(connectionsSource, />\s*Coming soon\s*</);
});

test("connections page offers every unavailable data connector without connected state", () => {
  assert.match(connectionsSource, /Data Integrations/);

  for (const integration of [
    "Shopify",
    "Meta Ads",
    "TikTok Ads",
    "GA4",
    "Klaviyo",
    "Stripe",
    "Slack",
    "Google Ads",
  ]) {
    assert.match(connectionsSource, new RegExp(`name: ["']${integration}["']`));
  }

  assert.match(connectionsSource, /integrations\.map/);
  assert.match(connectionsSource, />\s*Connect\s*</);
  assert.match(connectionsSource, /This connector is not available yet\./);
  assert.match(connectionsSource, /aria-label={`Connect \${integration\.name}`}/);
  assert.doesNotMatch(connectionsSource, /Connected/);
});

test("legacy pages redirect and settings navigation exposes one Connections item", () => {
  for (const legacySource of [channelsSource, integrationsSource]) {
    assert.match(legacySource, /import\s+\{\s*redirect\s*\}\s+from\s+["']next\/navigation["']/);
    assert.match(legacySource, /redirect\(["']\/settings\/connections["']\)/);
  }

  assert.match(layoutSource, /label: ["']Connections["']/);
  assert.match(layoutSource, /href: ["']\/settings\/connections["']/);
  assert.doesNotMatch(layoutSource, /href: ["']\/settings\/(channels|integrations)["']/);
  assert.match(layoutSource, /aria-current={active \? "page" : undefined}/);
  assert.match(layoutSource, /label: ["']Models["']/);
  assert.match(layoutSource, /href: ["']\/settings\/models["']/);
});
