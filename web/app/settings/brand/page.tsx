"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { LoaderCircle, Save } from "lucide-react";
import {
  fetchWorkspaceSettings,
  updateWorkspaceSettings,
} from "@/lib/api/settings";
import { getCurrentOrgId } from "@/lib/org";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { setCachedBrandName } from "@/lib/brand-cache";

interface BrandForm {
  brand_name: string;
  tone: string;
  target_audience: string;
  core_offer: string;
  target_location: string;
}

const emptyBrand: BrandForm = {
  brand_name: "",
  tone: "",
  target_audience: "",
  core_offer: "",
  target_location: "",
};

export default function BrandPage() {
  const [orgId, setOrgId] = useState("");
  const [ownerUserId, setOwnerUserId] = useState("");
  const [form, setForm] = useState<BrandForm>(emptyBrand);
  const [initialForm, setInitialForm] = useState<BrandForm>(emptyBrand);
  const [expectedUpdatedAt, setExpectedUpdatedAt] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const [needsReload, setNeedsReload] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadBrand() {
      setLoading(true);
      setError("");

      try {
        const supabase = getSupabaseBrowserClient();
        if (!supabase) throw new Error("Authentication is not configured.");

        const { data, error: authError } = await supabase.auth.getUser();
        if (authError) throw authError;
        if (!data.user) throw new Error("Sign in to manage your brand passport.");

        const currentOrgId = getCurrentOrgId(data.user.id);
        const settings = await fetchWorkspaceSettings(currentOrgId);
        if (cancelled) return;

        const loadedForm = {
          brand_name: settings.brand_name ?? "",
          tone: settings.tone ?? "",
          target_audience: settings.target_audience ?? "",
          core_offer: settings.core_offer ?? "",
          target_location: settings.target_location ?? "",
        };
        setOrgId(currentOrgId);
        setOwnerUserId(data.user.id);
        setForm(loadedForm);
        setInitialForm(loadedForm);
        setExpectedUpdatedAt(settings.updated_at ?? "");
        setNeedsReload(false);
        if (loadedForm.brand_name) setCachedBrandName(loadedForm.brand_name, data.user.id);
      } catch (loadError) {
        if (!cancelled) {
          setError(errorMessage(loadError, "Could not load the brand passport."));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadBrand();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  function updateField(field: keyof BrandForm, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setSaved(false);
    setError("");
  }

  async function saveBrand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!orgId || !expectedUpdatedAt || saving) return;

    const updates = dirtyUpdates(form, initialForm);
    if (Object.keys(updates).length === 0 || Object.values(updates).some((value) => !value)) return;

    setSaving(true);
    setSaved(false);
    setError("");

    try {
      const settings = await updateWorkspaceSettings(updates, expectedUpdatedAt, orgId);
      const savedForm = { ...form, ...updates };
      setForm(savedForm);
      setInitialForm(savedForm);
      setExpectedUpdatedAt(settings.updated_at ?? expectedUpdatedAt);
      setCachedBrandName(savedForm.brand_name, ownerUserId);
      setSaved(true);
    } catch (saveError) {
      const message = errorMessage(saveError, "Could not save the brand passport.");
      setError(message);
      setNeedsReload(message.includes("another tab"));
    } finally {
      setSaving(false);
    }
  }

  const hasBlankRequiredField = Object.values(form).some((value) => !value.trim());
  const hasNoChanges = Object.keys(dirtyUpdates(form, initialForm)).length === 0;
  const cannotSave = loading || saving || needsReload || !orgId || !expectedUpdatedAt || hasBlankRequiredField || hasNoChanges;

  return (
    <form className="space-y-10 sm:space-y-12" onSubmit={saveBrand} aria-busy={loading || saving}>
      <header>
        <h2 className="text-[28px] font-medium text-text-primary">Brand passport</h2>
        <p className="mt-2 max-w-lg text-[15px] leading-relaxed text-text-secondary">
          The workspace source of truth used when Converza creates brand-specific work.
        </p>
      </header>

      <Field htmlFor="brand-name" label="Brand name" hint="Shown in the sidebar and used as the workspace identity.">
        <input
          id="brand-name"
          name="brand_name"
          value={form.brand_name}
          required
          disabled={loading || saving || needsReload || !orgId}
          aria-describedby="brand-name-hint"
          autoComplete="organization"
          onChange={(event) => updateField("brand_name", event.target.value)}
          className={inputClassName}
        />
      </Field>

      <Field htmlFor="brand-tone" label="Voice and tone" hint="Describe how the brand should sound in writing.">
        <textarea
          id="brand-tone"
          name="tone"
          rows={3}
          value={form.tone}
          required
          disabled={loading || saving || needsReload || !orgId}
          aria-describedby="brand-tone-hint"
          onChange={(event) => updateField("tone", event.target.value)}
          className={textareaClassName}
        />
      </Field>

      <Field htmlFor="brand-audience" label="Target audience" hint="Who buys from you and what they need.">
        <textarea
          id="brand-audience"
          name="target_audience"
          rows={3}
          value={form.target_audience}
          required
          disabled={loading || saving || needsReload || !orgId}
          aria-describedby="brand-audience-hint"
          onChange={(event) => updateField("target_audience", event.target.value)}
          className={textareaClassName}
        />
      </Field>

      <Field htmlFor="core-offer" label="Core offer" hint="What customers buy and the outcome it provides.">
        <textarea
          id="core-offer"
          name="core_offer"
          rows={2}
          value={form.core_offer}
          required
          disabled={loading || saving || needsReload || !orgId}
          aria-describedby="core-offer-hint"
          onChange={(event) => updateField("core_offer", event.target.value)}
          className={textareaClassName}
        />
      </Field>

      <Field htmlFor="target-location" label="Target location" hint="The markets, cities, or countries you serve.">
        <input
          id="target-location"
          name="target_location"
          value={form.target_location}
          required
          disabled={loading || saving || needsReload || !orgId}
          aria-describedby="target-location-hint"
          onChange={(event) => updateField("target_location", event.target.value)}
          className={inputClassName}
        />
      </Field>

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
            ? "Loading brand passport..."
            : saving
              ? "Saving brand passport..."
              : saved
                ? "Brand passport saved."
                : "All fields are required."}
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

const inputClassName =
  "w-full rounded-lg border border-border bg-bg-elevated px-3.5 py-2.5 text-[14px] text-text-primary outline-none transition-all placeholder:text-text-muted focus:border-text-primary focus:shadow-[0_0_0_4px_rgba(0,0,0,0.04)] disabled:cursor-not-allowed disabled:bg-bg-secondary disabled:text-text-muted";
const textareaClassName = `${inputClassName} resize-y leading-relaxed`;

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function dirtyUpdates(form: BrandForm, initialForm: BrandForm) {
  const updates: Partial<BrandForm> = {};
  (Object.keys(form) as Array<keyof BrandForm>).forEach((field) => {
    const value = form[field].trim();
    if (value !== initialForm[field].trim()) updates[field] = value;
  });
  return updates;
}

function Field({
  htmlFor,
  label,
  hint,
  children,
}: {
  htmlFor: string;
  label: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_1.6fr] md:gap-10">
      <div>
        <label htmlFor={htmlFor} className="text-[14px] font-medium text-text-primary">
          {label}
        </label>
        <div id={`${htmlFor}-hint`} className="mt-1 text-[12.5px] leading-relaxed text-text-muted">
          {hint}
        </div>
      </div>
      <div>{children}</div>
    </div>
  );
}
