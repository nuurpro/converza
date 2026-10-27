"use client";

import Sidebar from "@/components/sidebar/Sidebar";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Menu } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { restoreWorkspaceSession } from "@/lib/api/session";
import {getWorkspaceSession,resetWorkspaceSession,subscribeSession} from '@/lib/org';
import { getDashboardGateDestination } from "@/lib/access";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

interface MainLayoutProps {
  children: React.ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [gateState, setGateState] = useState<"checking" | "allowed" | "blocked">("checking");
  const [gateError, setGateError] = useState("");
  const pathname = usePathname();
  const router = useRouter();
  const session=useSyncExternalStore(subscribeSession,getWorkspaceSession,getWorkspaceSession);

  const isPublicRoute = pathname?.startsWith("/landing") || pathname?.startsWith("/onboarding");

  useEffect(() => {
    let cancelled = false;
    let attempt = 0;
    async function checkAccess() {
      const current=++attempt;
      setGateState("checking");
      setGateError("");
      try {
        await restoreWorkspaceSession();
        if (!cancelled && current===attempt) setGateState("allowed");
      } catch (error) {
        if (!cancelled && current===attempt) {
          const message = error instanceof Error ? error.message : "Could not verify workspace access.";
          if (message === 'Sign in required' || message === 'Invalid user session') {
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
    const listener=getSupabaseBrowserClient()?.auth.onAuthStateChange((event,next)=>{
      if(event==='SIGNED_OUT'){
        attempt++;resetWorkspaceSession();setGateState('blocked');router.replace('/landing');
      }else if(event==='SIGNED_IN'||event==='TOKEN_REFRESHED'||event==='INITIAL_SESSION'){
        if(getWorkspaceSession().user?.id!==next?.user.id)resetWorkspaceSession();
        // Supabase invokes listeners while holding its auth lock.
        setTimeout(()=>{if(!cancelled)void checkAccess();},0);
      }
    });

    return () => {
      cancelled = true;
      attempt++;listener?.data.subscription.unsubscribe();resetWorkspaceSession();
    };
  }, [router]);

  useEffect(()=>{
    if(!isPublicRoute && session.user){
      const destination=getDashboardGateDestination(session.user.id,session.passport);
      if(destination!=='allow')router.replace(destination);
    }
  },[isPublicRoute,pathname,session,router]);

  // Marketing and onboarding routes render without the dashboard shell.
  if (pathname?.startsWith('/landing')) {
    return <>{children}</>;
  }

  if(pathname?.startsWith('/onboarding')&&session.user)return <div key={session.user.id}>{children}</div>;

  if (gateState === "checking" || (gateState==='allowed'&&!session.user)) {
    return (
      <div className="grid min-h-screen place-items-center bg-white font-workspace-sans text-[13px] text-text-muted">
        Checking workspace access...
      </div>
    );
  }

  if (gateState === "blocked" || getDashboardGateDestination(session.user?.id??null,session.passport)!=='allow') {
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
    <div key={`${session.user?.id}:${session.orgId}:${session.generation}`} className="flex h-screen overflow-hidden bg-white">
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
