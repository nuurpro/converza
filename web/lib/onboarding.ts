import { PLAN_PRICES } from "./pricing.shared.js";
import { setCachedBrandName } from "./brand-cache";
export { OWNER_USER_STORAGE_KEY, setActiveOwnerUserId } from "./brand-cache";

export type MarketingHandler = "nobody" | "me" | "in-house" | "agency-freelancer";
export type ReplyHandler = "me" | "someone else" | "falls through the cracks";
export type PrimaryGoal = "more leads" | "faster replies" | "more content" | "all of it";

export interface OnboardingAnswers {
  business_name?: string;
  industry?: string;
  core_offer?: string;
  ideal_customer?: string;
  customer_location?: string;
  current_marketing_handler?: MarketingHandler;
  current_marketing_spend?: number | null;
  current_reply_handler?: ReplyHandler;
  weekly_message_volume?: number;
  primary_pain_point?: string;
  primary_goal?: PrimaryGoal;
  brand_tone?: string[];
  brand_colors?: string[];
  channels_requested?: string[];
  owner_name?: string;
  owner_contact?: string;
}

export interface OnboardingAnalysis {
  branch: "ghost-town" | "founder-trap" | "bleeding-cash" | "fallback";
  headline: string;
  detail: string;
  goalNote: string;
  before: string;
  after: string;
  cta: string;
  monthlySavings?: number;
  spend?: number;
  converzaPrice: number;
}

export const ONBOARDING_STORAGE_KEY = "converza.onboarding.answers";

export const toneOptions = ["confident", "friendly", "premium", "playful", "technical", "direct"];
export const channelOptions = ["Instagram", "TikTok", "Telegram", "WhatsApp", "website chat"];

export function buildAnalysis(answers: OnboardingAnswers): OnboardingAnalysis {
  const handler = answers.current_marketing_handler;
  const spend = Number(answers.current_marketing_spend || 0);
  const volume = Number(answers.weekly_message_volume || 0);
  const converzaPrice = PLAN_PRICES.pilot;
  const pain = answers.primary_pain_point?.trim() || "the bottleneck you described";

  if (volume === 0) {
    return {
      branch: "ghost-town",
      headline:
        "You're not getting inbound messages right now, and nothing is currently being spent on generating them. The real problem isn't slow replies — it's that nothing is creating demand yet.",
      detail: `You told us: "${pain}". That's a content and visibility problem, not a response-time problem.`,
      goalNote: personalizeForGoal(answers),
      before: "No content going out, no leads coming in.",
      after:
        "Milo drafts real marketing content and hooks for your review. Vea turns your best ideas into real video ads. You approve what goes out — nothing publishes without your click.",
      cta: "See plans built for getting your first leads",
      converzaPrice,
    };
  }

  if (volume > 10 && answers.current_reply_handler === "me") {
    return {
      branch: "founder-trap",
      headline: `You're personally handling about ${formatNumber(volume)} messages a week.`,
      detail:
        "Harvard Business Review and MIT research (Oldroyd, 2007/2011) found leads contacted within 5 minutes are 21x more likely to qualify than those contacted after 30 minutes. Every message sitting in your inbox is a small chance slipping away.",
      goalNote: personalizeForGoal(answers),
      before: "Juggling every reply yourself, on your own time.",
      after:
        "Sleyz drafts a reply the moment a message comes in. You review and approve it before it sends — replies go out fast, without you writing every one by hand.",
      cta: "See plans built for faster replies",
      converzaPrice,
    };
  }

  if ((handler === "agency-freelancer" || handler === "in-house") && spend > 0) {
    const monthlySavings = spend - converzaPrice;
    return {
      branch: "bleeding-cash",
      headline: `You're currently spending $${formatNumber(spend)}/month on ${formatMarketingHandler(handler)}.`,
      detail: `$${formatNumber(spend)}/month today vs. $${formatNumber(converzaPrice)}/month with Converza — that's $${formatNumber(monthlySavings)}/month back, without losing the work.`,
      goalNote: personalizeForGoal(answers),
      before: `Paying $${formatNumber(spend)}/month and waiting on deliverables.`,
      after:
        "Milo, Sleyz, and Vea produce your hooks, replies, and videos directly. You review and approve — nothing waits on a retainer schedule.",
      cta: "See plans that cost less than what you're paying now",
      monthlySavings,
      spend,
      converzaPrice,
    };
  }

  return {
    branch: "fallback",
    headline: `You told us the frustration is "${pain}".`,
    detail: `Your first priority is ${answers.primary_goal || "growth"}. No outside statistic is needed here — this is your own bottleneck, in your own words.`,
    goalNote: personalizeForGoal(answers),
    before: "Work depends on manual follow-up, scattered ideas, and whoever has time that day.",
    after:
      "Milo drafts real marketing hooks, Sleyz drafts real DM replies, and Vea renders real video. You review and approve the work before anything ships.",
    cta: "See plans",
    converzaPrice,
  };
}

export function personalizeForGoal(answers: OnboardingAnswers) {
  const frustration = answers.primary_pain_point?.trim() || "the bottleneck you described";
  const goal = answers.primary_goal || "growth";
  return `You said the frustration is "${frustration}" and the priority is ${goal}. The setup should attack that first.`;
}

export function regretCopy(analysis: OnboardingAnalysis, answers: OnboardingAnswers) {
  if (analysis.branch === "bleeding-cash" && typeof analysis.monthlySavings === "number") {
    return `You're about to leave the $${formatNumber(analysis.monthlySavings)}/month gap we just calculated.`;
  }
  const pain = answers.primary_pain_point?.trim() || "the lead handling problem you described";
  return `You're about to leave this unfinished while "${pain}" is still costing attention.`;
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatMarketingHandler(handler: MarketingHandler) {
  if (handler === "agency-freelancer") return "an agency or freelancer";
  if (handler === "in-house") return "an in-house team";
  if (handler === "me") return "your own time";
  return "marketing";
}

export function loadLocalAnswers(): OnboardingAnswers {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(ONBOARDING_STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

export function saveLocalAnswers(answers: OnboardingAnswers) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify(answers));
  if (answers.business_name?.trim()) {
    setCachedBrandName(answers.business_name);
  }
}
