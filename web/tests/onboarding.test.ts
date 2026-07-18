import test from "node:test";
import assert from "node:assert/strict";
import { buildAnalysis } from "../lib/onboarding.ts";
import { getDashboardGateDestination, isPublicAppRoute } from "../lib/access.ts";
import { privacyPolicy } from "../lib/legal/privacy.ts";
import { getFooterLinkHref, publicDocuments } from "../lib/legal/documents.ts";
import { BACKEND_UNAVAILABLE_DETAIL } from "../lib/api/errors.ts";
import { getCurrentOrgId, setCurrentOrgId } from "../lib/org.ts";
import { getWorkspaceNavItems } from "../lib/data/workspace.ts";

test("authenticated passport org replaces stale browser org id", () => {
  const values = new Map<string, string>();
  const localStorage = {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  };
  Object.defineProperty(globalThis, "window", {
    value: { localStorage },
    configurable: true,
  });

  setCurrentOrgId("org-from-passport", "user-1");

  assert.equal(getCurrentOrgId("user-1"), "org-from-passport");
  delete (globalThis as { window?: unknown }).window;
});

test("connect channels is settings-only, not daily sidebar navigation", () => {
  const channels = getWorkspaceNavItems().find((item) => item.id === "channels");
  assert.equal(channels, undefined);
});

test("offline backend errors explain how to restore onboarding", () => {
  assert.equal(
    BACKEND_UNAVAILABLE_DETAIL,
    "Backend service is offline. Start FastAPI on port 8000, then try again.",
  );
});

test("privacy policy is public and contains the complete dated policy", () => {
  assert.equal(isPublicAppRoute("/privacy"), true);
  assert.equal(privacyPolicy.lastUpdated, "13.07.2026");
  assert.equal(privacyPolicy.sections.length, 8);
  assert.deepEqual(
    privacyPolicy.sections.map((section) => section.title),
    [
      "Information We Collect",
      "How We Use Information",
      "Third-Party Services",
      "Data Retention",
      "Your Rights",
      "International Data",
      "Changes to This Policy",
      "Contact",
    ],
  );
  assert.match(privacyPolicy.sections[0].content.join(" "), /Payment information/);
  assert.match(privacyPolicy.sections[0].content.join(" "), /Connected account data/);
  assert.match(privacyPolicy.sections[1].content.join(" "), /personalized to your business/);
});

test("every landing footer section resolves to a public document route", () => {
  const expectedRoutes = {
    "Privacy Policy": "/privacy",
    "Terms of Service": "/terms",
    Legal: "/legal",
    Contact: "/contact",
    Socials: "/socials",
  } as const;

  for (const [label, route] of Object.entries(expectedRoutes)) {
    assert.equal(getFooterLinkHref(label), route);
    assert.equal(isPublicAppRoute(route), true);
  }
});

test("provided terms, legal, contact, and social content is complete", () => {
  assert.equal(publicDocuments.terms.lastUpdated, "13.07.2026");
  assert.equal(publicDocuments.terms.sections.length, 12);
  assert.match(publicDocuments.terms.sections[1].content.join(" "), /staged for your review/);
  assert.match(publicDocuments.legal.sections[0].content.join(" "), /formal business registration/);
  assert.match(publicDocuments.contact.sections[0].content.join(" "), /\+998 77 177 78 10/);
  assert.deepEqual(
    publicDocuments.socials.sections.map((section) => section.title),
    ["Telegram", "Instagram", "X"],
  );
  assert.equal(publicDocuments.socials.sections[0].links?.[0].href, "https://t.me/converza_ai");
});

test("branch A ghost town handles zero volume without lead-loss copy", () => {
  const analysis = buildAnalysis({
    business_name: "Ghost Town Brand",
    current_marketing_handler: "nobody",
    current_reply_handler: "me",
    weekly_message_volume: 0,
    primary_pain_point: "Nobody knows we exist yet",
    primary_goal: "more leads",
  });

  const visibleCopy = renderAnalysisCopy(analysis);

  assert.equal(analysis.branch, "ghost-town");
  assert.match(analysis.headline, /nothing is creating demand yet/);
  assert.match(analysis.detail, /Nobody knows we exist yet/);
  assert.match(analysis.before, /No content going out, no leads coming in/);
  assert.match(analysis.after, /Milo drafts real marketing content/);
  assert.match(analysis.after, /Vea turns your best ideas into real video ads/);
  assert.match(analysis.after, /nothing publishes without your click/);
  assert.equal(analysis.cta, "See plans built for getting your first leads");
  assert.doesNotMatch(visibleCopy, /Every one of those is a lead/);
  assert.doesNotMatch(visibleCopy, /21x/);
});

