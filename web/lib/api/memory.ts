import { authenticatedFetch } from "@/lib/api/session";
import { getCurrentOrgId } from "@/lib/org";

export interface IdentityCore {
  org_id: string; revision: number; passport: Record<string, unknown>;
  exports: Record<string, string>;
}
export interface ProductRecord {
  id: string; name: string; description: string; price: string; currency: string;
  metadata: Record<string, unknown>; updated_at?: string;
  sku?: string | null; stock_count?: number | null; checkout_url_template?: string | null; revision?: number;
}
export interface KnowledgeRecord {
  id: string; source_id?: string; kind: string; title: string; content: string;
  summary?: string; revision: number; updated_at?: string;
  read_only?: boolean;
  atoms?: {objection?: string; answer?: string; text?: string; rule?: string; resolved_at?: string; supporting_spans?: unknown[]; metadata?: Record<string,unknown>; originating_draft_id?:string; originating_revision?:number; draft_id?:string; approved_revision?:number; approved_at?:string; priority?:number}[];
  metadata?: Record<string,unknown>;
}
export interface IndexJob { id: string; status: string; error?: string; last_error?: string; source_id: string; }

export async function memoryRequest<T>(path: string, init?: RequestInit, orgId = getCurrentOrgId()): Promise<T> {
  const headers = new Headers(init?.headers);headers.set('Content-Type','application/json');
  const response = await authenticatedFetch(`/api/backend/api/memory/${encodeURIComponent(orgId)}${path}`, {...init,headers});
  const payload = await response.json().catch(()=>null);
  if (!response.ok) throw new Error(typeof payload?.detail === "string" ? payload.detail : `Request failed (${response.status})`);
  return payload as T;
}

export async function downloadIdentity(filename: string, orgId = getCurrentOrgId()) {
  const response = await authenticatedFetch(`/api/backend/api/memory/${encodeURIComponent(orgId)}/identity/export/${encodeURIComponent(filename)}`);
  if (!response.ok) throw new Error("Identity export failed");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url; link.download = filename; link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
