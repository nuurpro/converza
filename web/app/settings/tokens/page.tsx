"use client";

import { useState } from "react";
import { KeyRound, Plus, X } from "lucide-react";

export default function TokensPage() {
  const [showNotice, setShowNotice] = useState(false);

  return (
    <div className="space-y-12">
      <header>
        <h2 className="text-[28px] font-medium tracking-[-0.025em] text-text-primary">API tokens</h2>
        <p className="mt-2 max-w-md text-[15px] leading-relaxed text-text-secondary">
          Programmatic workspace access will appear here after secure token lifecycle support exists.
        </p>
      </header>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setShowNotice(true)}
          className="inline-flex items-center gap-2 rounded-full bg-text-primary px-4 py-2 text-[13px] font-medium text-bg-elevated transition-transform hover:scale-[1.02]"
        >
          <Plus size={13} strokeWidth={2.4} />
          New token
        </button>
      </div>

      <section className="rounded-2xl border border-border bg-bg-elevated p-8 text-center">
        <KeyRound className="mx-auto text-text-muted" size={20} strokeWidth={1.7} />
        <h3 className="mt-4 text-[15px] font-medium text-text-primary">No API tokens yet</h3>
        <p className="mx-auto mt-2 max-w-sm text-[13px] leading-relaxed text-text-muted">
          No token records are shown because token creation, storage, and revocation are not implemented.
        </p>
      </section>

      {showNotice ? (
        <div className="rounded-2xl border border-border bg-bg-secondary p-5" role="status">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h3 className="text-[14px] font-medium text-text-primary">
                Secure token creation is not available yet.
              </h3>
              <p className="mt-2 text-[13px] leading-relaxed text-text-secondary">
                This control will be enabled only after tokens can be created, stored, revealed once, and revoked safely.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowNotice(false)}
              aria-label="Close notice"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-text-muted hover:bg-bg-hover hover:text-text-primary"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
