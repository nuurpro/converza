import type { OnboardingAnswers } from "@/lib/onboarding";
import { authHeaders } from "@/lib/api/session";
import { getCurrentOrgId } from "@/lib/org";

export interface OnboardingPassport {
  id: string;
  org_id: string;
  owner_user_id: string;
  onboarding_answers?: OnboardingAnswers;
  onboarding_completed_at?: string | null;
  paywall_status?: "pending" | "stub_completed" | "paid";
  selected_plan?: "basic" | "pilot" | "operating-system" | null;
  brand_name?: string | null;
}

function backendPath(path: string) {
  return `/api/backend${path}`;
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = typeof payload?.detail === "string" ? payload.detail : "";
    if (detail.includes("brand_passports.owner_user_id") || detail.includes("42703")) {
      throw new Error("Onboarding database migration is pending. Run migrations/003_onboarding_paywall.sql in Supabase, then refresh.");
    }
    if (detail.includes("hex_colors") || detail.includes("PGRST204")) {
      throw new Error("Brand Passport schema migration is pending. Run migrations/004_brand_passport_structured_columns.sql in Supabase, then refresh.");
    }
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return payload as T;
}

async function apiJson<T>(path: string, init?: RequestInit) {
  const headers = await authHeaders({
    "Content-Type": "application/json",
    ...(init?.headers ?? {}),
  });
  const response = await fetch(backendPath(path), {
    ...init,
    headers,
  });
  return readJson<T>(response);
}

export async function fetchOnboardingState(ownerUserId: string) {
  const payload = await apiJson<{ passport: OnboardingPassport | null }>(
    `/api/onboarding/state/${ownerUserId}`,
  );
  return payload.passport;
}

export async function saveOnboardingAnswers(ownerUserId: string, answers: OnboardingAnswers) {
  const payload = await apiJson<{ passport: OnboardingPassport }>("/api/onboarding/passport", {
    method: "POST",
    body: JSON.stringify({
      owner_user_id: ownerUserId,
      org_id: getCurrentOrgId(ownerUserId),
      answers,
    }),
  });
  return payload.passport;
}

export async function markOnboardingComplete(ownerUserId: string) {
  const payload = await apiJson<{ passport: OnboardingPassport }>("/api/onboarding/complete", {
    method: "POST",
    body: JSON.stringify({
      owner_user_id: ownerUserId,
      org_id: getCurrentOrgId(ownerUserId),
    }),
  });
  return payload.passport;
}

export async function completeStubPayment(ownerUserId: string, selectedPlan: string) {
  const payload = await apiJson<{ passport: OnboardingPassport }>("/api/onboarding/stub-payment", {
    method: "POST",
    body: JSON.stringify({
      owner_user_id: ownerUserId,
      org_id: getCurrentOrgId(ownerUserId),
      selected_plan: selectedPlan,
    }),
  });
  return payload.passport;
}
