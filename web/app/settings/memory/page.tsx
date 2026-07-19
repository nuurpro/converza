"use client";

import { useEffect, useMemo, useState } from "react";
import { Brain } from "lucide-react";
import { fetchAgentMemory, type AgentMemoryRow } from "@/lib/api/settings";
import { getCurrentOrgId } from "@/lib/org";
import { agentName } from "@/lib/settings";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export default function MemoryPage() {
  const [memory, setMemory] = useState<AgentMemoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const supabase = getSupabaseBrowserClient();
        const user = supabase ? (await supabase.auth.getUser()).data.user : null;
        if (!user) throw new Error("Sign in to view agent memory.");
        setMemory(await fetchAgentMemory(getCurrentOrgId(user.id)));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Could not load agent memory.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  const knownMemory = useMemo(
    () => memory.filter((row) => agentName(row.agent_slug) !== "Unknown agent"),
    [memory],
  );

  return (
    <div className="space-y-12">
      <header>
        <h2 className="text-[28px] font-medium tracking-[-0.025em] text-text-primary">Agent memory</h2>
        <p className="mt-2 max-w-md text-[15px] leading-relaxed text-text-secondary">
          Real context saved by Milo, Sleyz, and Vea for this workspace.
        </p>
      </header>

      {loading ? <p className="text-[14px] text-text-muted">Loading memory...</p> : null}
      {error ? (
        <p className="rounded-xl border border-error/20 bg-error/5 p-4 text-[13px] text-error" role="alert">
          {error}
        </p>
      ) : null}

      {!loading && !error && knownMemory.length === 0 ? (
        <div className="rounded-2xl border border-border bg-bg-elevated p-8 text-center">
          <Brain className="mx-auto text-text-muted" size={20} strokeWidth={1.7} />
          <h3 className="mt-4 text-[15px] font-medium text-text-primary">No memory yet</h3>
          <p className="mt-2 text-[13px] text-text-muted">No memory yet - this fills in as your agents work.</p>
        </div>
      ) : null}

      <div className="space-y-3">
        {knownMemory.map((row) => (
          <article key={row.id} className="rounded-xl border border-border bg-bg-elevated p-4">
            <p className="text-[14px] leading-relaxed text-text-primary">{row.content}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
              <span>{agentName(row.agent_slug)}</span>
              <span aria-hidden="true">/</span>
              <span>{row.role}</span>
              <span aria-hidden="true">/</span>
              <time dateTime={row.created_at}>{new Date(row.created_at).toLocaleString()}</time>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
