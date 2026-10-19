export type DashboardGateDestination = "allow" | "/landing" | "/onboarding" | "/onboarding/reveal";

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
