"use client";

import { useEffect, useState, type FormEvent } from "react";
import { LoaderCircle, Save } from "lucide-react";
import {
  fetchWorkspaceSettings,
  updateWorkspaceSettings,
} from "@/lib/api/settings";
import { getCurrentOrgId } from "@/lib/org";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export default function SettingsAudiencePage() {
  const [orgId, setOrgId] = useState("");
  const [targetAudience, setTargetAudience] = useState("");
  const [expectedUpdatedAt, setExpectedUpdatedAt] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const [needsReload, setNeedsReload] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadAudience() {
      setLoading(true);
      setError("");

      try {
        const supabase = getSupabaseBrowserClient();
        if (!supabase) throw new Error("Authentication is not configured.");

        const { data, error: authError } = await supabase.auth.getUser();
        if (authError) throw authError;
        if (!data.user) throw new Error("Sign in to manage your target audience.");

        const currentOrgId = getCurrentOrgId(data.user.id);
        const settings = await fetchWorkspaceSettings(currentOrgId);
        if (cancelled) return;

        setOrgId(currentOrgId);
        setTargetAudience(settings.target_audience ?? "");
        setExpectedUpdatedAt(settings.updated_at ?? "");
        setNeedsReload(false);
      } catch (loadError) {
        if (!cancelled) {
          setError(errorMessage(loadError, "Could not load the target audience."));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadAudience();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  async function saveAudience(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedAudience = targetAudience.trim();
    if (!normalizedAudience || !orgId || !expectedUpdatedAt || saving) return;

    setSaving(true);
    setSaved(false);
    setError("");

    try {
      const settings = await updateWorkspaceSettings(
        { target_audience: normalizedAudience },
        expectedUpdatedAt,
        orgId,
      );
      setTargetAudience(normalizedAudience);
      setExpectedUpdatedAt(settings.updated_at ?? expectedUpdatedAt);
      setSaved(true);
    } catch (saveError) {
      const message = errorMessage(saveError, "Could not save the target audience.");
      setError(message);
      setNeedsReload(message.includes("another tab"));
    } finally {
      setSaving(false);
    }
  }

  const cannotSave = loading || saving || needsReload || !orgId || !expectedUpdatedAt || !targetAudience.trim();

  return (
    <form className="space-y-10 sm:space-y-12" onSubmit={saveAudience} aria-busy={loading || saving}>
      <header>
        <h2 className="text-[28px] font-medium text-text-primary">Target audience</h2>
        <p className="mt-2 max-w-lg text-[15px] leading-relaxed text-text-secondary">
          The customer description Converza uses to keep generated work relevant.
        </p>
      </header>

      <div>
        <label htmlFor="target-audience" className="text-[14px] font-medium text-text-primary">
          Audience description
        </label>
        <p id="target-audience-hint" className="mt-1 text-[12.5px] leading-relaxed text-text-muted">
          Describe who they are, what they need, and where they are based.
        </p>
        <textarea
          id="target-audience"
          name="target_audience"
          rows={8}
          value={targetAudience}
          required
          disabled={loading || saving || needsReload || !orgId}
          aria-describedby="target-audience-hint"
          onChange={(event) => {
            setTargetAudience(event.target.value);
            setSaved(false);
            setError("");
          }}
          className="mt-3 w-full resize-y rounded-lg border border-border bg-bg-elevated px-4 py-3 text-[14px] leading-relaxed text-text-primary outline-none transition-all placeholder:text-text-muted focus:border-text-primary focus:shadow-[0_0_0_4px_rgba(0,0,0,0.04)] disabled:cursor-not-allowed disabled:bg-bg-secondary disabled:text-text-muted"
        />
      </div>

      <section className="border-l-2 border-border px-4 py-1" aria-labelledby="audience-research-status">
        <h3 id="audience-research-status" className="text-[14px] font-medium text-text-primary">
          Audience research is not available yet.
        </h3>
        <p className="mt-1.5 max-w-lg text-[13px] leading-relaxed text-text-secondary">
          No audience claims are generated without a verifiable source. This page stores only the
          customer description you provide.
        </p>
      </section>

      {error ? (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="border-l-2 border-error bg-error-dim px-4 py-3 text-[13px] text-error">
            {error}
          </p>
          {!orgId || needsReload ? (
            <button
              type="button"
              onClick={() => setReloadToken((value) => value + 1)}
              className="rounded-full border border-border px-4 py-2 text-[13px] font-medium text-text-primary hover:bg-bg-hover"
            >
              {needsReload ? "Reload latest" : "Retry"}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-4 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
        <span className="text-[12.5px] text-text-muted" aria-live="polite">
          {loading
            ? "Loading target audience..."
            : saving
              ? "Saving target audience..."
              : saved
                ? "Target audience saved."
                : "An audience description is required."}
        </span>
        <button
          type="submit"
          disabled={cannotSave}
          className="inline-flex min-h-10 items-center justify-center gap-2 self-start rounded-full bg-text-primary px-5 py-2.5 text-[13.5px] font-medium text-bg-elevated transition-all hover:scale-[1.02] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:scale-100 sm:self-auto"
        >
          {saving ? <LoaderCircle size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? "Saving..." : "Save changes"}
        </button>
      </div>
    </form>
  );
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
