import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const proxySource = readFileSync(
  new URL("../app/api/backend/[...path]/route.ts", import.meta.url),
  "utf8",
);
const errorSource = readFileSync(new URL("../lib/api/errors.ts", import.meta.url), "utf8");
const backendSource = readFileSync(new URL("../../main.py", import.meta.url), "utf8");
const layoutSource = readFileSync(
  new URL("../components/layout/MainLayout.tsx", import.meta.url),
  "utf8",
);
const workspaceSource = readFileSync(new URL("../lib/data/workspace.ts", import.meta.url), "utf8");
const settingsSource = readFileSync(new URL("../app/settings/layout.tsx", import.meta.url), "utf8");

test("backend proxy turns connection failures into an actionable 503", () => {
  assert.match(proxySource, /catch \(error\)/);
  assert.match(proxySource, /status: 503/);
  assert.match(proxySource, /BACKEND_UNAVAILABLE_DETAIL/);
  assert.match(errorSource, /Backend service is offline/);
  assert.match(errorSource, /port 8000/);
});

test("onboarding preserves the org foreign-key root and restores authenticated org state", () => {
  assert.match(backendSource, /def _ensure_org_exists\(org_id: str, name: str\)/);
  assert.match(backendSource, /_ensure_org_exists\(org_id, str\(payload\["brand_name"\]\)\)/);
  assert.match(layoutSource, /setCurrentOrgId\(passport\.org_id, ownerUserId\)/);
});

test("channel setup is discoverable in settings but absent from daily navigation", () => {
  assert.doesNotMatch(workspaceSource, /label: "Connect channels"/);
  assert.match(settingsSource, /label: "Channels", href: "\/settings\/channels"/);
});