test("branch B founder trap uses only the permitted 21x research stat", () => {
  const analysis = buildAnalysis({
    business_name: "Founder Trap Brand",
    current_marketing_handler: "me",
    current_reply_handler: "me",
    weekly_message_volume: 58,
    primary_pain_point: "Leads wait until morning",
    primary_goal: "faster replies",
  });

  const visibleCopy = renderAnalysisCopy(analysis);

  assert.equal(analysis.branch, "founder-trap");
  assert.match(analysis.headline, /58 messages a week/);
  assert.match(analysis.detail, /Harvard Business Review and MIT research/);
  assert.match(analysis.detail, /21x more likely to qualify/);
  assert.match(analysis.after, /Sleyz drafts a reply/);
  assert.match(analysis.after, /You review and approve it before it sends/);
  assert.equal(analysis.cta, "See plans built for faster replies");
  assert.doesNotMatch(visibleCopy, /autonomous publishing/i);
  assert.doesNotMatch(visibleCopy, /checkout link/i);
  assert.doesNotMatch(visibleCopy, /sub-second/i);
});

test("branch C bleeding cash uses real spend math against the Enterprise Pilot plan", () => {
  const analysis = buildAnalysis({
    business_name: "Bleeding Cash Brand",
    current_marketing_handler: "agency-freelancer",
    current_reply_handler: "someone else",
    current_marketing_spend: 2000,
    weekly_message_volume: 37,
    primary_pain_point: "Agency is slow",
    primary_goal: "more content",
  });

  assert.equal(analysis.branch, "bleeding-cash");
  assert.equal(analysis.monthlySavings, 1500);
  assert.match(analysis.headline, /\$2,000\/month/);
  assert.match(analysis.detail, /\$500\/month/);
  assert.match(analysis.detail, /\$1,500\/month back/);
  assert.match(analysis.after, /Milo, Sleyz, and Vea produce your hooks, replies, and videos directly/);
  assert.match(analysis.after, /You review and approve/);
  assert.equal(analysis.cta, "See plans that cost less than what you're paying now");
});

test("branch D fallback reflects user answers and leaks no dollar figure", () => {
  const analysis = buildAnalysis({
    business_name: "Fallback Brand",
    current_marketing_handler: "nobody",
    current_reply_handler: "someone else",
    weekly_message_volume: 7,
    primary_pain_point: "We need more consistent content",
    primary_goal: "more content",
  });

  const visibleCopy = renderAnalysisCopy(analysis);

  assert.equal(analysis.branch, "fallback");
  assert.match(analysis.headline, /We need more consistent content/);
  assert.match(analysis.detail, /more content/);
  assert.match(analysis.after, /Milo drafts real marketing hooks/);
  assert.match(analysis.after, /Sleyz drafts real DM replies/);
  assert.match(analysis.after, /Vea renders real video/);
  assert.match(analysis.after, /You review and approve/);
  assert.equal(analysis.cta, "See plans");
  assert.doesNotMatch(visibleCopy, /\$\d/);
  assert.doesNotMatch(visibleCopy, /\d+\/month/);
  assert.doesNotMatch(visibleCopy, /90%|300%|400%/);
});

test("dashboard gate redirects each Phase A state correctly", () => {
  assert.equal(getDashboardGateDestination(null, null), "/landing");
  assert.equal(
    getDashboardGateDestination("user-1", {
      id: "passport-1",
      org_id: "org-1",
      owner_user_id: "user-1",
      paywall_status: "pending",
      onboarding_completed_at: null,
    }),
    "/onboarding",
  );
  assert.equal(
    getDashboardGateDestination("user-1", {
      id: "passport-1",
      org_id: "org-1",
      owner_user_id: "user-1",
      paywall_status: "pending",
      onboarding_completed_at: "2026-07-08T00:00:00Z",
    }),
    "/onboarding/reveal",
  );
  assert.equal(
    getDashboardGateDestination("user-1", {
      id: "passport-1",
      org_id: "org-1",
      owner_user_id: "user-1",
      paywall_status: "stub_completed",
      onboarding_completed_at: "2026-07-08T00:00:00Z",
    }),
    "allow",
  );
});

function renderAnalysisCopy(analysis: ReturnType<typeof buildAnalysis>) {
  return [
    analysis.headline,
    analysis.detail,
    analysis.goalNote,
    analysis.before,
    analysis.after,
    analysis.cta,
  ].join(" ");
}
