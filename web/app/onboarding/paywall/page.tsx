"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, X } from "lucide-react";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { PRICING_TIERS } from "@/lib/pricing";
import {
  buildAnalysis,
  loadLocalAnswers,
  regretCopy,
  saveLocalAnswers,
  type OnboardingAnswers,
} from "@/lib/onboarding";
import { completeStubPayment, fetchOnboardingState } from "@/lib/api/onboarding";

export default function PaywallPage() {
  const router = useRouter();
  const [ownerUserId, setOwnerUserId] = useState("");
  const [answers, setAnswers] = useState<OnboardingAnswers>({});
  const [selectedPlan, setSelectedPlan] = useState("pilot");
  const [showRegret, setShowRegret] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [retry, setRetry] = useState(0);
  const [restoring, setRestoring] = useState(true);

  const analysis = useMemo(() => buildAnalysis(answers), [answers]);

  useEffect(() => {
    let active=true;
    const supabase = getSupabaseBrowserClient();
    async function load() {
      setRestoring(true);setLoadError('');
      try {
      const sessionUser = supabase ? (await supabase.auth.getUser()).data.user : null;
      const userId = sessionUser?.id || "";
      if (!userId) {
        router.replace("/landing");
        return;
      }
      const passport = await fetchOnboardingState(userId);
      if(!active)return;
      if(!passport?.onboarding_completed_at){router.replace('/onboarding');return;}
      setOwnerUserId(userId);
      const nextAnswers = passport?.onboarding_answers || loadLocalAnswers(userId);
      saveLocalAnswers(nextAnswers,userId);
      setAnswers(nextAnswers);
      } catch(failure){if(active)setLoadError(failure instanceof Error?failure.message:'Could not restore workspace');}
      finally {if(active)setRestoring(false);}
    }
    void load();
    return()=>{active=false;};
  }, [router,retry]);

  useEffect(() => {
    history.pushState({ paywall: true }, "", window.location.href);
    const onPop = () => {
      setShowRegret(true);
      history.pushState({ paywall: true }, "", window.location.href);
    };
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("popstate", onPop);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, []);

  async function finishStubPayment() {
    if (!ownerUserId) return;
    setLoading(true);
    try {await completeStubPayment(ownerUserId);router.push('/');}
    catch(failure){setLoadError(failure instanceof Error?failure.message:'Could not update workspace');}
    finally {setLoading(false);}
  }

  if(restoring||loadError)return <main className="grid min-h-screen place-items-center bg-bg-primary text-text-muted"><div role="status">{loadError||'Restoring workspace...'}{loadError&&<button className="mt-3 block rounded-lg border border-border px-4 py-3" onClick={()=>setRetry(value=>value+1)}>Retry</button>}</div></main>;

  return (
    <main
      className="min-h-screen bg-bg-primary px-4 py-8 text-text-primary"
      onClick={(event) => {
        if (event.target === event.currentTarget) setShowRegret(true);
      }}
    >
      <section className="mx-auto max-w-[1180px] rounded-[32px] border border-border bg-bg-elevated p-6 sm:p-10">
        <div className="max-w-[760px]">
          <p className="font-workspace-mono text-[11px] uppercase tracking-[0.18em] text-text-muted">
            Choose your Converza plan
          </p>
          <h1 className="mt-4 font-serif text-[44px] leading-none tracking-[-0.045em] sm:text-[68px]">
            Unlock the dashboard.
          </h1>
          <p className="mt-5 text-[18px] leading-relaxed text-text-secondary">
            Payment integration coming next. For Phase A, choose a plan and click the testing button to continue.
          </p>
        </div>

        <div className="mt-10 grid gap-4 lg:grid-cols-3">
          {PRICING_TIERS.map((tier) => (
            <button
              key={tier.id}
              type="button"
              onClick={() => setSelectedPlan(tier.id)}
              className={`rounded-3xl border p-6 text-left transition-all ${
                selectedPlan === tier.id ? "border-converza-blue bg-converza-blue-dim" : "border-border bg-bg-elevated hover:bg-bg-hover"
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="font-workspace-mono text-[11px] uppercase tracking-[0.16em] text-text-muted">{tier.name}</div>
                {selectedPlan === tier.id ? <Check size={18} className="text-converza-blue" /> : null}
              </div>
              <div className="mt-5 text-[38px] font-medium tracking-[-0.04em]">{tier.price}</div>
              <p className="mt-3 min-h-[48px] text-[14px] leading-relaxed text-text-secondary">{tier.note}</p>
              <ul className="mt-6 space-y-2 text-[13px] text-text-secondary">
                {tier.features.map((feature) => (
                  <li key={feature} className="flex gap-2">
                    <Check size={14} className="mt-0.5 text-converza-blue" />
                    {feature}
                  </li>
                ))}
              </ul>
            </button>
          ))}
        </div>

        <div className="mt-8 flex flex-col gap-3 rounded-2xl border border-border bg-bg-secondary p-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[15px] font-medium text-text-primary">Testing stub</div>
            <p className="mt-1 text-[13px] text-text-secondary">
              No card will be charged. This only sets paywall_status to stub_completed.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void finishStubPayment()}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-full bg-converza-blue px-5 py-3 text-[13px] font-semibold text-white transition-transform hover:scale-[1.02] disabled:opacity-60"
          >
            {loading ? "Unlocking..." : "Continue for testing"}
            <ArrowRight size={14} />
          </button>
        </div>
      </section>

      {showRegret ? (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/25 px-4">
          <div className="w-full max-w-md rounded-3xl border border-border bg-white p-6">
            <button
              type="button"
              onClick={() => setShowRegret(false)}
              className="ml-auto grid h-9 w-9 place-items-center rounded-full border border-border text-text-muted hover:bg-bg-hover"
              aria-label="Close"
            >
              <X size={16} />
            </button>
            <h2 className="mt-3 font-serif text-[36px] leading-none tracking-[-0.04em]">
              Before you leave
            </h2>
            <p className="mt-4 text-[15px] leading-relaxed text-text-secondary">
              {regretCopy(analysis, answers)}
            </p>
            <button
              type="button"
              onClick={() => setShowRegret(false)}
              className="mt-6 w-full rounded-full bg-converza-blue px-5 py-3 text-[13px] font-semibold text-white"
            >
              Stay on this step
            </button>
          </div>
        </div>
      ) : null}
    </main>
  );
}
