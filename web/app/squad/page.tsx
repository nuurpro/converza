"use client";
import {useState} from "react";
import {ChatInputBar,SquadMessage,WorkspaceHeader} from "@/components/workspace/AgentWorkspace";
import type {DraftStatus} from "@/lib/data/workspace";
import {mapSquadMessage,resolveHitlDraft,sendSquadMessage,resolveBuyerConversation,retryDraftGeneration,deliverBuyerReply,refreshBuyerDraft,retryDraftLearning,type SquadMessageRow} from "@/lib/api/workspace";
import {withUnlinkedDrafts} from "@/lib/data/sleyz";
import {useWorkspace} from "@/lib/hooks/useWorkspace";

export default function SquadChatPage(){
  const {messages,drafts,error,setError}=useWorkspace();
  const [sending,setSending]=useState(false);
  const [busy,setBusy]=useState<string|null>(null);
  const [localMessages,setLocalMessages]=useState<SquadMessageRow[]>([]);
  const rows=messages as unknown as SquadMessageRow[];
  const merged=[...rows,...localMessages.filter(row=>!rows.some(existing=>existing.id===row.id))];
  const all=withUnlinkedDrafts(merged,drafts);
  async function decide(id:string,status:DraftStatus,content?:string){
    const draft=drafts[id];if(!draft||busy)return;setBusy(id);setError(null);
    try{await resolveHitlDraft(id,status==="approved"?"approve":status==="rejected"?"reject":"edit",content,draft.revision);}
    catch(failure){setError(failure instanceof Error?failure.message:"Decision failed");}
    finally{setBusy(null);}
  }
  async function act(id:string,action:"resolve"|"retry"|"deliver"|"refresh"|"learn"){
    const draft=drafts[id];if(!draft||busy)return;setBusy(id);setError(null);
    try{if(action==="resolve")await resolveBuyerConversation(draft);else if(action==="deliver")await deliverBuyerReply(draft);else if(action==="refresh")await refreshBuyerDraft(draft);else if(action==="learn")await retryDraftLearning(draft);else await retryDraftGeneration(draft);}
    catch(failure){setError(failure instanceof Error?failure.message:"Action failed");}
    finally{setBusy(null);}
  }
  async function send(text:string){setSending(true);setError(null);try{const result=await sendSquadMessage(text);setLocalMessages(current=>[...current,result.message]);}catch(failure){setError(failure instanceof Error?failure.message:"Message failed");}finally{setSending(false);}}
  return <div className="flex h-full flex-col bg-white"><WorkspaceHeader title="Squad chat" subtitle="everyone, in one room"/>
    <main className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-10"><div className="mx-auto flex max-w-4xl flex-col gap-4">
      {error&&<p role="status" className="rounded-xl border border-border p-3 text-sm">{error}</p>}
      {all.map(row=>{const message=mapSquadMessage(row,row.hitl_draft_id?drafts[row.hitl_draft_id]:undefined);return <SquadMessage key={row.id} message={message} busy={busy!==null} onHitlAction={message.hitlCard?(status,content)=>void decide(message.hitlCard!.id,status,content):undefined} onResolve={message.hitlCard?()=>void act(message.hitlCard!.id,"resolve"):undefined} onRetry={message.hitlCard?()=>void act(message.hitlCard!.id,"retry"):undefined} onDeliver={message.hitlCard?()=>void act(message.hitlCard!.id,"deliver"):undefined} onRefresh={message.hitlCard?()=>void act(message.hitlCard!.id,"refresh"):undefined} onRetryLearning={message.hitlCard?()=>void act(message.hitlCard!.id,"learn"):undefined}/>;})}
    </div></main><ChatInputBar placeholder="Message the squad..." showTaskToggle isSending={sending} onSend={send}/></div>;
}
