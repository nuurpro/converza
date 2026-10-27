import { PLAN_PRICES } from "./pricing.shared.js";

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
  branch: "savings" | "volume";
  headline: string;
  detail: string;
  goalNote: string;
  monthlySavings?: number;
  spend?: number;
  converzaPrice: number;
}

export const ONBOARDING_STORAGE_KEY = "converza.onboarding.answers";
export const OWNER_USER_STORAGE_KEY = "converza.ownerUserId";
export const BRAND_NAME_STORAGE_KEY = "converza.brandName";

export const toneOptions = ["confident", "friendly", "premium", "playful", "technical", "direct"];
export const channelOptions = ["Instagram", "TikTok", "Telegram", "WhatsApp", "website chat"];

export function buildAnalysis(answers: OnboardingAnswers): OnboardingAnalysis {
  const handler = answers.current_marketing_handler;
  const spend = Number(answers.current_marketing_spend || 0);
  const volume = Number(answers.weekly_message_volume || 0);
  const converzaPrice = PLAN_PRICES.pilot;

  if ((handler === "agency-freelancer" || handler === "in-house") && spend > 0) {
    const monthlySavings = spend - converzaPrice;
    return {
      branch: "savings",
      headline: `You're spending $${formatNumber(spend)}/mo today. Converza is $${formatNumber(converzaPrice)}/mo.`,
      detail: `That's $${formatNumber(monthlySavings)}/mo back, without losing the work.`,
      goalNote: personalizeForGoal(answers),
      monthlySavings,
      spend,
      converzaPrice,
    };
  }

  return {
    branch: "volume",
    headline: `You get about ${formatNumber(volume)} messages a week with no dedicated help handling them.`,
    detail: "Every one of those is a lead someone else is following up on faster.",
    goalNote: personalizeForGoal(answers),
    converzaPrice,
  };
}

export function personalizeForGoal(answers: OnboardingAnswers) {
  const frustration = answers.primary_pain_point?.trim() || "the bottleneck you described";
  const goal = answers.primary_goal || "growth";
  return `You said the frustration is "${frustration}" and the priority is ${goal}. The setup should attack that first.`;
}

export function regretCopy(analysis: OnboardingAnalysis, answers: OnboardingAnswers) {
  if (analysis.branch === "savings" && typeof analysis.monthlySavings === "number") {
    return `You're about to leave the $${formatNumber(analysis.monthlySavings)}/mo gap we just calculated.`;
  }
  const pain = answers.primary_pain_point?.trim() || "the lead handling problem you described";
  return `You're about to leave this unfinished while "${pain}" is still costing attention.`;
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

export function loadLocalAnswers(ownerId?: string | null): OnboardingAnswers {
  if (typeof window === "undefined" || !ownerId) return {};
  try {
    return JSON.parse(window.localStorage.getItem(`${ONBOARDING_STORAGE_KEY}.${ownerId}`) || "{}");
  } catch {
    return {};
  }
}

export function saveLocalAnswers(answers: OnboardingAnswers, ownerId?: string | null) {
  if (typeof window === "undefined" || !ownerId) return;
  window.localStorage.setItem(`${ONBOARDING_STORAGE_KEY}.${ownerId}`, JSON.stringify(answers));
  if (answers.business_name?.trim()) {
    window.localStorage.setItem(`${BRAND_NAME_STORAGE_KEY}.${ownerId}`, answers.business_name.trim());
    window.dispatchEvent(new Event("converza:brand-name-updated"));
  }
}
