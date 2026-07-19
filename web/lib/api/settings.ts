import { authHeaders } from "@/lib/api/session";
import { getCurrentOrgId } from "@/lib/org";
import type { PaywallStatus, PlanId } from "@/lib/settings";

export interface WorkspaceSettings {
  id: string;
  org_id: string;
  owner_user_id: string;
  brand_name: string | null;
  owner_name: string | null;
  owner_role: string | null;
  tone: string | null;
  target_audience: string | null;
  core_offer: string | null;
  target_location: string | null;
  channels_requested: string[];
  paywall_status: PaywallStatus;
  selected_plan: PlanId | null;
  updated_at?: string | null;
}

export type WorkspaceSettingsUpdate = Partial<
  Pick<
    WorkspaceSettings,
    | "owner_name"
    | "owner_role"
    | "brand_name"
    | "tone"
    | "target_audience"
    | "core_offer"
    | "target_location"
  >
>;

export interface AgentMemoryRow {
  id: string;
  agent_slug: string;
  role: string;
  content: string;
  created_at: string;
}

async function apiJson<T>(path: string, init?: RequestInit) {
  const headers = await authHeaders({
    "Content-Type": "application/json",
    ...(init?.headers ?? {}),
  });
  const response = await fetch(`/api/backend${path}`, { ...init, headers });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return payload as T;
}

export async function fetchWorkspaceSettings(orgId = getCurrentOrgId()) {
  const payload = await apiJson<{ settings: WorkspaceSettings }>(`/api/settings/${orgId}`);
  return payload.settings;
}

export async function updateWorkspaceSettings(
  updates: WorkspaceSettingsUpdate,
  expectedUpdatedAt: string,
  orgId = getCurrentOrgId(),
) {
  const payload = await apiJson<{ settings: WorkspaceSettings }>("/api/settings", {
    method: "PATCH",
    body: JSON.stringify({ org_id: orgId, updates, expected_updated_at: expectedUpdatedAt }),
  });
  return payload.settings;
}

export async function fetchAgentMemory(orgId = getCurrentOrgId()) {
  const payload = await apiJson<{ memory: AgentMemoryRow[] }>(
    `/api/settings/${orgId}/memory`,
  );
  return payload.memory;
}
