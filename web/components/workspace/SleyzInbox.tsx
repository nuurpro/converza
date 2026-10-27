"use client";

import {useEffect,useRef,useState,type FormEvent} from "react";
import {SquadMessage} from "@/components/workspace/AgentWorkspace";
import {useWorkspace} from "@/lib/hooks/useWorkspace";
import {deliverBuyerReply,fetchSleyzConnections,mapSquadMessage,refreshBuyerDraft,resolveBuyerConversation,resolveHitlDraft,retryDraftGeneration,retryDraftLearning,simulateInboundDm,type SleyzConnectionStatus} from "@/lib/api/workspace";
import type {DraftStatus} from "@/lib/data/workspace";
import type {SleyzPlatform} from "@/lib/data/sleyz";
import {useMiloOrg} from '@/lib/hooks/useMiloOrg';

const input="mt-1 w-full rounded-lg border border-border bg-white px-3 py-2 text-xs";

export function SleyzInbox() {
  const org=useMiloOrg();return org?<Inbox key={org} org={org}/>:<p className="p-5 text-sm">Sign in to review buyer replies.</p>;
}
function Inbox({org}:{org:string}){
  const {drafts,error,setError}=useWorkspace();
  const [platform,setPlatform]=useState<SleyzPlatform>("telegram");
  const [customer,setCustomer]=useState("demo-buyer");
  const [text,setText]=useState("");
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState("");
  const [connections,setConnections]=useState<SleyzConnectionStatus[]>([]);
  // Retain the key after an uncertain request; editing inputs starts a distinct simulation.
  const request=useRef<{payload:string;key:string}|null>(null);
  const alive=useRef(false),lock=useRef(false);
  useEffect(()=>{alive.current=true;void fetchSleyzConnections(org).then(result=>{if(alive.current)setConnections(result.connections);}).catch(()=>{});return()=>{alive.current=false;};},[org]);
  async function simulate(event:FormEvent) {
    event.preventDefault();if(lock.current)return;lock.current=true;setBusy(true);setError(null);setNotice("");
    const payload=JSON.stringify({platform,customer,text});
    if(request.current?.payload!==payload)request.current={payload,key:crypto.randomUUID()};
    try {
      const result=await simulateInboundDm({platform,customer_id:customer,customer_handle:customer,text},request.current!.key,org);
      if(!alive.current)return;
      setNotice(`${result.duplicate?"Existing":"New"} simulation queued. Draft ${result.draft_id} appears below when ready.`);
      request.current=null;
    }catch(failure){if(alive.current)setError(failure instanceof Error?failure.message:"Simulation failed");}
    finally{lock.current=false;if(alive.current)setBusy(false);}
  }
  async function act(id:string,action:"approve"|"reject"|"edit"|"deliver"|"resolve"|"retry"|"refresh"|"learn",content?:string) {
    const draft=drafts[id];if(!draft||lock.current)return;lock.current=true;setBusy(true);setError(null);
    try {
      if(action==="deliver")await deliverBuyerReply(draft);
      else if(action==="resolve")await resolveBuyerConversation(draft);
      else if(action==="retry")await retryDraftGeneration(draft);
      else if(action==="refresh")await refreshBuyerDraft(draft);
      else if(action==="learn")await retryDraftLearning(draft);
      else await resolveHitlDraft(id,action,content,draft.revision);
    }catch(failure){if(alive.current)setError(failure instanceof Error?failure.message:"Action failed");}
    finally{lock.current=false;if(alive.current)setBusy(false);}
  }
  function decide(id:string,status:DraftStatus,content?:string) {void act(id,status==="approved"?"approve":status==="rejected"?"reject":"edit",content);}
  const inbound=Object.values(drafts).filter(draft=>draft.agent_slug==="sleyz");
  return <section className="mx-auto w-full max-w-3xl space-y-4 px-5 py-5 font-workspace-sans">
    <details className="rounded-xl border border-border p-4" open>
      <summary className="cursor-pointer text-sm font-medium">Test an inbound DM</summary>
      <p className="mt-2 text-xs text-text-muted">Runs the sales pipeline and creates a review draft. Simulations cannot send messages or train agent memory.</p>
      <form className="mt-3 space-y-3" onSubmit={simulate}>
        <div className="grid grid-cols-2 gap-3"><label className="text-xs">Platform<select className={input} value={platform} onChange={event=>setPlatform(event.target.value as SleyzPlatform)}><option value="telegram">Telegram</option><option value="instagram">Instagram</option></select></label>
          <label className="text-xs">Customer handle or ID<input className={input} required maxLength={200} value={customer} onChange={event=>setCustomer(event.target.value)}/></label></div>
        <label className="block text-xs">Incoming message<textarea className={input} required maxLength={10000} rows={2} value={text} onChange={event=>setText(event.target.value)} placeholder="Is this in stock? I'd like two."/></label>
        <button disabled={busy||!text.trim()||!customer.trim()} className="rounded-full bg-black px-4 py-2 text-xs text-white disabled:opacity-50">{busy?"Working…":"Generate review draft"}</button>
      </form>
      {connections.length>0&&<p className="mt-3 text-xs text-text-muted">Connections: {connections.map(connection=>`${connection.platform}: ${connection.status??(connection.configured||connection.connected?"configured":"not configured")}`).join(" · ")}</p>}
    </details>
    {(error||notice)&&<p role="status" className="rounded-lg border border-border p-3 text-xs">{error||notice}</p>}
    {inbound.length>0&&<h2 className="text-sm font-medium">Buyer replies for review</h2>}
    {inbound.map(draft=>{
      const message=mapSquadMessage({id:`draft:${draft.id}`,org_id:draft.org_id,sender_slug:"sleyz",content:draft.simulated?"Simulated inbound DM":"Inbound buyer reply",hitl_draft_id:draft.id,created_at:draft.created_at},draft);
      return <SquadMessage key={draft.id} message={message} busy={busy} onHitlAction={(status,content)=>decide(draft.id,status,content)} onDeliver={()=>void act(draft.id,"deliver")} onResolve={()=>void act(draft.id,"resolve")} onRetry={()=>void act(draft.id,"retry")} onRefresh={()=>void act(draft.id,"refresh")} onRetryLearning={()=>void act(draft.id,"learn")}/>;
    })}
  </section>;
}
