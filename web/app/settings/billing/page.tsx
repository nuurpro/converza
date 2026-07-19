"use client";

import { useEffect, useMemo, useState } from "react";
import { CreditCard } from "lucide-react";
import { fetchWorkspaceSettings, type WorkspaceSettings } from "@/lib/api/settings";
import { getCurrentOrgId } from "@/lib/org";
import { PRICING_TIERS } from "@/lib/pricing";
import { billingStatusCopy } from "@/lib/settings";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export default function BillingPage() {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const supabase = getSupabaseBrowserClient();
        const user = supabase ? (await supabase.auth.getUser()).data.user : null;
        if (!user) throw new Error("Sign in to view billing status.");
        setSettings(await fetchWorkspaceSettings(getCurrentOrgId(user.id)));
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Could not load billing status.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  const plan = useMemo(
    () => PRICING_TIERS.find((tier) => tier.id === settings?.selected_plan),
    [settings?.selected_plan],
  );

  return (
    <div className="space-y-12">
      <header>
        <h2 className="text-[28px] font-medium tracking-[-0.025em] text-text-primary">Billing</h2>
        <p className="mt-2 max-w-md text-[15px] leading-relaxed text-text-secondary">
          The plan selected for this workspace and its recorded payment state.
        </p>
      </header>

      {loading ? <p className="text-[14px] text-text-muted">Loading billing status...</p> : null}
      {error ? (
        <p className="rounded-xl border border-error/20 bg-error/5 p-4 text-[13px] text-error" role="alert">
          {error}
        </p>
      ) : null}

      {settings ? (
        <section className="rounded-2xl border border-border bg-bg-elevated p-6">
          <div className="flex items-start gap-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border bg-bg-secondary text-text-secondary">
              <CreditCard size={17} strokeWidth={1.8} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted">
                Selected plan
              </div>
              <div className="mt-2 text-[24px] font-medium tracking-[-0.02em] text-text-primary">
                {plan?.name ?? "No plan selected"}
              </div>
              {plan ? <p className="mt-1 text-[14px] text-text-secondary">{plan.price}</p> : null}
              <div className="mt-6 border-t border-border pt-5">
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-muted">
                  Payment record
                </div>
                <p className="mt-2 text-[14px] text-text-primary">
                  {billingStatusCopy(settings.paywall_status)}
                </p>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      <p className="text-[12.5px] leading-relaxed text-text-muted">
        Payments are handled manually for current pilots. This page does not create invoices or charge a card.
      </p>
    </div>
  );
}
