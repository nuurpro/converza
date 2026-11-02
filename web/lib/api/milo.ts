import {authenticatedFetch} from '@/lib/api/session';
import type {DirectorSnapshot,DirectorEditPreview} from '@/lib/data/director';
import {scriptDecisionRequest,type MiloBrand,type MiloCampaign,type MiloJob,type MiloScene,type MiloSettings} from '@/lib/data/milo';
export interface MiloSource {id:string;revision:number;kind:string;title:string;content:string;product_id?:string;}
export async function miloRequest<T>(orgId:string,path:string,init?:RequestInit):Promise<T>{
 const headers=new Headers(init?.headers);headers.set('Content-Type','application/json');
 const response=await authenticatedFetch(`/api/backend/api/milo/${encodeURIComponent(orgId)}${path}`,{...init,headers});
 const body=await response.json().catch(()=>null);
 if(!response.ok){
  const detail=body?.detail;
  const message=typeof detail==='string'?detail:detail?.message;
  const violations=Array.isArray(detail?.violations)?detail.violations.filter((value:unknown)=>typeof value==='string'):[];
  const validation=Array.isArray(detail)?detail.map((value:{msg?:string})=>value.msg).filter(Boolean):[];
  throw new Error([message,...violations,...validation].filter(Boolean).join(' · ')||`Milo request failed (${response.status}). Refresh before retrying a decision.`);
 }
 return body as T;
}
export const fetchMiloCampaigns=(orgId:string)=>miloRequest<{campaigns:MiloCampaign[]}>(orgId,'/campaigns');
const directorPath=(campaignId:string)=>`/campaigns/${encodeURIComponent(campaignId)}/director`;
export const fetchMiloDirector=(org:string,campaignId:string)=>miloRequest<DirectorSnapshot>(org,directorPath(campaignId));
export const approveMiloDirectorNarration=(org:string,campaignId:string,revision:number,key:string)=>miloRequest<unknown>(org,`${directorPath(campaignId)}/storyboard/approve`,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({expected_revision:revision})});
export const recoverMiloDirector=(org:string,campaignId:string,runId:string,revision:number,key:string)=>miloRequest<unknown>(org,`${directorPath(campaignId)}/recover`,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({run_id:runId,expected_revision:revision})});
export const previewMiloDirectorEdit=(org:string,campaignId:string,directive:string,revision:number)=>miloRequest<DirectorEditPreview>(org,`${directorPath(campaignId)}/edits/preview`,{method:'POST',body:JSON.stringify({directive,expected_revision:revision})});
export const applyMiloDirectorEdit=(org:string,campaignId:string,previewId:string,revision:number,key:string)=>miloRequest<unknown>(org,`${directorPath(campaignId)}/edits`,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({preview_id:previewId,expected_revision:revision})});
export const fetchMiloJobs=(orgId:string)=>miloRequest<{jobs:MiloJob[]}>(orgId,'/jobs');
export const fetchMiloSettings=(orgId:string)=>miloRequest<MiloSettings>(orgId,'/settings');
export const saveMiloSettings=(orgId:string,settings:MiloSettings)=>miloRequest<MiloSettings>(orgId,'/settings',{method:'PUT',body:JSON.stringify(settings)});
export const fetchMiloBrand=(orgId:string)=>miloRequest<MiloBrand>(orgId,'/brand');
export const saveMiloBrand=(orgId:string,brand:MiloBrand)=>miloRequest<MiloBrand>(orgId,'/brand',{method:'PUT',body:JSON.stringify(brand)});
export const fetchMiloSources=(orgId:string)=>miloRequest<{sources:MiloSource[]}>(orgId,'/proof-sources');
export const createMiloCampaign=(orgId:string,prompt:string,language:string,key:string,productId?:string)=>miloRequest<MiloCampaign>(orgId,'/campaigns',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({prompt,...(language?{language}:{}),...(productId?{product_id:productId}:{})})});
export function decideMiloScript(orgId:string,campaign:MiloCampaign,action:'edit'|'approve'|'reject',key:string,scenes?:MiloScene[]){
 const request=scriptDecisionRequest(orgId,campaign,action,key,scenes);
 return miloRequest<MiloCampaign>(orgId,request.path.slice(`/api/milo/${encodeURIComponent(orgId)}`.length),request.init);
}
export const retryMiloJob=(orgId:string,id:string,key:string)=>miloRequest<MiloJob>(orgId,`/jobs/${encodeURIComponent(id)}/retry`,{method:'POST',headers:{'Idempotency-Key':key},body:'{}'});

export const reconcileMiloJob=(orgId:string,id:string,taskId:string,key:string)=>miloRequest<MiloJob>(orgId,`/jobs/${encodeURIComponent(id)}/reconcile`,{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({task_id:taskId})});
