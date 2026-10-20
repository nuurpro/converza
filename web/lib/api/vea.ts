import {authHeaders} from '@/lib/api/session';
import {variantMutationRequest,type VeaAsset,type VeaPreset,type VeaVariant} from '@/lib/data/vea';
async function veaRequest<T>(org:string,path:string,init?:RequestInit):Promise<T>{
 const response=await fetch(`/api/backend/api/vea/${encodeURIComponent(org)}${path}`,{...init,headers:await authHeaders({'Content-Type':'application/json',...(init?.headers??{})}),cache:'no-store'});
 const body=await response.json().catch(()=>null);
 if(!response.ok){const detail=body?.detail;throw new Error(typeof detail==='string'?detail:detail?.message??`Video request failed (${response.status}). Refresh before retrying.`);}
 return body as T;
}
export const fetchVeaVariants=(org:string)=>veaRequest<{variants:VeaVariant[]}>(org,'/variants');
export const fetchVeaPresets=(org:string)=>veaRequest<{presets:VeaPreset[]}>(org,'/presets');
export function fetchVeaAssets(org:string,productId?:string,language?:string){const params=new URLSearchParams();if(productId)params.set('product_id',productId);if(language)params.set('language',language);return veaRequest<{assets:VeaAsset[]}>(org,`/assets?${params}`);}
export const createVeaVariant=(org:string,campaign:{id:string;revision:number},presetId:string,key:string)=>veaRequest<VeaVariant>(org,'/variants',{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({campaign_id:campaign.id,expected_revision:campaign.revision,preset_id:presetId})});
export function mutateVeaVariant(org:string,variant:VeaVariant,action:'swap'|'retry',key:string,extra?:Record<string,string>){const request=variantMutationRequest(org,variant,action,key,extra);return veaRequest<VeaVariant>(org,request.path.slice(`/api/vea/${encodeURIComponent(org)}`.length),request.init);}
