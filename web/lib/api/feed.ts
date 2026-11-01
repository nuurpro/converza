import {authenticatedFetch} from '@/lib/api/session';
import type {DraftRow} from '@/lib/data/workflow';
import type {MiloCampaign} from '@/lib/data/milo';

interface PendingIdentity {
  id:string; source_id:string; revision:number; created_at:string;
  restrictions:{can_approve:boolean;can_edit:boolean;can_reject:boolean;reasons:string[]};
}
export type PendingFeedItem = PendingIdentity & (
  {kind:'workflow';payload:{draft:DraftRow}} |
  {kind:'milo';payload:{campaign:MiloCampaign;review_href:string}}
);
export interface PendingFeedPage {items:PendingFeedItem[];next_cursor:string|null;snapshot_at:string;}

export async function fetchPendingFeed(orgId:string,cursor?:string,signal?:AbortSignal):Promise<PendingFeedPage> {
  const query=new URLSearchParams({org_id:orgId,limit:'50'});
  if(cursor)query.set('cursor',cursor);
  const response=await authenticatedFetch(`/api/backend/api/feed/pending?${query}`,{cache:'no-store',signal});
  const body=await response.json().catch(()=>null);
  if(!response.ok)throw new Error(typeof body?.detail==='string'?body.detail:`Approval feed unavailable (${response.status}). Retry shortly.`);
  if(!body||!Array.isArray(body.items))throw new Error('Approval feed returned an invalid response.');
  return body;
}

/** Publish each valid snapshot; coalesce SSE follow-ups without starving a busy feed. */
export function createPendingFeedController(
  orgId:string,onPage:(page:PendingFeedPage)=>void,onError:(error:string|null)=>void,
  options:{pollMs?:number;fetchPage?:typeof fetchPendingFeed}={},
) {
  const abort=new AbortController(),fetchPage=options.fetchPage??fetchPendingFeed;
  let stopped=false,running=false,dirty=false,pages=1;
  async function refresh() {
    if(stopped)return;
    if(running){dirty=true;return;}
    running=true;
    try {
      do {
        dirty=false;
        try {
          const targetPages=pages;
          let page=await fetchPage(orgId,undefined,abort.signal);
          const items=[...page.items];const seenCursors=new Set<string>();
          for(let index=1;index<targetPages&&page.next_cursor&&!stopped;index++){
            if(seenCursors.has(page.next_cursor))throw new Error('Approval pagination did not advance.');
            seenCursors.add(page.next_cursor);
            page=await fetchPage(orgId,page.next_cursor,abort.signal);items.push(...page.items);
          }
          if(!stopped){
            onPage({...page,items:[...new Map(items.map(item=>[item.id,item])).values()]});onError(null);
          }
        } catch(error) {
          if(!stopped)onError(error instanceof Error?error.message:'Approval feed unavailable.');
        }
      } while(dirty&&!stopped);
    } finally {running=false;}
  }
  // A slow request must not be perpetually invalidated by its own recovery poll.
  const timer=setInterval(()=>{if(!running)void refresh();},options.pollMs??5000);
  void refresh();
  return {
    refresh:()=>void refresh(),
    loadMore:()=>{pages++;void refresh();},
    stop:()=>{stopped=true;clearInterval(timer);abort.abort();},
  };
}
