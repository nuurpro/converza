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
  const [answers, setAnswers] = useState<OnboardingAnswers>({});
  const [ownerUserId, setOwnerUserId] = useState("");
  const [selectedPlan, setSelectedPlan] = useState("pilot");
  const [showRegret, setShowRegret] = useState(false);
  const [showPaymentModal, setShowPaymentModal] = useState(false);
  const [checkoutError, setCheckoutError] = useState("");
  const [checkoutPending, setCheckoutPending] = useState(false);

  const analysis = useMemo(() => buildAnalysis(answers), [answers]);

  useEffect(() => {
    const supabase = getSupabaseBrowserClient();
    async function load() {
      const sessionUser = supabase ? (await supabase.auth.getUser()).data.user : null;
      const userId = sessionUser?.id || "";
      if (!userId) {
        router.replace("/landing");
        return;
      }
      setOwnerUserId(userId);
      const passport = await fetchOnboardingState(userId).catch(() => null);
      const nextAnswers = passport?.onboarding_answers || loadLocalAnswers();
      saveLocalAnswers(nextAnswers);
      setAnswers(nextAnswers);
    }
    void load();
  }, [router]);

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

  const handleCheckoutMock = async (provider: string) => {
    console.log(`[Checkout Intent] User selected: ${provider}`);
    if (!ownerUserId || checkoutPending) return;
    setCheckoutPending(true);
    setCheckoutError("");
    try {
      await completeStubPayment(ownerUserId, selectedPlan);
      setShowPaymentModal(false);
      router.push("/dashboard");
    } catch (error) {
      setCheckoutError(
        error instanceof Error ? error.message : "Could not enable testing access.",
      );
    } finally {
      setCheckoutPending(false);
    }
  };

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
            Start your pilot manually.
          </h1>
          <p className="mt-5 text-[18px] leading-relaxed text-text-secondary">
            Choose the plan you want to discuss. Payment is handled manually after the call by invoice, then your dashboard is unlocked.
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
            <div className="text-[15px] font-medium text-text-primary">Manual pilot start</div>
            <p className="mt-1 text-[13px] text-text-secondary">
              No card form here. We confirm fit on a call, send a Wise or Payme invoice, then mark the workspace as paid after it clears.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowPaymentModal(true)}
            className="inline-flex items-center justify-center gap-2 rounded-full bg-converza-blue px-5 py-3 text-[13px] font-semibold text-white transition-transform hover:scale-[1.02] disabled:opacity-60"
          >
            Book a call to start your pilot
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

      {showPaymentModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md border border-zinc-800 bg-[#111111] p-6 text-white">
            <div>
              <p className="font-workspace-mono text-[11px] uppercase tracking-[0.18em] text-zinc-500">
                Demo mode
              </p>
              <h2 className="mt-3 text-[28px] font-semibold tracking-[-0.04em]">
                Select Payment Gateway
              </h2>
              <p className="mt-2 text-[14px] leading-relaxed text-zinc-400">
                This is a painted-door test. No card is required, and no payment will be charged.
              </p>
            </div>

            <div className="mt-6 space-y-3">
              <button
                type="button"
                onClick={() => handleCheckoutMock("Paddle")}
                disabled={checkoutPending}
                className="group w-full border border-zinc-800 bg-zinc-950 p-4 text-left transition-colors hover:border-[#1b5bf7] hover:bg-[#1b5bf7]/10"
              >
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="text-[16px] font-semibold text-white">Paddle</div>
                    <div className="mt-1 text-[13px] text-zinc-500">
                      International / USD / Credit Card
                    </div>
                  </div>
                  <ArrowRight size={16} className="text-zinc-600 transition-colors group-hover:text-[#1b5bf7]" />
                </div>
              </button>

              <button
                type="button"
                onClick={() => handleCheckoutMock("Local")}
                disabled={checkoutPending}
                className="group w-full border border-zinc-800 bg-zinc-950 p-4 text-left transition-colors hover:border-emerald-500 hover:bg-emerald-500/10"
              >
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <div className="text-[16px] font-semibold text-white">Click / Payme</div>
                    <div className="mt-1 text-[13px] text-zinc-500">
                      Uzbekistan Local / UZS / Uzcard
                    </div>
                  </div>
                  <ArrowRight size={16} className="text-zinc-600 transition-colors group-hover:text-emerald-400" />
                </div>
              </button>
            </div>

            {checkoutError ? (
              <p role="alert" className="mt-4 border border-red-900 bg-red-950/40 px-4 py-3 text-[13px] text-red-200">
                {checkoutError}
              </p>
            ) : null}

            <button
              type="button"
              onClick={() => setShowPaymentModal(false)}
              disabled={checkoutPending}
              className="mt-5 w-full border border-zinc-800 px-4 py-3 text-[13px] font-medium text-zinc-300 transition-colors hover:bg-zinc-900 hover:text-white"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
    </main>
  );
}
