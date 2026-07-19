"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { LoaderCircle, Save } from "lucide-react";
import {
  fetchWorkspaceSettings,
  updateWorkspaceSettings,
} from "@/lib/api/settings";
import { getCurrentOrgId } from "@/lib/org";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export default function ProfilePage() {
  const [orgId, setOrgId] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("");
  const [expectedUpdatedAt, setExpectedUpdatedAt] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const [needsReload, setNeedsReload] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      setLoading(true);
      setError("");

      try {
        const supabase = getSupabaseBrowserClient();
        if (!supabase) throw new Error("Authentication is not configured.");

        const { data, error: authError } = await supabase.auth.getUser();
        if (authError) throw authError;
        if (!data.user) throw new Error("Sign in to manage your profile.");

        const currentOrgId = getCurrentOrgId(data.user.id);
        const settings = await fetchWorkspaceSettings(currentOrgId);
        if (cancelled) return;

        setOrgId(currentOrgId);
        setEmail(data.user.email ?? "");
        setName(settings.owner_name ?? "");
        setRole(settings.owner_role ?? "");
        setExpectedUpdatedAt(settings.updated_at ?? "");
        setNeedsReload(false);
      } catch (loadError) {
        if (!cancelled) {
          setError(errorMessage(loadError, "Could not load your profile."));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadProfile();
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  function markChanged() {
    setSaved(false);
    setError("");
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ownerName = name.trim();
    if (!ownerName || !orgId || !expectedUpdatedAt || saving) return;

    setSaving(true);
    setSaved(false);
    setError("");

    try {
      const ownerRole = role.trim();
      const settings = await updateWorkspaceSettings(
        {
          owner_name: ownerName,
          owner_role: ownerRole || null,
        },
        expectedUpdatedAt,
        orgId,
      );
      setName(ownerName);
      setRole(ownerRole);
      setExpectedUpdatedAt(settings.updated_at ?? expectedUpdatedAt);
      setSaved(true);
    } catch (saveError) {
      const message = errorMessage(saveError, "Could not save your profile.");
      setError(message);
      setNeedsReload(message.includes("another tab"));
    } finally {
      setSaving(false);
    }
  }

  const cannotSave = loading || saving || needsReload || !orgId || !expectedUpdatedAt || !name.trim();

  return (
    <form className="space-y-10 sm:space-y-12" onSubmit={saveProfile} aria-busy={loading || saving}>
      <header>
        <h2 className="text-[28px] font-medium text-text-primary">Profile</h2>
        <p className="mt-2 max-w-md text-[15px] leading-relaxed text-text-secondary">
          Your identity inside the workspace and on agent attribution.
        </p>
      </header>

      <section className="flex min-w-0 items-center gap-4 border-b border-border pb-8 sm:gap-5 sm:pb-10">
        <div
          className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-accent text-[18px] font-medium text-white"
          aria-hidden="true"
        >
          {initialsFor(name, email)}
        </div>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-medium text-text-primary">
            {name || (loading ? "Loading profile..." : "Workspace owner")}
          </div>
          <div className="mt-1 truncate text-[13px] text-text-muted">
            {email || (loading ? "Loading email..." : "Email unavailable")}
          </div>
        </div>
      </section>

      <Field htmlFor="owner-name" label="Full name" hint="As it appears on agent threads.">
        <input
          id="owner-name"
          name="owner_name"
          value={name}
          required
          disabled={loading || saving || needsReload || !orgId}
          aria-describedby="owner-name-hint"
          autoComplete="name"
          onChange={(event) => {
            setName(event.target.value);
            markChanged();
          }}
          className={inputClassName}
        />
      </Field>

      <Field htmlFor="owner-role" label="Role" hint="Optional. What you do at the company.">
        <input
          id="owner-role"
          name="owner_role"
          value={role}
          disabled={loading || saving || needsReload || !orgId}
          aria-describedby="owner-role-hint"
          autoComplete="organization-title"
          onChange={(event) => {
            setRole(event.target.value);
            markChanged();
          }}
          className={inputClassName}
        />
      </Field>

      <Field htmlFor="profile-email" label="Email" hint="Used for login. It cannot be changed here.">
        <input
          id="profile-email"
          name="email"
          type="email"
          value={email}
          readOnly
          aria-readonly="true"
          aria-describedby="profile-email-hint"
          className="w-full rounded-lg border border-border bg-bg-secondary px-3.5 py-2.5 text-[14px] text-text-muted outline-none"
        />
      </Field>

      {error ? (
        <div className="flex flex-wrap items-center gap-3">
          <StatusMessage kind="error">{error}</StatusMessage>
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
            ? "Loading profile..."
            : saving
              ? "Saving changes..."
              : saved
                ? "Changes saved."
                : "Save to update your workspace profile."}
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

function initialsFor(name: string, email: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length > 0) {
    return `${words[0][0] ?? ""}${words.length > 1 ? words.at(-1)?.[0] ?? "" : ""}`.toUpperCase();
  }
  return (email.trim()[0] || "?").toUpperCase();
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
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

function StatusMessage({ kind, children }: { kind: "error"; children: ReactNode }) {
  return (
    <p role="alert" className="border-l-2 border-error bg-error-dim px-4 py-3 text-[13px] text-error">
      {children}
    </p>
  );
}
