export function formatQualifyError(err: unknown): {
  status: number;
  error: string;
  message: string;
} {
  const raw = err instanceof Error ? err.message : "unknown_error";

  if (
    raw.includes("ANTHROPIC_API_KEY") ||
    raw.includes("ANTHROPIC_AUTH_TOKEN")
  ) {
    return {
      status: 503,
      error: "missing_api_key",
      message: "Anthropic API key is not configured in .env",
    };
  }

  if (raw.includes("insufficient balance") || raw.includes("billing_error")) {
    return {
      status: 402,
      error: "billing_error",
      message:
        "API gateway balance is insufficient. Top up your cc-vibe.com account and restart the server.",
    };
  }

  return {
    status: 502,
    error: "qualification_failed",
    message: raw,
  };
}
