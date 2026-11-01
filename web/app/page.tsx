"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "motion/react";
import {
  ArrowUpRight,
  PenLine,
  Sparkles,
  Eye,
  Send,
  ShieldCheck,
  Plug,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {useWorkspace} from "@/lib/hooks/useWorkspace";
import { HitlCard, StatCard } from "@/components/workspace/AgentWorkspace";
import {useMiloOrg} from "@/lib/hooks/useMiloOrg";
import {downloadVideo} from "@/lib/data/vea";
import { type DashboardStat } from "@/lib/data/workspace";
import {createPendingFeedController,type PendingFeedItem} from '@/lib/api/feed';
import {
  fetchDashboardStats,
  mapSquadMessage,
  resolveHitlDraft,
  type AgentRunStepRow,
} from "@/lib/api/workspace";

interface LedgerEvent {
  id: string;
  time: string;
  agent: string;
  action: string;
  icon: LucideIcon;
  live?: boolean;
}

const agentLabels: Record<string, string> = {
  milo: "Milo",
  sleyz: "Sleyz",
  vea: "Vea",
};

const agentIcons: Record<string, LucideIcon> = {
  milo: PenLine,
  sleyz: Send,
  vea: Eye,
};

function formatTime(value?: string) {
  if (!value) return "Now";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Now";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function ledgerEventFromStep(row: AgentRunStepRow): LedgerEvent {
  const detail = row.detail ? ` — ${row.detail}` : "";
  const status =
    row.step_status === "started"
      ? "Started"
      : row.step_status === "completed"
        ? "Finished"
        : row.step_status === "failed"
          ? "Failed"
          : row.step_status;

  return {
    id: row.id,
    time: formatTime(row.created_at),
    agent: agentLabels[row.agent_slug] ?? row.agent_slug,
    action: `${status} ${row.step_label.toLowerCase()}${detail}`,
    icon: row.step_status === "failed" ? ShieldCheck : agentIcons[row.agent_slug] ?? Sparkles,
    live: row.step_status === "started",
  };
}

export default function DashboardPage() {
  const org=useMiloOrg();return org?<Dashboard key={org} org={org}/>:<p className="p-5 text-sm">Sign in to review approvals.</p>;
}
function Dashboard({org}:{org:string}) {
  const [approvals, setApprovals] = useState<PendingFeedItem[]>([]);
  const [nextCursor,setNextCursor]=useState<string|null>(null);
  const [feedLoading,setFeedLoading]=useState(true);
  const [feedError,setFeedError]=useState<string|null>(null);
  const feed=useRef<ReturnType<typeof createPendingFeedController>|null>(null);
  const [ledger, setLedger] = useState<LedgerEvent[]>([]);
  const [stats, setStats] = useState<DashboardStat[]>([]);
  const [busy,setBusy]=useState(false);
  const alive=useRef(false),lock=useRef(false),keys=useRef(new Map<string,string>());
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);

  const workspace=useWorkspace();
  useEffect(()=>{
    const controller=createPendingFeedController(org,page=>{
      setApprovals(page.items);setNextCursor(page.next_cursor);setFeedLoading(false);
    },error=>{setFeedError(error);if(error)setFeedLoading(false);});
    feed.current=controller;
    const refresh=()=>controller.refresh();
    window.addEventListener('online',refresh);document.addEventListener('visibilitychange',refresh);
    return()=>{controller.stop();feed.current=null;window.removeEventListener('online',refresh);document.removeEventListener('visibilitychange',refresh);};
  },[org]);
  useEffect(()=>{
    // SSE snapshots (including reconnects) invalidate the unified server projection.
    feed.current?.refresh();
  },[workspace.drafts,workspace.error]);
  useEffect(()=>{
    const latestSteps=new Map<string,AgentRunStepRow>();
    for(const step of workspace.steps as unknown as AgentRunStepRow[])latestSteps.set(`${step.agent_run_id}:${step.step_label}`,step);
    setLedger([...latestSteps.values()].slice(-9).reverse().map(ledgerEventFromStep));
    let active=true;void fetchDashboardStats(org).then(result=>{if(active)setStats(result);}).catch(error=>{if(active)workspace.setError(error.message);});
    return()=>{active=false;};
  },[org,workspace.steps]);

  async function resolve(id: string, action: "approve" | "reject" | "edit", finalContent?: string) {
    const item=approvals.find(row=>row.kind==='workflow'&&row.source_id===id);
    if(!item||item.kind!=='workflow'||lock.current)return;
    const draft=item.payload.draft;
    const allowed=action==='approve'?item.restrictions.can_approve:action==='edit'?item.restrictions.can_edit:item.restrictions.can_reject;
    if(!allowed)return;
    lock.current=true;setBusy(true);const signature=JSON.stringify([id,draft.revision,action,finalContent]);let key=keys.current.get(signature);if(!key){key=crypto.randomUUID();keys.current.set(signature,key);}
    try {
      const result=await resolveHitlDraft(id, action, finalContent, draft.revision,key);keys.current.delete(signature);
      if(alive.current&&action==='approve'&&draft.vea_artifact&&result.status==='APPROVED'&&!result.superseded_by&&!result.vea_artifact?.superseded)downloadVideo(result.vea_artifact??draft.vea_artifact);
    } catch(error) {
      if(alive.current)workspace.setError(error instanceof Error?error.message:"Decision failed");
      return;
    } finally {
      lock.current=false;if(alive.current)setBusy(false);
    }
    if(!alive.current)return;
    setApprovals((arr) => arr.filter((a) => a.id !== item.id));
    feed.current?.refresh();
    void fetchDashboardStats(org).then(result=>{if(alive.current)setStats(result);}).catch(() => undefined);
  }

  return (
    <div className="flex h-full flex-col bg-white font-workspace-sans">
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-[#e5e5e5] bg-white px-4 pl-14 md:pl-8 md:px-10">
        <div className="flex items-baseline gap-3">
          <h1 className="font-workspace-display text-[22px] font-extrabold tracking-[-0.02em] text-[#111111]">
            Dashboard
          </h1>
          <span className="hidden font-workspace-mono text-[12px] italic text-[#999999] sm:block">
            mission control
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden items-center gap-2 rounded-full border border-[#e5e5e5] bg-white px-3 py-1.5 font-workspace-mono text-[10px] uppercase tracking-[0.12em] text-[#666666] sm:inline-flex">
            <span className="relative flex h-1.5 w-1.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-converza-blue/40" />
              <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-converza-blue" />
            </span>
            Live
          </span>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto bg-white">
        <div className="mx-auto max-w-[1240px] px-6 py-8 md:px-10 md:py-12">
          <Link
            href="/connect-channels"
            className="mb-6 flex flex-col gap-3 rounded-2xl border border-[#e5e5e5] bg-[#fafafa] p-4 transition-colors hover:bg-white sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl border border-[#e5e5e5] bg-white text-converza-blue">
                <Plug size={17} strokeWidth={1.9} />
              </span>
              <span>
                <span className="block text-[14px] font-medium tracking-[-0.01em] text-[#111111]">
                  Connect your channels
                </span>
                <span className="mt-0.5 block text-[12.5px] text-[#666666]">
                  Review Sleyz connection status for your workspace.
                </span>
              </span>
            </span>
            <span className="font-workspace-mono text-[10px] uppercase tracking-[0.12em] text-[#999999]">
              View status →
            </span>
          </Link>

          {workspace.error&&<p role="status" className="mb-5 rounded-lg border border-border p-3 text-sm">{workspace.error}</p>}
          <section className="mb-10 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {stats.map((stat) => (
              <StatCard key={stat.label} value={stat.value} label={stat.label} />
            ))}
          </section>

          <div className="grid gap-10 md:grid-cols-[3fr_2fr] md:gap-14">
          <section>
            <header className="mb-7 flex items-baseline justify-between">
              <div>
                <h2 className="font-workspace-display text-[18px] font-bold tracking-[-0.02em] text-[#111111]">
                  The Swarm Ledger
                </h2>
                <p className="mt-1 font-workspace-mono text-[10px] uppercase tracking-[0.1em] text-[#999999]">
                  Live · {ledger.length} events
                </p>
              </div>
            </header>

            <ol className="relative space-y-1">
              <span
                aria-hidden
                className="absolute bottom-3 left-[7px] top-3 w-px bg-[#e5e5e5]"
              />
              {ledger.length === 0 && (
                <li className="rounded-2xl border border-dashed border-[#e5e5e5] bg-white p-8 text-[13px] text-[#999999]">
                  Waiting for live agent steps...
                </li>
              )}
              {ledger.map((event, i) => (
                <motion.li
                  key={event.id}
                  initial={{ opacity: 0, x: -6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{
                    duration: 0.45,
                    delay: 0.04 * i,
                    ease: [0.16, 1, 0.3, 1],
                  }}
                  className="group relative flex items-start gap-4 rounded-lg py-2.5 pl-5 pr-3 transition-colors hover:bg-[#f4f4f5]"
                >
                  <span className="absolute left-[2px] top-3.5 flex h-3 w-3 items-center justify-center rounded-full bg-white ring-4 ring-white">
                    {event.live ? (
                      <>
                        <span className="absolute inline-flex h-3 w-3 animate-ping rounded-full bg-converza-blue/40" />
                        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-converza-blue" />
                      </>
                    ) : (
                      <span className="h-1.5 w-1.5 rounded-full bg-[#999999]/50" />
                    )}
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
                      <span className="font-workspace-mono text-[10px] uppercase tracking-[0.1em] text-[#999999] tabular-nums">
                        {event.time}
                      </span>
                      <span className="text-[12.5px] font-medium tracking-[-0.005em] text-[#111111]">
                        {event.agent}
                      </span>
                      <event.icon
                        size={11}
                        strokeWidth={1.6}
                        className="text-[#999999]"
                      />
                    </div>
                    <p className="mt-1 max-w-[60ch] text-[13.5px] leading-[1.55] text-[#666666]">
                      {event.action}
                    </p>
                  </div>
                </motion.li>
              ))}
            </ol>
          </section>

          <section>
            <header className="mb-7 flex items-baseline justify-between">
              <div>
                <h2 className="font-workspace-display text-[18px] font-bold tracking-[-0.02em] text-[#111111]">
                  Approval queue
                </h2>
                <p className="mt-1 font-workspace-mono text-[10px] uppercase tracking-[0.1em] text-[#999999]">
                  {feedError?"Refresh unavailable":feedLoading?"Loading approvals":approvals.length === 0
                    ? "Caught up"
                    : `${approvals.length}${nextCursor?'+':''} waiting on you`}
                </p>
              </div>
            </header>

            <div className="space-y-4">
              {feedError&&<p role="alert" className="text-sm text-error">{feedError} <button onClick={()=>feed.current?.refresh()} className="underline">Retry</button></p>}
              <AnimatePresence mode="popLayout">
                {approvals.map(item=>{
                  if(item.kind==='milo'){
                    const campaign=item.payload.campaign;
                    return <motion.article key={item.id} layout className="rounded-2xl border border-[#e5e5e5] bg-white p-5">
                      <p className="font-workspace-mono text-[10px] uppercase text-milo">Milo · {campaign.status.replaceAll('_',' ')}</p>
                      <h3 className="mt-2 text-[15.5px] font-medium">{campaign.artifact?.trigger_reason||'Campaign needs review'}</h3>
                      {item.restrictions.reasons.length>0&&<ul className="mt-2 space-y-1 text-xs text-[#666666]">{item.restrictions.reasons.map((reason,index)=><li key={index}>{reason}</li>)}</ul>}
                      <Link href={item.payload.review_href} className="mt-3 inline-flex items-center gap-1 text-sm underline">Review campaign <ArrowUpRight size={14}/></Link>
                    </motion.article>;
                  }
                  const draft=item.payload.draft;
                  const card=mapSquadMessage({id:item.id,org_id:org,sender_slug:draft.agent_slug,content:'',hitl_draft_id:draft.id},draft).hitlCard;
                  return card?<motion.article key={item.id} layout initial={{opacity:0,y:6}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}}>
                    <p className="font-workspace-mono text-[10px] uppercase text-[#999999]">{agentLabels[draft.agent_slug]??draft.agent_slug}</p>
                    <HitlCard key={`${item.id}:${item.revision}`} card={card} busy={busy} onApprove={()=>void resolve(item.source_id,'approve')} onSkip={()=>void resolve(item.source_id,'reject')} onEdit={text=>void resolve(item.source_id,'edit',text)}/>
                  </motion.article>:null;
                })}
              </AnimatePresence>
              {nextCursor&&<button disabled={feedLoading} onClick={()=>{setFeedLoading(true);feed.current?.loadMore();}} className="rounded-full border border-[#e5e5e5] px-4 py-2 text-sm disabled:opacity-50">Load more approvals</button>}

              {approvals.length === 0 && !feedLoading && !feedError && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
                  className="rounded-2xl border border-dashed border-[#e5e5e5] bg-white p-10 text-center"
                >
                  <ShieldCheck
                    size={22}
                    strokeWidth={1.6}
                    className="mx-auto mb-3 text-[#999999]"
                  />
                  <p className="text-[14px] text-[#111111]">Caught up.</p>
                  <p className="mt-1 text-[12.5px] text-[#999999]">
                    The swarm is working autonomously. New approvals will surface here.
                  </p>
                </motion.div>
              )}
            </div>
          </section>
          </div>
        </div>
      </div>
    </div>
  );
}
