"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import {
  setActiveOwnerUserId,
  type OnboardingAnswers,
  channelOptions,
  loadLocalAnswers,
  saveLocalAnswers,
  toneOptions,
} from "@/lib/onboarding";
import { markOnboardingComplete, saveOnboardingAnswers } from "@/lib/api/onboarding";

type QuestionKind = "text" | "select" | "number" | "multi" | "color";

interface Question {
  number: number;
  key: keyof OnboardingAnswers;
  title: string;
  help: string;
  kind: QuestionKind;
  options?: string[];
  optional?: boolean;
  maxSelected?: number;
  placeholder?: string;
}

const questions: Question[] = [
  { number: 1, key: "business_name", title: "Business name", help: "This becomes the workspace identity.", kind: "text", placeholder: "Nafis Beauty Salon" },
  { number: 2, key: "industry", title: "Industry", help: "Use the category your customer would recognize.", kind: "text", placeholder: "Skincare, clinic, SaaS, ecommerce..." },
  { number: 3, key: "core_offer", title: "Core offer, one sentence", help: "What do people buy from you?", kind: "text", placeholder: "Premium skincare kits for dry winter skin." },
  { number: 4, key: "ideal_customer", title: "Ideal customer", help: "Who should Converza write and sell to?", kind: "text", placeholder: "Women 25-40 buying premium skincare online." },
  { number: 5, key: "customer_location", title: "Where customers are based", help: "Markets, cities, or countries.", kind: "text", placeholder: "Uzbekistan now, US and Dubai next." },
  { number: 6, key: "current_marketing_handler", title: "Who handles marketing today?", help: "This helps calculate the right comparison.", kind: "select", options: ["nobody", "me", "in-house", "agency-freelancer"] },
  { number: 7, key: "current_marketing_spend", title: "Monthly spend on that", help: "Use the real number. If you are not sure, estimate low.", kind: "number", placeholder: "5000" },
  { number: 8, key: "current_reply_handler", title: "Who replies to customer messages today?", help: "This shows where leads slow down.", kind: "select", options: ["me", "someone else", "falls through the cracks"] },
  { number: 9, key: "weekly_message_volume", title: "Messages or leads per week, roughly", help: "A rough count is enough.", kind: "number", placeholder: "40" },
  { number: 10, key: "primary_pain_point", title: "Biggest frustration right now", help: "Use your own words. We will echo this back honestly.", kind: "text", placeholder: "We lose leads after hours." },
  { number: 11, key: "primary_goal", title: "First priority", help: "Pick the outcome that matters first.", kind: "select", options: ["more leads", "faster replies", "more content", "all of it"] },
  { number: 12, key: "brand_tone", title: "Brand tone", help: "Choose 2 or 3. This becomes your voice guardrail.", kind: "multi", options: toneOptions, maxSelected: 3 },
  { number: 13, key: "brand_colors", title: "Brand colors", help: "Optional. Pick one primary color or skip.", kind: "color", optional: true },
  { number: 14, key: "channels_requested", title: "Platforms you eventually want connected", help: "These will appear in your channel connection checklist.", kind: "multi", options: channelOptions },
  { number: 15, key: "owner_contact", title: "Your name and best contact", help: "One line is enough for Phase A.", kind: "text", placeholder: "Nuriddin, +998..." },
];

