export type DraftState = "PENDING_DRAFT" | "AWAITING_HITL" | "APPROVED" | "EDITED" | "REJECTED" | "PUBLISHED";
import type { SleyzDraftArtifact, SleyzPlatform } from "./sleyz";

export interface DraftRow {
  id: string;
  org_id: string;
  agent_slug: string;
  status: DraftState;
  revision: number;
  draft_content: string;
  final_content?: string | null;
  inbound_text?: string;
  prospect_id?: string | null;
  created_at?: string;
  generation_error?: string | null;
  generation_status?: "pending" | "running" | "failed" | "completed";
  delivery_status?: "idle" | "sending" | "failed" | "ambiguous" | "delivered";
  delivery_error?: string | null;
  delivery_attempt_id?: string | null;
  delivery_claimed_at?: string | null;
  delivery_receipt?: Record<string, unknown> | null;
  updated_at?: string;
  delivered_at?: string | null;
  resolved_at?: string | null;
  sleyz_artifact?: SleyzDraftArtifact | null;
  simulated?: boolean;
  platform?: SleyzPlatform | null;
  superseded_by?: string | null;
  learning_status?: "pending" | "running" | "completed" | "failed" | "skipped" | null;
  learning_error?: string | null;
}
export interface MessageRow { id: string; [key: string]: unknown }
export interface WorkspaceState {
  cursor: number;
  drafts: Record<string, DraftRow>;
  messages: MessageRow[];
  steps: MessageRow[];
}
export type WorkspaceEvent =
  | { type: "snapshot"; cursor: number; drafts: DraftRow[]; messages: MessageRow[]; steps: MessageRow[] }
  | { type: "draft_transition"; event_id?: number; row: DraftRow }
  | { type: "squad_message" | "agent_run_step"; event_id?: number; row: MessageRow }
  | { type: "error"; error: string };

export function emptyWorkspace(): WorkspaceState {
  return { cursor: 0, drafts: {}, messages: [], steps: [] };
}

export function presentationStatus(status: DraftState) {
  return ({PENDING_DRAFT:"generating", AWAITING_HITL:"pending", APPROVED:"approved", EDITED:"edited", REJECTED:"rejected", PUBLISHED:"published"} as const)[status];
}

export function applyWorkspaceEvent(state: WorkspaceState, event: WorkspaceEvent): WorkspaceState {
  if (event.type === "error") return state;
  if (event.type === "snapshot") {
    return {cursor:event.cursor, drafts:Object.fromEntries(event.drafts.map(row=>[row.id,row])), messages:event.messages, steps:event.steps};
  }
  const cursor = Math.max(state.cursor, event.event_id ?? state.cursor);
  if (event.type === "draft_transition") {
    const old = state.drafts[event.row.id];
    if (old && old.revision >= event.row.revision) return {...state,cursor};
    return {...state,cursor,drafts:{...state.drafts,[event.row.id]:event.row}};
  }
  const key = event.type === "squad_message" ? "messages" : "steps";
  if (state[key].some(row=>row.id === event.row.id)) return {...state,cursor};
  return {...state,cursor,[key]:[...state[key],event.row]};
}
