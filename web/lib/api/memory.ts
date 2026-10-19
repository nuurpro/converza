import { authHeaders } from "@/lib/api/session";
import { getCurrentOrgId } from "@/lib/org";

export interface IdentityCore {
  org_id: string; revision: number; passport: Record<string, unknown>;
  exports: Record<string, string>;
}
export interface ProductRecord {
  id: string; name: string; description: string; price: string; currency: string;
  metadata: Record<string, unknown>; updated_at?: string;
}
export interface KnowledgeRecord {
  id: string; source_id?: string; kind: string; title: string; content: string;
  summary?: string; revision: number; updated_at?: string;
  read_only?: boolean;
  atoms?: {objection?: string; answer?: string; text?: string; resolved_at?: string}[];
}
export interface IndexJob { id: string; status: string; error?: string; last_error?: string; source_id: string; }

export async function memoryRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = await authHeaders({"Content-Type":"application/json"});
  const response = await fetch(`/api/backend/api/memory/${encodeURIComponent(getCurrentOrgId())}${path}`, {...init,headers,cache:"no-store"});
  const payload = await response.json().catch(()=>null);
  if (!response.ok) throw new Error(typeof payload?.detail === "string" ? payload.detail : `Request failed (${response.status})`);
  return payload as T;
}

export async function downloadIdentity(filename: string) {
  const response = await fetch(`/api/backend/api/memory/${encodeURIComponent(getCurrentOrgId())}/identity/export/${encodeURIComponent(filename)}`, {headers:await authHeaders()});
  if (!response.ok) throw new Error("Identity export failed");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url; link.download = filename; link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
