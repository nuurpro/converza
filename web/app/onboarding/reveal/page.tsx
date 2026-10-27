"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import {
  buildAnalysis,
  loadLocalAnswers,
  saveLocalAnswers,
  type OnboardingAnalysis,
  type OnboardingAnswers,
} from "@/lib/onboarding";
import { fetchOnboardingState } from "@/lib/api/onboarding";

export default function RevealPage() {
  const router = useRouter();
  const [answers, setAnswers] = useState<OnboardingAnswers>({});
  const [analysis, setAnalysis] = useState<OnboardingAnalysis | null>(null);

  useEffect(() => {
    let active=true;
    const supabase = getSupabaseBrowserClient();
    async function load() {
      const sessionUser = supabase ? (await supabase.auth.getUser()).data.user : null;
      const ownerUserId = sessionUser?.id || "";
      if (!ownerUserId) {
        router.replace("/landing");
        return;
      }
      const passport = await fetchOnboardingState(ownerUserId).catch(() => null);
      if(!active)return;
      const nextAnswers = passport?.onboarding_answers || loadLocalAnswers(ownerUserId);
      saveLocalAnswers(nextAnswers,ownerUserId);
      setAnswers(nextAnswers);
      setAnalysis(buildAnalysis(nextAnswers));
    }
    void load();
    return()=>{active=false;};
  }, [router]);

  if (!analysis) {
    return <main className="grid min-h-screen place-items-center bg-bg-primary text-text-muted">Preparing your analysis...</main>;
  }

  return (
    <main className="min-h-screen bg-bg-primary px-4 py-8 text-text-primary">
      <section className="mx-auto grid min-h-[calc(100vh-64px)] max-w-[1100px] place-items-center rounded-[32px] border border-border bg-bg-elevated p-6 sm:p-10">
        <div className="max-w-[760px]">
          <p className="font-workspace-mono text-[11px] uppercase tracking-[0.18em] text-text-muted">
            Your Converza analysis
          </p>
          <h1 className="mt-5 font-serif text-[46px] leading-none tracking-[-0.045em] sm:text-[72px]">
            {analysis.headline}
          </h1>
          <p className="mt-6 max-w-[650px] text-[20px] leading-relaxed text-text-secondary">
            {analysis.detail}
          </p>
          <div className="mt-8 rounded-2xl border border-border bg-bg-secondary p-5 text-[15px] leading-relaxed text-text-secondary">
            {analysis.goalNote}
          </div>
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            <Summary label="Business" value={answers.business_name || "Your brand"} />
            <Summary label="Priority" value={answers.primary_goal || "Not set"} />
            <Summary label="Channels" value={(answers.channels_requested || []).join(", ") || "Not set"} />
          </div>
          <button
            type="button"
            onClick={() => router.push("/onboarding/paywall")}
            className="mt-10 inline-flex items-center gap-2 rounded-full bg-converza-blue px-6 py-3 text-[14px] font-semibold text-white transition-transform hover:scale-[1.02]"
          >
            Continue to plans
            <ArrowRight size={15} />
          </button>
        </div>
      </section>
    </main>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border bg-bg-elevated p-4">
      <div className="font-workspace-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">{label}</div>
      <div className="mt-2 text-[14px] text-text-primary">{value}</div>
    </div>
  );
}
