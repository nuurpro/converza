import type { WorkspaceEvent } from "./workflow";

interface StreamDependencies {
  getOrgId: (ownerId?: string) => string | null;
  createSource: (orgId: string, cursor?: number) => Promise<EventSource>;
  subscribeAuth: (callback: (event: string, ownerId?: string) => void) => () => void;
}

/** Each organization owns its cursor. Authentication changes invalidate pending connections. */
export function subscribeWorkspaceTransport(
  onEvent: (event: WorkspaceEvent) => void,
  onError: (message: string | null) => void,
  dependencies: StreamDependencies,
) {
  let source: EventSource | null = null;
  let cancelled = false;
  let cursor: number | undefined;
  let connecting = 0;
  let activeOrg = dependencies.getOrgId();
  const reset = () => {
    cursor = undefined;
    onEvent({ type: "snapshot", cursor: 0, drafts: [], messages: [], steps: [] });
  };
  const connect = async (orgId = activeOrg) => {
    if (activeOrg !== orgId) { activeOrg = orgId; reset(); }
    const attempt = ++connecting;
    source?.close();
    if (!orgId) return;
    try {
      const next = await dependencies.createSource(orgId, cursor);
      if (cancelled || attempt !== connecting) { next.close(); return; }
      source = next;
      next.onopen = () => onError(null);
      next.onmessage = event => {
        if(cancelled||attempt!==connecting)return;
        try {
          const payload = JSON.parse(event.data) as WorkspaceEvent;
          if (payload.type === "error") { onError(payload.error); return; }
          if (!["snapshot", "draft_transition", "squad_message", "agent_run_step"].includes(payload.type)) return;
          const id = Number(event.lastEventId);
          if (event.lastEventId && Number.isSafeInteger(id)) cursor = id;
          onEvent(payload);
        } catch { onError("An invalid live event was ignored."); }
      };
      next.onerror = () => {if(!cancelled&&attempt===connecting)onError("Live updates disconnected. Reconnecting…");};
    } catch (error) {
      if (!cancelled && attempt === connecting) onError(error instanceof Error ? error.message : "Live updates failed");
    }
  };
  const unsubscribe = dependencies.subscribeAuth((event, ownerId) => {
    if (event === "TOKEN_REFRESHED") void connect();
    if (event === "SIGNED_IN") void connect(dependencies.getOrgId(ownerId));
    if (event === "SIGNED_OUT") {
      connecting++; source?.close();activeOrg=null; reset(); onError("Sign in to reconnect live updates.");
    }
  });
  void connect();
  return () => { cancelled = true; connecting++; source?.close(); unsubscribe(); };
}
