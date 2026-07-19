"use client";

import Sidebar from "@/components/sidebar/Sidebar";
import { useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { fetchOnboardingState } from "@/lib/api/onboarding";
import { getDashboardGateDestination, isPublicAppRoute } from "@/lib/access";
import { setCurrentOrgId } from "@/lib/org";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { setActiveOwnerUserId } from "@/lib/brand-cache";

interface MainLayoutProps {
  children: React.ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [gateState, setGateState] = useState<"checking" | "allowed" | "blocked">("checking");
  const [gateError, setGateError] = useState("");
  const pathname = usePathname();
  const router = useRouter();

  const isPublicRoute = isPublicAppRoute(pathname);

  useEffect(() => {
    if (isPublicRoute) {
      setGateState("allowed");
      return;
    }

    let cancelled = false;

    async function checkAccess() {
      setGateState("checking");
      setGateError("");
      try {
        const supabase = getSupabaseBrowserClient();
        const sessionUser = supabase ? (await supabase.auth.getUser()).data.user : null;
        const ownerUserId = sessionUser?.id || null;

        if (sessionUser?.id) {
          setActiveOwnerUserId(sessionUser.id);
        }

        const passport = ownerUserId ? await fetchOnboardingState(ownerUserId) : null;
        if (ownerUserId && passport?.org_id) {
          setCurrentOrgId(passport.org_id, ownerUserId);
        }
        const destination = getDashboardGateDestination(ownerUserId, passport);
        if (destination !== "allow") {
          router.replace(destination);
          if (!cancelled) setGateState("blocked");
          return;
        }

        if (!cancelled) setGateState("allowed");
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "Could not verify workspace access.";
          if (message.includes("Onboarding database migration is pending")) {
            router.replace("/landing");
            setGateState("blocked");
            return;
          }
          setGateError(message);
          setGateState("blocked");
        }
      }
    }

    void checkAccess();

    return () => {
      cancelled = true;
    };
  }, [isPublicRoute, pathname, router]);

  // Marketing and onboarding routes render without the dashboard shell.
  if (isPublicRoute) {
    return <>{children}</>;
  }

  if (gateState === "checking") {
    return (
      <div className="grid min-h-screen place-items-center bg-white font-workspace-sans text-[13px] text-text-muted">
        Checking workspace access...
      </div>
    );
  }

  if (gateState === "blocked") {
    return (
      <div className="grid min-h-screen place-items-center bg-white px-4 font-workspace-sans text-text-secondary">
        {gateError ? (
          <div className="max-w-md rounded-2xl border border-border bg-bg-elevated p-5 text-[13px] leading-relaxed">
            {gateError}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      {/* Mobile hamburger */}
      <button
        onClick={() => setSidebarOpen(true)}
        className="fixed left-3 top-3 z-50 flex h-10 w-10 items-center justify-center rounded-lg bg-bg-secondary ring-1 ring-border md:hidden"
        aria-label="Open menu"
      >
        <Menu size={20} className="text-text-primary" />
      </button>

      {/* Sidebar — drawer on mobile, fixed on desktop */}
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Main content — offset by sidebar width on desktop only */}
      <main className="ml-0 flex flex-1 flex-col overflow-hidden md:ml-[var(--sidebar-width)]">
        {children}
      </main>
    </div>
  );
}
