"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  Clock3,
  Film,
  LoaderCircle,
  Play,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import {
  approveCalendarDay,
  createMarketingCalendar,
  fetchMarketingCalendar,
  generateCalendarDayDetail,
  type CalendarInterviewAnswers,
  type MarketingCalendar,
  type MarketingCalendarDay,
} from "@/lib/api/marketing-calendar";
import { FALLBACK_PLATFORMS, platformConstraint, resourceCommitment } from "@/lib/marketing-calendar.shared.js";

interface Props {
  onStateChange?: (state: "loading" | "setup" | "ready" | "error") => void;
}

const PLATFORM_OPTIONS = [
  { id: "instagram_reels", label: "Instagram Reels" },
  { id: "youtube_shorts", label: "YouTube Shorts" },
  { id: "tiktok", label: "TikTok" },
  { id: "telegram", label: "Telegram" },
  { id: "linkedin", label: "LinkedIn" },
];

const TONE_OPTIONS = ["Confident", "Friendly", "Premium", "Playful", "Technical", "Direct"];
const PROCESS_OPTIONS = [
  { id: "whatever feels right", label: "Whatever feels right" },
  { id: "occasional posts", label: "We post when we have time" },
  { id: "monthly content calendar", label: "We use a content calendar" },
  { id: "weekly experiments with tracked CPA and ROAS", label: "We run tracked experiments" },
];

const STATUS_COPY: Record<string, string> = {
  skeleton: "Planned",
  draft: "Script ready",
  rendering: "Rendering",
  awaiting_hitl: "Review video",
  completed: "Approved",
  failed: "Needs attention",
};

const initialAnswers: CalendarInterviewAnswers = {
  target_audience: "",
  tone: [],
  core_offer: "",
  platforms: [],
  hours_per_week: 3,
  duration_days: 14,
  has_tracked_metrics_before: false,
  current_process: "",
  overrode_platform_limit: false,
};

