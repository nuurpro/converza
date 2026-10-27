import type { OnboardingAnswers } from "@/lib/onboarding";
import { authenticatedFetch, restoreWorkspaceSession } from "@/lib/api/session";
import {getWorkspaceSession,setWorkspaceSession} from '@/lib/org';

export interface OnboardingPassport {
  id: string;
  org_id: string;
  owner_user_id: string;
  onboarding_answers?: OnboardingAnswers;
  onboarding_completed_at?: string | null;
  paywall_status?: "pending" | "stub_completed" | "paid";
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
    throw new Error(detail || `Request failed with ${response.status}`);
  }
  return payload as T;
}

async function apiJson<T>(path: string, init?: RequestInit) {
  const headers=new Headers(init?.headers);headers.set('Content-Type','application/json');
  const response = await authenticatedFetch(backendPath(path), {
    ...init,
    headers,
  });
  return readJson<T>(response);
}

export async function fetchOnboardingState(ownerUserId: string) {
  const session=await restoreWorkspaceSession();
  if(session.user?.id!==ownerUserId)throw new Error('Workspace owner changed');
  return session.passport;
}

function acceptPassport(passport:OnboardingPassport){
  const user=getWorkspaceSession().user;
  if(!user||user.id!==passport.owner_user_id)throw new Error('Workspace owner changed');
  setWorkspaceSession(user,passport);return passport;
}

export async function saveOnboardingAnswers(ownerUserId: string, answers: OnboardingAnswers) {
  const payload = await apiJson<{ passport: OnboardingPassport }>("/api/onboarding/passport", {
    method: "POST",
    body: JSON.stringify({
      owner_user_id: ownerUserId,
      answers,
    }),
  });
  return acceptPassport(payload.passport);
}

export async function markOnboardingComplete(ownerUserId: string) {
  const payload = await apiJson<{ passport: OnboardingPassport }>("/api/onboarding/complete", {
    method: "POST",
    body: JSON.stringify({
      owner_user_id: ownerUserId,
    }),
  });
  return acceptPassport(payload.passport);
}

export async function completeStubPayment(ownerUserId: string) {
  const payload = await apiJson<{ passport: OnboardingPassport }>("/api/onboarding/stub-payment", {
    method: "POST",
    body: JSON.stringify({
      owner_user_id: ownerUserId,
    }),
  });
  return acceptPassport(payload.passport);
}