export default function OnboardingPage() {
  const router = useRouter();
  const [answers, setAnswers] = useState<OnboardingAnswers>({});
  const [index, setIndex] = useState(0);
  const [ownerUserId, setOwnerUserId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const supabase = getSupabaseBrowserClient();
    setAnswers(loadLocalAnswers());

    async function readUser() {
      const sessionUser = supabase ? (await supabase.auth.getUser()).data.user : null;
      const userId = sessionUser?.id || "";
      if (!userId) {
        router.replace("/landing");
        return;
      }
      setActiveOwnerUserId(userId);
      setOwnerUserId(userId);
    }

    void readUser();
  }, [router]);

  const visibleQuestions = useMemo(() => {
    if (answers.current_marketing_handler === "nobody") {
      return questions.filter((question) => question.number !== 7);
    }
    return questions;
  }, [answers.current_marketing_handler]);

  const question = visibleQuestions[index] ?? visibleQuestions[0];
  const value = answers[question.key];
  const canContinue = question.optional || hasAnswer(question, value);

  function updateAnswer(key: keyof OnboardingAnswers, nextValue: unknown) {
    const next = { ...answers, [key]: nextValue };
    if (key === "current_marketing_handler" && nextValue === "nobody") {
      next.current_marketing_spend = null;
    }
    if (key === "owner_contact" && typeof nextValue === "string") {
      next.owner_name = nextValue.split(",")[0]?.trim() || nextValue.trim();
    }
    setAnswers(next);
    saveLocalAnswers(next);
  }

  async function continueFlow() {
    if (!ownerUserId || !canContinue) return;
    setSaving(true);
    setError("");
    try {
      await saveOnboardingAnswers(ownerUserId, answers);
      if (index < visibleQuestions.length - 1) {
        setIndex((current) => current + 1);
      } else {
        await markOnboardingComplete(ownerUserId);
        router.push("/onboarding/reveal");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save onboarding.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="min-h-screen bg-bg-primary px-4 py-6 text-text-primary">
      <div className="mx-auto flex min-h-[calc(100vh-48px)] max-w-[980px] flex-col rounded-[28px] border border-border bg-bg-elevated">
        <header className="flex items-center justify-between border-b border-border px-5 py-4 sm:px-7">
          <div>
            <div className="font-workspace-mono text-[10px] uppercase tracking-[0.16em] text-text-muted">
              Step {question.number} of 15
            </div>
            <div className="mt-1 text-[14px] font-medium text-text-secondary">
              Brand Vault setup
            </div>
          </div>
          <button
            type="button"
            onClick={() => router.push("/landing")}
            className="rounded-full border border-border px-3 py-1.5 text-[12px] text-text-secondary hover:bg-bg-hover"
          >
            Exit
          </button>
        </header>

        <section className="grid flex-1 place-items-center px-5 py-10 sm:px-8">
          <div className="w-full max-w-[620px]">
            <div className="mb-8 h-1.5 overflow-hidden rounded-full bg-bg-tertiary">
              <div
                className="h-full rounded-full bg-converza-blue transition-all"
                style={{ width: `${(question.number / 15) * 100}%` }}
              />
            </div>

            <h1 className="font-serif text-[42px] leading-none tracking-[-0.04em] text-text-primary sm:text-[56px]">
              {question.title}
            </h1>
            <p className="mt-4 max-w-[520px] text-[16px] leading-relaxed text-text-secondary">
              {question.help}
            </p>

            <div className="mt-8">
              <QuestionInput question={question} value={value} onChange={(next) => updateAnswer(question.key, next)} />
            </div>

            {error ? (
              <p className="mt-5 rounded-xl border border-error/20 bg-error-dim px-4 py-3 text-[13px] text-error">
                {error}
              </p>
            ) : null}

            <div className="mt-8 flex items-center justify-between">
              <button
                type="button"
                onClick={() => setIndex((current) => Math.max(0, current - 1))}
                disabled={index === 0 || saving}
                className="inline-flex items-center gap-2 rounded-full border border-border px-4 py-2 text-[13px] font-medium text-text-secondary transition-colors hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ArrowLeft size={14} />
                Back
              </button>
              <button
                type="button"
                onClick={() => void continueFlow()}
                disabled={!canContinue || saving}
                className="inline-flex items-center gap-2 rounded-full bg-converza-blue px-5 py-2.5 text-[13px] font-semibold text-white transition-transform hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? "Saving..." : index === visibleQuestions.length - 1 ? "See analysis" : "Continue"}
                <ArrowRight size={14} />
              </button>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function QuestionInput({
  question,
  value,
  onChange,
}: {
  question: Question;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  if (question.kind === "select") {
    return (
      <div className="grid gap-2">
        {question.options?.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={`flex items-center justify-between rounded-2xl border px-4 py-4 text-left text-[15px] transition-colors ${
              value === option ? "border-converza-blue bg-converza-blue-dim text-text-primary" : "border-border bg-bg-elevated text-text-secondary hover:bg-bg-hover"
            }`}
          >
            {option}
            {value === option ? <Check size={16} className="text-converza-blue" /> : null}
          </button>
        ))}
      </div>
    );
  }

  if (question.kind === "multi") {
    const selected = Array.isArray(value) ? value : [];
    return (
      <div className="flex flex-wrap gap-2">
        {question.options?.map((option) => {
          const active = selected.includes(option);
          return (
            <button
              key={option}
              type="button"
              onClick={() => {
                if (active) {
                  onChange(selected.filter((item) => item !== option));
                  return;
                }
                if (question.maxSelected && selected.length >= question.maxSelected) return;
                onChange([...selected, option]);
              }}
              className={`rounded-full border px-4 py-2 text-[13px] font-medium transition-colors ${
                active ? "border-converza-blue bg-converza-blue text-white" : "border-border bg-bg-elevated text-text-secondary hover:bg-bg-hover"
              }`}
            >
              {option}
            </button>
          );
        })}
      </div>
    );
  }

  if (question.kind === "color") {
    const selected = Array.isArray(value) && value[0] ? value[0] : "#1b5bf7";
    return (
      <div className="flex items-center gap-3">
        <input
          type="color"
          value={selected}
          onChange={(event) => onChange([event.target.value])}
          className="h-14 w-20 rounded-xl border border-border bg-bg-elevated p-1"
        />
        <button
          type="button"
          onClick={() => onChange([])}
          className="rounded-full border border-border px-4 py-2 text-[13px] text-text-secondary hover:bg-bg-hover"
        >
          Skip
        </button>
      </div>
    );
  }

  return (
    <input
      type={question.kind === "number" ? "number" : "text"}
      inputMode={question.kind === "number" ? "numeric" : undefined}
      value={typeof value === "number" ? value : typeof value === "string" ? value : ""}
      placeholder={question.placeholder}
      onChange={(event) => {
        onChange(question.kind === "number" ? Number(event.target.value) : event.target.value);
      }}
      className="w-full rounded-2xl border border-border bg-bg-elevated px-5 py-4 text-[17px] text-text-primary outline-none transition-all placeholder:text-text-muted focus:border-converza-blue focus:shadow-[0_0_0_4px_rgba(0,112,243,0.12)]"
      autoFocus
    />
  );
}

function hasAnswer(question: Question, value: unknown) {
  if (question.kind === "multi") return Array.isArray(value) && value.length > 0;
  if (question.kind === "number") return typeof value === "number" && value >= 0;
  return typeof value === "string" && value.trim().length > 0;
}
