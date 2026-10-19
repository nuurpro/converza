import type {
  ActivityFeedItem,
  AgentId,
  DashboardStat,
  DraftStatus,
  SquadMessageData,
} from "@/lib/data/workspace";
import { workspaceTokens } from "@/lib/data/workspace";
import { authHeaders, getSupabaseAccessToken } from "@/lib/api/session";
import { getCurrentOrgId, FALLBACK_ORG_ID } from "@/lib/org";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { presentationStatus, type DraftRow, type WorkspaceEvent } from "@/lib/data/workflow";
import {subscribeWorkspaceTransport} from "@/lib/data/workspaceStream";
import { draftCapabilities, simulationRequest, type SimulationInput } from "@/lib/data/sleyz";

export const DEFAULT_ORG_ID =
  process.env.NEXT_PUBLIC_DEFAULT_ORG_ID ??
  FALLBACK_ORG_ID;

export interface AgentMessageResponse {
  run_id: string;
  agent_slug: AgentId;
  response: string;
}

export interface SquadMessageRow {
  id: string;
  org_id: string;
  sender_slug: string;
  content: string;
  mentions?: string[];
  related_run_id?: string | null;
  hitl_draft_id?: string | null;
  created_at?: string;
}

export interface AgentRunStepRow {
  id: string;
  agent_run_id: string;
  org_id: string;
  agent_slug: AgentId;
  step_label: string;
  step_status: "started" | "completed" | "failed" | string;
  detail?: string | null;
  created_at?: string;
}

export type SquadStreamEvent =
  | { type: "squad_message"; row: SquadMessageRow }
  | { type: "agent_run_step"; row: AgentRunStepRow }
  | { type: "error"; error: string };

interface SquadPostResponse {
  message: SquadMessageRow;
  routed_to: AgentId[];
}

type HitlResponse = DraftRow;

const senderMeta: Record<
  string,
  Pick<SquadMessageData, "sender" | "senderColor" | "mark" | "role">
> = {
  owner: {
    sender: "Owner",
    senderColor: workspaceTokens.black,
    mark: "N",
    role: "user",
  },
  converza: {
    sender: "Converza",
    senderColor: workspaceTokens.black,
    mark: "C",
    role: "assistant",
  },
  milo: {
    sender: "Milo",
    senderColor: workspaceTokens.milo,
    mark: "M",
    role: "assistant",
  },
  sleyz: {
    sender: "Sleyz",
    senderColor: workspaceTokens.sleyz,
    mark: "S",
    role: "assistant",
  },
  vea: {
    sender: "Vea",
    senderColor: workspaceTokens.vea,
    mark: "V",
    role: "assistant",
  },
};

const agentNames: Record<string, string> = {
  milo: "Milo",
  sleyz: "Sleyz",
  vea: "Vea",
};

const agentColors: Record<string, string> = {
  milo: workspaceTokens.milo,
  sleyz: workspaceTokens.sleyz,
  vea: workspaceTokens.vea,
  converza: workspaceTokens.black,
};

function backendPath(path: string) {
  return `/api/backend${path}`;
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : `Request failed with ${response.status}`;
    throw new Error(detail);
  }

  return payload as T;
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = await authHeaders({
    "Content-Type": "application/json",
    ...(init?.headers ?? {}),
  });
  const response = await fetch(backendPath(path), {
    ...init,
    headers,
  });
  return readJson<T>(response);
}

export async function sendAgentMessage(
  agentId: AgentId,
  text: string,
  orgId = getCurrentOrgId(),
) {
  return apiJson<AgentMessageResponse>(`/api/agent/${agentId}/message`, {
    method: "POST",
    body: JSON.stringify({ org_id: orgId, text }),
  });
}

export async function sendSquadMessage(text: string, orgId = getCurrentOrgId()) {
  return apiJson<SquadPostResponse>("/api/squad/message", {
    method: "POST",
    body: JSON.stringify({ org_id: orgId, text }),
  });
}

export async function fetchDashboardStats(orgId = getCurrentOrgId()) {
  const payload = await apiJson<{ stats: DashboardStat[] }>(
    `/api/dashboard/${orgId}/stats`,
  );
  return payload.stats;
}

export async function resolveHitlDraft(
  draftId: string,
  action: "approve" | "reject" | "edit",
  finalContent?: string,
  expectedRevision?: number,
) {
  if (!expectedRevision) throw new Error("Draft revision is missing. Refresh live state before deciding.");
  return apiJson<HitlResponse>(`/api/hitl/${draftId}/${action}`, {
    method: "POST",
    headers: {"Idempotency-Key":crypto.randomUUID()},
    body: JSON.stringify({expected_revision:expectedRevision, ...(action === "edit" ? {final_content:finalContent??""} : {})}),
  });
}

