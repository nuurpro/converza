export type PaywallStatus = "pending" | "stub_completed" | "paid";
export type PlanId = "basic" | "pilot" | "operating-system";

export function billingStatusCopy(status: PaywallStatus) {
  if (status === "paid") return "Paid manually";
  if (status === "stub_completed") {
    return "Testing access enabled - no payment recorded";
  }
  return "Invoice pending";
}

export function agentName(slug: string) {
  const names: Record<string, string> = {
    milo: "Milo",
    sleyz: "Sleyz",
    vea: "Vea",
  };
  return names[slug] ?? "Unknown agent";
}