function ChoiceButton({
  selected,
  warning,
  onClick,
  children,
}: {
  selected: boolean;
  warning?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex min-h-12 items-center justify-between rounded-xl border px-4 py-3 text-left text-[13px] font-medium transition-all ${
        warning
          ? "border-error bg-error-dim text-error"
          : selected
            ? "border-converza-blue bg-converza-blue-dim text-[#111111]"
            : "border-[#e5e5e5] bg-white text-[#4a4a48] hover:border-[#cfcfcf] hover:bg-[#fafafa]"
      }`}
    >
      {children}
      {selected ? <Check size={15} strokeWidth={2.2} /> : null}
    </button>
  );
}

export default function ManagedMarketingCalendar({ onStateChange }: Props) {
  const [calendar, setCalendar] = useState<MarketingCalendar | null>(null);
  const [state, setState] = useState<"loading" | "setup" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<CalendarInterviewAnswers>(initialAnswers);
  const [showOverride, setShowOverride] = useState(false);
  const [selectedDay, setSelectedDay] = useState<MarketingCalendarDay | null>(null);
  const [dayBusy, setDayBusy] = useState<"detail" | "render" | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchMarketingCalendar()
      .then((value) => {
        if (cancelled) return;
        setCalendar(value);
        setState(value ? "ready" : "setup");
      })
      .catch((nextError) => {
        if (cancelled) return;
        setError(nextError instanceof Error ? nextError.message : "Could not load your marketing calendar.");
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => onStateChange?.(state), [onStateChange, state]);

  const resource = useMemo(
    () => resourceCommitment(answers.hours_per_week, answers.duration_days),
    [answers.hours_per_week, answers.duration_days],
  );
  const constraint = platformConstraint(answers.platforms);

  function canContinue() {
    if (step === 0) return answers.target_audience.trim().length >= 3;
    if (step === 1) return answers.tone.length > 0;
    if (step === 2) return answers.core_offer.trim().length >= 3;
    if (step === 3) return answers.platforms.length > 0;
    if (step === 5) return Boolean(answers.current_process);
    return true;
  }

  function advance() {
    if (step === 3 && constraint && !answers.overrode_platform_limit) {
      setShowOverride(true);
      return;
    }
    if (step < 6) setStep((current) => current + 1);
    else void finishInterview();
  }

  async function finishInterview() {
    setState("loading");
    setError("");
    try {
      const next = await createMarketingCalendar(answers);
      setCalendar(next);
      setState("ready");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Milo could not build the calendar.");
      setState("setup");
    }
  }

  async function openDay(day: MarketingCalendarDay) {
    setSelectedDay(day);
    setError("");
    if (day.status !== "skeleton") return;
    setDayBusy("detail");
    try {
      const result = await generateCalendarDayDetail(calendar!.id, day.day_number);
      setCalendar(result.calendar);
      setSelectedDay(result.day);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Milo could not draft this day.");
    } finally {
      setDayBusy(null);
    }
  }

  async function renderSelectedDay() {
    if (!selectedDay || !calendar) return;
    setDayBusy("render");
    setError("");
    try {
      const result = await approveCalendarDay(calendar.id, selectedDay.day_number);
      setCalendar(result.calendar);
      setSelectedDay(result.day);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Vea could not render this video.");
    } finally {
      setDayBusy(null);
    }
  }

  if (state === "loading") {
    return (
      <section className="grid min-h-[560px] place-items-center border-b border-[#e5e5e5] bg-[#fafafa] px-6">
        <div className="text-center">
          <LoaderCircle className="mx-auto animate-spin text-converza-blue" size={23} />
          <p className="mt-3 text-[13px] text-[#666666]">
            {calendar ? "Updating your plan..." : "Milo is opening your workspace..."}
          </p>
        </div>
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="mx-auto my-10 max-w-2xl rounded-2xl border border-error/20 bg-error-dim p-6">
        <p className="text-[14px] font-medium text-error">Managed calendar unavailable</p>
        <p className="mt-2 text-[13px] leading-relaxed text-[#666666]">{error}</p>
      </section>
    );
  }

  if (state === "setup") {
    const prompts = [
      "Who should this plan reach?",
      "How should the brand sound?",
      "What are we selling?",
      "Where should we focus first?",
      "Have you tracked marketing metrics before?",
      "How do you plan content today?",
      "How many hours can you film each week?",
    ];
    const descriptions = [
      "Describe the people most likely to buy, in plain language.",
      "Choose up to three. Milo uses these when writing every script.",
      "One clear sentence is enough. Include the outcome the customer buys.",
      "Two channels is the recommended starting point.",
      "This only changes how much explanation Milo includes. It is not a score.",
      "Pick the closest match. We use this to keep the plan practical.",
      "We derive the video count from this answer. Vea-rendered videos do not use your filming time.",
    ];

    return (
      <section className="min-h-[calc(100vh-64px)] bg-[#fafafa] px-5 py-8 md:px-10 md:py-12">
        <div className="mx-auto grid max-w-[980px] gap-8 lg:grid-cols-[240px_1fr]">
          <aside className="pt-2">
            <span className="font-workspace-mono text-[10px] uppercase tracking-[0.14em] text-[#999999]">
              Milo · plan setup
            </span>
            <h1 className="mt-4 font-workspace-display text-[28px] font-extrabold tracking-[-0.025em] text-[#111111]">
              Let&apos;s build the first 14 days.
            </h1>
            <p className="mt-3 text-[13px] leading-relaxed text-[#666666]">
              Seven focused answers. Then Milo turns the blank workspace into a plan you can react to.
            </p>
            <div className="mt-7 flex gap-1.5" aria-label={`Question ${step + 1} of 7`}>
              {Array.from({ length: 7 }, (_, index) => (
                <span
                  key={index}
                  className={`h-1 flex-1 rounded-full ${index <= step ? "bg-converza-blue" : "bg-[#e5e5e5]"}`}
                />
              ))}
            </div>
          </aside>

          <div className="rounded-2xl border border-[#e5e5e5] bg-white p-6 md:p-8">
            <div className="flex items-start gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#111111] font-workspace-mono text-[11px] text-white">
                M
              </span>
              <div>
                <p className="font-workspace-mono text-[9px] uppercase tracking-[0.14em] text-[#999999]">
                  Question {step + 1} of 7
                </p>
                <h2 className="mt-2 font-workspace-display text-[24px] font-bold tracking-[-0.02em] text-[#111111]">
                  {prompts[step]}
                </h2>
                <p className="mt-2 text-[13px] leading-relaxed text-[#666666]">{descriptions[step]}</p>
              </div>
            </div>

            <div className="mt-8 min-h-[230px]">
              {step === 0 ? (
                <textarea
                  autoFocus
                  value={answers.target_audience}
                  onChange={(event) => setAnswers({ ...answers, target_audience: event.target.value })}
                  rows={4}
                  placeholder="Example: E-commerce founders selling from Uzbekistan to the US"
                  className="w-full resize-none rounded-xl border border-[#e5e5e5] bg-[#fafafa] px-4 py-3 text-[14px] leading-relaxed text-[#111111] outline-none transition focus:border-converza-blue focus:bg-white"
                />
              ) : null}
              {step === 1 ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {TONE_OPTIONS.map((tone) => {
                    const selected = answers.tone.includes(tone.toLowerCase());
                    return (
                      <ChoiceButton
                        key={tone}
                        selected={selected}
                        onClick={() =>
                          setAnswers({
                            ...answers,
                            tone: selected
                              ? answers.tone.filter((item) => item !== tone.toLowerCase())
                              : answers.tone.length < 3
                                ? [...answers.tone, tone.toLowerCase()]
                                : answers.tone,
                          })
                        }
                      >
                        {tone}
                      </ChoiceButton>
                    );
                  })}
                </div>
              ) : null}
              {step === 2 ? (
                <textarea
                  autoFocus
                  value={answers.core_offer}
                  onChange={(event) => setAnswers({ ...answers, core_offer: event.target.value })}
                  rows={4}
                  placeholder="Example: A $500 pilot that produces one complete campaign"
                  className="w-full resize-none rounded-xl border border-[#e5e5e5] bg-[#fafafa] px-4 py-3 text-[14px] leading-relaxed text-[#111111] outline-none transition focus:border-converza-blue focus:bg-white"
                />
              ) : null}
              {step === 3 ? (
                <div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {PLATFORM_OPTIONS.map((platform) => {
                      const selected = answers.platforms.includes(platform.id);
                      const selectedIndex = answers.platforms.indexOf(platform.id);
                      return (
                        <ChoiceButton
                          key={platform.id}
                          selected={selected}
                          warning={selected && selectedIndex >= 2}
                          onClick={() =>
                            setAnswers({
                              ...answers,
                              overrode_platform_limit: false,
                              platforms: selected
                                ? answers.platforms.filter((item) => item !== platform.id)
                                : [...answers.platforms, platform.id],
                            })
                          }
                        >
                          {platform.label}
                        </ChoiceButton>
                      );
                    })}
                  </div>
                  {constraint ? (
                    <div className="mt-3 flex gap-2 rounded-xl border border-error/20 bg-error-dim p-3 text-[12px] leading-relaxed text-error">
                      <AlertTriangle className="mt-0.5 shrink-0" size={15} />
                      {constraint.message}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {step === 4 ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  <ChoiceButton selected={!answers.has_tracked_metrics_before} onClick={() => setAnswers({ ...answers, has_tracked_metrics_before: false })}>
                    No, not consistently
                  </ChoiceButton>
                  <ChoiceButton selected={answers.has_tracked_metrics_before} onClick={() => setAnswers({ ...answers, has_tracked_metrics_before: true })}>
                    Yes, we track results
                  </ChoiceButton>
                </div>
              ) : null}
              {step === 5 ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  {PROCESS_OPTIONS.map((process) => (
                    <ChoiceButton key={process.id} selected={answers.current_process === process.id} onClick={() => setAnswers({ ...answers, current_process: process.id })}>
                      {process.label}
                    </ChoiceButton>
                  ))}
                </div>
              ) : null}
              {step === 6 ? (
                <div className="rounded-xl border border-[#e5e5e5] bg-[#fafafa] p-5">
                  <div className="flex items-end justify-between gap-4">
                    <span className="text-[13px] text-[#666666]">Weekly filming time</span>
                    <span className="font-workspace-display text-[30px] font-bold text-[#111111]">
                      {answers.hours_per_week}h
                    </span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="10"
                    step="1"
                    value={answers.hours_per_week}
                    onChange={(event) => setAnswers({ ...answers, hours_per_week: Number(event.target.value) })}
                    className="mt-5 w-full accent-[#0070f3]"
                  />
                  <div className="mt-5 flex items-start gap-3 border-t border-[#e5e5e5] pt-4">
                    <Film size={17} className="mt-0.5 shrink-0 text-converza-blue" />
                    <p className="text-[12.5px] leading-relaxed text-[#666666]">
                      A 14-day plan with about <strong className="text-[#111111]">{resource.targetVideoCount} film-it-yourself videos</strong>. Low hours produce a lighter skeleton before it is saved.
                    </p>
                  </div>
                </div>
              ) : null}
              {error ? <p className="mt-4 rounded-xl bg-error-dim p-3 text-[12px] text-error">{error}</p> : null}
            </div>

            <div className="mt-7 flex items-center justify-between border-t border-[#e5e5e5] pt-5">
              <button
                type="button"
                onClick={() => setStep((current) => Math.max(0, current - 1))}
                disabled={step === 0}
                className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-[12px] font-medium text-[#666666] hover:bg-[#f4f4f5] disabled:opacity-30"
              >
                <ArrowLeft size={14} /> Back
              </button>
              <button
                type="button"
                onClick={advance}
                disabled={!canContinue()}
                className="inline-flex items-center gap-2 rounded-full bg-converza-blue px-5 py-2.5 text-[12.5px] font-semibold text-white transition hover:scale-[1.02] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {step === 6 ? "Build my 14-day plan" : "Continue"}
                {step === 6 ? <Sparkles size={14} /> : <ArrowRight size={14} />}
              </button>
            </div>
          </div>
        </div>

        {showOverride ? (
          <div className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4" role="dialog" aria-modal="true">
            <div className="w-full max-w-md rounded-2xl border border-[#e5e5e5] bg-white p-6">
              <AlertTriangle size={21} className="text-error" />
              <h3 className="mt-4 font-workspace-display text-[22px] font-bold text-[#111111]">More channels, less repetition.</h3>
              <p className="mt-2 text-[13px] leading-relaxed text-[#666666]">
                You&apos;re choosing more platforms than we recommend. Continue anyway, or use the focused two-channel plan.
              </p>
              <div className="mt-6 grid gap-2">
                <button
                  onClick={() => {
                    setAnswers({ ...answers, platforms: [...FALLBACK_PLATFORMS], overrode_platform_limit: false });
                    setShowOverride(false);
                    setStep(4);
                  }}
                  className="rounded-xl bg-converza-blue px-4 py-3 text-[12.5px] font-semibold text-white"
                >
                  Use Instagram Reels + YouTube Shorts
                </button>
                <button
                  onClick={() => {
                    setAnswers({ ...answers, overrode_platform_limit: true });
                    setShowOverride(false);
                    setStep(4);
                  }}
                  className="rounded-xl border border-[#e5e5e5] bg-white px-4 py-3 text-[12.5px] font-medium text-[#666666] hover:bg-[#fafafa]"
                >
                  Continue with {answers.platforms.length} platforms
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </section>
    );
  }

  return (
    <section className="border-b border-[#e5e5e5] bg-[#fafafa] px-5 py-8 md:px-10 md:py-10">
      <div className="mx-auto max-w-[1240px]">
        <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex items-center gap-2 font-workspace-mono text-[10px] uppercase tracking-[0.13em] text-[#999999]">
              <CalendarDays size={13} /> Managed calendar
            </div>
            <h2 className="mt-3 font-workspace-display text-[28px] font-extrabold tracking-[-0.025em] text-[#111111]">
              Your next {calendar!.duration_days} days are planned.
            </h2>
            <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-[#666666]">
              Open a day when you&apos;re ready. Milo writes that script only then, so you do not pay to generate work you never use.
            </p>
          </div>
          <div className="flex items-center gap-4 rounded-xl border border-[#e5e5e5] bg-white px-4 py-3">
            <Clock3 size={16} className="text-converza-blue" />
            <div>
              <p className="font-workspace-mono text-[9px] uppercase tracking-[0.12em] text-[#999999]">Your commitment</p>
              <p className="mt-0.5 text-[12.5px] font-medium text-[#111111]">{calendar!.hours_per_week}h/week · {calendar!.target_video_count} videos</p>
            </div>
          </div>
        </header>

        <div className="mt-7 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-7">
          {calendar!.days.map((day) => (
            <button
              key={day.day_number}
              type="button"
              onClick={() => void openDay(day)}
              className={`group flex min-h-[148px] flex-col rounded-xl border p-3 text-left transition-all hover:-translate-y-0.5 hover:bg-white ${
                day.status === "failed" ? "border-error/30 bg-error-dim" : "border-[#e5e5e5] bg-white/70"
              }`}
            >
              <span className="flex items-center justify-between">
                <span className="font-workspace-mono text-[9px] uppercase tracking-[0.12em] text-[#999999]">Day {day.day_number}</span>
                <span className={`h-1.5 w-1.5 rounded-full ${day.status === "skeleton" ? "bg-[#cfcfcf]" : day.status === "failed" ? "bg-error" : "bg-converza-blue"}`} />
              </span>
              <span className="mt-4 text-[12.5px] font-medium leading-[1.4] text-[#111111]">{day.theme}</span>
              <span className="mt-auto pt-4 font-workspace-mono text-[8px] uppercase tracking-[0.1em] text-[#999999]">{STATUS_COPY[day.status] ?? day.status}</span>
            </button>
          ))}
        </div>
      </div>

      {selectedDay ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4" role="dialog" aria-modal="true">
          <div className="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl border border-[#e5e5e5] bg-white p-6 sm:rounded-2xl md:p-7">
            <header className="flex items-start justify-between gap-5">
              <div>
                <p className="font-workspace-mono text-[9px] uppercase tracking-[0.13em] text-[#999999]">Day {selectedDay.day_number} · {STATUS_COPY[selectedDay.status]}</p>
                <h3 className="mt-2 font-workspace-display text-[25px] font-bold tracking-[-0.02em] text-[#111111]">{selectedDay.theme}</h3>
              </div>
              <button onClick={() => setSelectedDay(null)} className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-[#e5e5e5] text-[#666666] hover:bg-[#fafafa]" aria-label="Close day">
                <X size={16} />
              </button>
            </header>

            <div className="mt-6 min-h-[210px] rounded-xl border border-[#e5e5e5] bg-[#fafafa] p-5">
              {dayBusy === "detail" ? (
                <div className="grid min-h-[170px] place-items-center text-center">
                  <div><LoaderCircle className="mx-auto animate-spin text-converza-blue" size={20} /><p className="mt-3 text-[12.5px] text-[#666666]">Milo is writing this day to match the locked theme...</p></div>
                </div>
              ) : selectedDay.script ? (
                <pre className="whitespace-pre-wrap font-workspace-sans text-[13px] leading-[1.7] text-[#333333]">{selectedDay.script}</pre>
              ) : (
                <p className="text-[13px] text-[#666666]">The script has not been generated yet.</p>
              )}
            </div>

            {selectedDay.video_url ? (
              <a href={selectedDay.video_url} target="_blank" rel="noreferrer" className="mt-4 flex items-center justify-between rounded-xl border border-[#e5e5e5] bg-white p-4 text-[13px] font-medium text-[#111111] hover:bg-[#fafafa]">
                Open rendered video <Play size={15} className="text-converza-blue" />
              </a>
            ) : null}
            {error ? <p className="mt-4 rounded-xl bg-error-dim p-3 text-[12px] text-error">{error}</p> : null}

            <div className="mt-6 grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => void renderSelectedDay()}
                disabled={!selectedDay.script || dayBusy !== null || ["rendering", "awaiting_hitl", "completed"].includes(selectedDay.status)}
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-[#111111] px-4 text-[12.5px] font-semibold text-white transition hover:scale-[1.01] disabled:cursor-not-allowed disabled:opacity-40"
              >
                {dayBusy === "render" ? <LoaderCircle size={15} className="animate-spin" /> : <Sparkles size={15} />}
                {selectedDay.status === "awaiting_hitl" ? "Waiting for video review" : selectedDay.status === "completed" ? "Video approved" : "Approve script and render with Vea"}
              </button>
              <button
                type="button"
                disabled
                title="Raw-footage assembly is not supported by the current renderer yet."
                className="inline-flex min-h-12 cursor-not-allowed items-center justify-center gap-2 rounded-xl border border-[#e5e5e5] bg-[#fafafa] px-4 text-[12.5px] font-medium text-[#999999]"
              >
                <Upload size={15} /> Upload own footage · unavailable
              </button>
            </div>
            <p className="mt-3 text-center text-[11px] leading-relaxed text-[#999999]">
              Vea renders through the existing review queue. Nothing publishes without your approval.
            </p>
          </div>
        </div>
      ) : null}
    </section>
  );
}