export async function createSquadEventSource(orgId = getCurrentOrgId(), cursor?: number) {
  const params = new URLSearchParams({ org_id: orgId });
  if (cursor !== undefined) params.set("cursor",String(cursor));
  const token = await getSupabaseAccessToken();
  if (token) params.set("access_token", token);
  return new EventSource(backendPath(`/api/squad/stream?${params.toString()}`));
}

export function parseSquadStreamEvent(raw: string): SquadStreamEvent | null {
  try {
    return JSON.parse(raw) as SquadStreamEvent;
  } catch {
    return null;
  }
}

export function mapSquadMessage(row: SquadMessageRow, draft?: DraftRow): SquadMessageData {
  const meta = senderMeta[row.sender_slug] ?? senderMeta.converza;
  const hitlStatus = draft ? presentationStatus(draft.status) : undefined;

  return {
    id: row.id,
    role: meta.role,
    sender: meta.sender,
    senderColor: meta.senderColor,
    mark: meta.mark,
    timestamp: formatTimestamp(row.created_at),
    text: row.content,
    hitlCard: row.hitl_draft_id && draft && hitlStatus && row.sender_slug === draft.agent_slug
      ? {
          id: row.hitl_draft_id,
          label: hitlStatus === "pending" ? "Review before use" : "Decision recorded",
          content: draft.final_content || draft.draft_content || "Generating draft…",
          status: hitlStatus,
          revision: draft.revision,
          deliveryStatus: draft.delivery_status,
          deliveryError: draft.delivery_error,
          generationError: draft.generation_error,
          resolvedAt: draft.resolved_at,
          ...draftCapabilities(draft),
          artifact: draft.sleyz_artifact,
          simulated: draft.simulated,
          supersededBy: draft.superseded_by,
          learningStatus: draft.learning_status,
          learningError: draft.learning_error,
        }
      : undefined,
  };
}

export function mapRunStepToActivity(row: AgentRunStepRow): ActivityFeedItem {
  const name = agentNames[row.agent_slug] ?? row.agent_slug;
  const status =
    row.step_status === "started"
      ? "started"
      : row.step_status === "completed"
        ? "finished"
        : row.step_status;
  const detail = row.detail ? ` — ${row.detail}` : "";

  return {
    id: row.id,
    agentId: row.agent_slug,
    color: agentColors[row.agent_slug] ?? workspaceTokens.black,
    text: `${name} ${status} ${row.step_label.toLowerCase()}${detail}`,
    timestamp: formatTimestamp(row.created_at),
  };
}

export async function resolveBuyerConversation(draft: DraftRow) {
  return apiJson<DraftRow>(`/api/drafts/${draft.id}/resolve`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({expected_revision:draft.revision})});
}

export async function retryDraftGeneration(draft: DraftRow) {
  return apiJson(`/api/drafts/${draft.id}/retry-generation`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({expected_revision:draft.revision})});
}

export async function deliverBuyerReply(draft: DraftRow) {
  if (!draftCapabilities(draft).canDeliver) throw new Error("This draft is not eligible for customer delivery.");
  return apiJson<DraftRow>(`/api/drafts/${draft.id}/deliver`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({expected_revision:draft.revision})});
}

export async function refreshBuyerDraft(draft: DraftRow) {
  return apiJson<{inbound_id:string;draft_id:string}>(`/api/drafts/${draft.id}/refresh`, {method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({expected_revision:draft.revision})});
}

export async function retryDraftLearning(draft: DraftRow) {
  return apiJson(`/api/drafts/${draft.id}/retry-learning`, {method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({expected_revision:draft.revision})});
}

export async function simulateInboundDm(input: SimulationInput, key: string, orgId = getCurrentOrgId()) {
  const request = simulationRequest(orgId, input, key);
  return apiJson<{inbound_id:string;draft_id:string;duplicate:boolean}>(request.path,request.init);
}

export interface SleyzConnectionStatus {
  platform:string; configured?:boolean; connected?:boolean; status?:string; account_id?:string|null; connection_id?:string|null; messaging_window_hours?:number;
}
export async function fetchSleyzConnections(orgId = getCurrentOrgId()) {
  return apiJson<{connections:SleyzConnectionStatus[]}>(`/api/sleyz/connections?org_id=${encodeURIComponent(orgId)}`);
}

export function subscribeWorkspace(onEvent: (event:WorkspaceEvent)=>void, onError:(message:string|null)=>void) {
  return subscribeWorkspaceTransport(onEvent,onError,{
    getOrgId:owner=>getCurrentOrgId(owner),
    createSource:createSquadEventSource,
    subscribeAuth:callback=>{
      const listener=getSupabaseBrowserClient()?.auth.onAuthStateChange((event,session)=>callback(event,session?.user.id));
      return ()=>listener?.data.subscription.unsubscribe();
    },
  });
}

function formatTimestamp(value?: string) {
  if (!value) return "Now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Now";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
