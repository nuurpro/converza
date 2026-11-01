export type DashboardGateDestination = "allow" | "/landing" | "/onboarding" | "/onboarding/reveal";

export function isAuthFormValid(step: string, values: {email:string;password:string;phone:string}) {
  if (!values.email.trim() || !values.email.includes('@') || !values.email.includes('.') || !values.password) return false;
  if (step === 'signIn') return true;
  return step === 'signUp' && values.phone.trim().length > 0 && values.password.length >= 8 && /[A-Za-z]/.test(values.password) && /\d/.test(values.password);
}

export async function restoreWorkspaceDestination(): Promise<string> {
  const {restoreWorkspaceSession} = await import('@/lib/api/session');
  const session = await restoreWorkspaceSession();
  const destination = getDashboardGateDestination(session.user?.id ?? null, session.passport);
  return destination === 'allow' ? '/' : destination;
}

interface GatePassport {
  id?: string;
  org_id?: string;
  owner_user_id?: string;
  onboarding_completed_at?: string | null;
  paywall_status?: "pending" | "stub_completed" | "paid";
}

export function getDashboardGateDestination(ownerUserId: string | null, passport: GatePassport | null) {
  if (!ownerUserId) return "/landing";
  if (!passport?.onboarding_completed_at) return "/onboarding";
  if (passport.paywall_status !== "stub_completed" && passport.paywall_status !== "paid") {
    return "/onboarding/reveal";
  }
  return "allow";
}
