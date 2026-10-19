import type { DraftRow } from "./workflow";

export type SleyzPlatform = "telegram" | "instagram";
export interface SleyzDraftArtifact {
  schema_version: 1;
  customer_handle: string;
  platform: SleyzPlatform;
  incoming_message: string;
  intent_score: number;
  intent: "COLD" | "WARM" | "HOT";
  detected_objection: string | null;
  cited_brand_passport_atoms: Array<{source_id: string; revision: number; atom_index?: number | null; span?: [number, number] | null}>;
  draft_reply: string;
  checkout_link: string | null;
  product_snapshot: Array<{id: string; sku: string | null; name: string; description?: string; price: string | number | null; currency: string; stock_count: number | null; revision: number; checkout_url_template?: string | null}>;
  quantity: number;
  operator_notes: string[];
}
export interface SimulationInput { platform: SleyzPlatform; customer_id: string; customer_handle?: string; text: string }
export function draftCapabilities(draft: DraftRow) {
  const active = !draft.simulated && !draft.superseded_by;
  const staleCommerce = draft.delivery_status === "failed" && /catalog|commerce|price|stock|sku|commercial|product.*chang/i.test(draft.delivery_error ?? "");
  return {
    canDeliver: active && !staleCommerce && !!draft.prospect_id && ["APPROVED", "EDITED"].includes(draft.status) && !["sending", "ambiguous", "delivered"].includes(draft.delivery_status ?? "idle"),
    canResolve: active && draft.agent_slug === "sleyz" && !!draft.prospect_id && draft.status === "PUBLISHED" && !draft.resolved_at,
    canRefresh: active && staleCommerce,
  };
}

export function simulationRequest(orgId: string, input: SimulationInput, key: string): {path: string; init: RequestInit} {
  if (!input.customer_id.trim()) throw new Error("Customer ID is required.");
  if (!input.text.trim()) throw new Error("Message is required.");
  return {path: "/api/simulate/inbound-dm", init: {
    method: "POST", headers: {"Idempotency-Key": key},
    body: JSON.stringify({org_id: orgId, platform: input.platform, customer_id: input.customer_id.trim(), customer_handle: input.customer_handle?.trim() || input.customer_id.trim(), text: input.text.trim()}),
  }};
}

export function productCommerceFields(form: {sku: string; stock_count: string; checkout_url_template: string}) {
  const stock = form.stock_count.trim() ? Number(form.stock_count) : null;
  if (stock !== null && (!Number.isSafeInteger(stock) || stock < 0)) throw new Error("Stock must be a nonnegative whole number or left blank for unknown.");
  const template = form.checkout_url_template.trim() || null;
  if (template) {
    if (/\{(?!sku\}|quantity\})[^}]*\}/.test(template)) throw new Error("Checkout supports only {sku} and {quantity} placeholders.");
    let url: URL;
    try { url = new URL(template.replaceAll("{sku}", "sku").replaceAll("{quantity}", "1")); }
    catch { throw new Error("Checkout must be a valid HTTPS URL."); }
    if (url.protocol !== "https:" || url.username || url.password) throw new Error("Checkout must be an HTTPS URL without embedded credentials.");
    if (/\{[^}]*\}/.test(new URL(template).host)) throw new Error("Checkout placeholders must appear in the URL path or query.");
  }
  return {sku: form.sku.trim() || null, stock_count: stock, checkout_url_template: template};
}

/** A status message linked to a draft must not suppress its review card. */
export function withUnlinkedDrafts<T extends {id: string; sender_slug: string; hitl_draft_id?: string | null}>(messages: T[], drafts: Record<string, DraftRow>) {
  const linked = new Set(messages.filter(row => row.hitl_draft_id && row.sender_slug === drafts[row.hitl_draft_id]?.agent_slug).map(row => row.hitl_draft_id));
  return [...messages, ...Object.values(drafts).filter(draft => !linked.has(draft.id)).map(draft => ({
    id: `draft:${draft.id}`, org_id: draft.org_id, sender_slug: draft.agent_slug,
    content: draft.simulated ? "Simulated inbound DM" : "Customer-facing draft", hitl_draft_id: draft.id, created_at: draft.created_at,
  }))];
}
