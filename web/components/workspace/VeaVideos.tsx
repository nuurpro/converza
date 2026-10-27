"use client";

import {useEffect,useRef,useState,type FormEvent} from 'react';
import {VeaPreview} from '@/components/workspace/AgentWorkspace';
import {useMiloOrg} from '@/lib/hooks/useMiloOrg';
import {useWorkspace} from '@/lib/hooks/useWorkspace';
import {fetchMiloCampaigns} from '@/lib/api/milo';
import {resolveHitlDraft} from '@/lib/api/workspace';
import {createVeaVariant,fetchVeaAssets,fetchVeaPresets,fetchVeaVariants,mutateVeaVariant} from '@/lib/api/vea';
import {downloadVideo,replacementAssets,videoCapabilities,type VeaAsset,type VeaPreset,type VeaVariant} from '@/lib/data/vea';
import type {MiloCampaign} from '@/lib/data/milo';
import type {DraftRow} from '@/lib/data/workflow';

const input='mt-1 w-full rounded-lg border border-border bg-white px-3 py-2 text-xs';
const button='rounded-full border border-border px-3 py-2 text-xs disabled:cursor-not-allowed disabled:opacity-50';
export function VeaVideos(){const org=useMiloOrg();return org?<VideoWorkspace key={org} org={org}/>:<p className="px-5 py-4 text-xs text-text-muted">Sign in to review Vea videos.</p>;}
function VideoWorkspace({org}:{org:string}){
 const {drafts}=useWorkspace();
 const [variants,setVariants]=useState<VeaVariant[]>([]),[presets,setPresets]=useState<VeaPreset[]>([]),[campaigns,setCampaigns]=useState<MiloCampaign[]>([]);
 const [campaignId,setCampaignId]=useState(''),[presetId,setPresetId]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState(''),[loaded,setLoaded]=useState(false),[busy,setBusy]=useState(false);
 const alive=useRef(false),sequence=useRef(0),lock=useRef(false),keys=useRef(new Map<string,string>());
 async function refresh(){
  const request=++sequence.current;
  const results=await Promise.allSettled([fetchVeaVariants(org),fetchVeaPresets(org),fetchMiloCampaigns(org)]);
  if(!alive.current||request!==sequence.current)return;
  const [videos,recipes,scripts]=results;
  if(videos.status==='fulfilled'){setVariants(videos.value.variants);setLoaded(true);}
  if(recipes.status==='fulfilled')setPresets(recipes.value.presets);
  if(scripts.status==='fulfilled')setCampaigns(scripts.value.campaigns.filter(c=>c.script_status==='approved'&&!!c.artifact));
  const errors=results.flatMap(result=>result.status==='rejected'?[result.reason instanceof Error?result.reason.message:'Video refresh failed']:[]);
  setError(errors.join(' · '));
 }
 useEffect(()=>{alive.current=true;void refresh();const timer=setInterval(()=>void refresh(),5000);return()=>{alive.current=false;sequence.current++;clearInterval(timer);};},[org]); // eslint-disable-line react-hooks/exhaustive-deps
 async function perform(signature:string,work:(key:string)=>Promise<unknown>,message:string){if(lock.current)return;lock.current=true;setBusy(true);setError('');setNotice('');let key=keys.current.get(signature);if(!key){key=crypto.randomUUID();keys.current.set(signature,key);}try{await work(key);keys.current.delete(signature);if(alive.current){setNotice(message);await refresh();}}catch(failure){if(alive.current){setError(failure instanceof Error?failure.message:'Video action failed');await refresh();}}finally{lock.current=false;if(alive.current)setBusy(false);}}
 const selectedCampaign=campaigns.find(c=>c.id===campaignId),selectedPreset=presets.find(p=>p.id===presetId);
 function create(event:FormEvent){event.preventDefault();if(!selectedCampaign||!selectedPreset)return;void perform(JSON.stringify(['create',campaignId,selectedCampaign.revision,presetId]),key=>createVeaVariant(org,selectedCampaign,presetId,key),'Variant queued. Review the finished video before exporting.');}
 function decide(variant:VeaVariant,draft:DraftRow,action:'approve'|'reject'){void perform(`${action}:${draft.id}:${draft.revision}`,async key=>{const result=await resolveHitlDraft(draft.id,action,undefined,draft.revision,key);if(alive.current&&action==='approve'&&result.status==='APPROVED'&&!result.superseded_by&&!result.vea_artifact?.superseded&&variant.artifact)downloadVideo(result.vea_artifact??variant.artifact);},action==='approve'?'Video approved for export.':'Video rejected.');}
 return <section className="mx-auto w-full max-w-3xl shrink-0 space-y-4 px-5 py-5 font-workspace-sans">
  <div className="rounded-xl border border-border p-4"><h2 className="text-sm font-medium">Vea video studio</h2><p className="mt-2 text-xs text-text-muted">Approved Milo scripts become branded vertical videos. Review every variant before exporting.</p>
   <form onSubmit={create} className="mt-3 space-y-3"><label className="block text-xs">Approved script<select className={input} value={campaignId} onChange={event=>setCampaignId(event.target.value)} required><option value="">Select an approved Milo script</option>{campaigns.map(c=><option key={c.id} value={c.id}>{c.artifact?.trigger_reason??c.id} · revision {c.revision}</option>)}</select></label>
    <label className="block text-xs">Preset<select className={input} value={presetId} onChange={event=>setPresetId(event.target.value)} required><option value="">Select a preset</option>{presets.map(p=><option key={p.id} value={p.id}>{p.name} · v{p.version}</option>)}</select></label>
    <button className={`${button} bg-black text-white`} disabled={busy||!selectedCampaign||!selectedPreset}>Render variant</button>
   </form>{loaded&&campaigns.length===0&&<p className="mt-3 text-xs text-text-muted">Approve a script in <a href="/agents/milo" className="underline">Milo campaigns</a> to request a variant.</p>}
  </div>
  {error&&<p role="alert" className="rounded-lg border border-border p-3 text-xs text-error">{error}</p>}{notice&&<p role="status" className="text-xs">{notice}</p>}
  {!loaded&&!error&&<p role="status" className="text-xs">Loading video workspace…</p>}{loaded&&variants.length===0&&<p className="text-xs text-text-muted">No videos yet. Milo approval automatically queues your first D2C cut.</p>}
  {variants.map(variant=>{const draft=variant.draft_id?drafts[variant.draft_id]:undefined;const campaign=campaigns.find(c=>c.id===variant.campaign_id);return <VeaVariantCard key={`${variant.id}:${variant.revision}`} org={org} variant={variant} draft={draft?.org_id===org?draft:undefined} campaign={campaign} busy={busy} onDecide={action=>{if(draft?.org_id===org)decide(variant,draft,action);}} onRetry={()=>void perform(`retry:${variant.id}:${variant.revision}`,key=>mutateVeaVariant(org,variant,'retry',key),'Retry queued.')} onSwap={(segmentId,assetId)=>void perform(`swap:${variant.id}:${variant.revision}:${segmentId}:${assetId}`,key=>mutateVeaVariant(org,variant,'swap',key,{segment_id:segmentId,asset_id:assetId}),'Replacement queued. The new cut requires fresh approval.')}/>;})}
 </section>;
}
export function VeaVariantCard({org,variant,draft,campaign,busy,onDecide,onRetry,onSwap}:{org:string;variant:VeaVariant;draft?:DraftRow;campaign?:MiloCampaign;busy:boolean;onDecide:(action:'approve'|'reject')=>void;onRetry:()=>void;onSwap:(segmentId:string,assetId:string)=>void}){
 const capabilities=videoCapabilities(variant,draft),manifest=variant.composition_manifest??variant.artifact?.composition_manifest,segments=variant.segments??manifest?.segments??[];
 const [showSwap,setShowSwap]=useState(false),[assets,setAssets]=useState<VeaAsset[]>([]),[assetId,setAssetId]=useState(''),[segmentId,setSegmentId]=useState(''),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const eligibleAssets=replacementAssets(assets,segments.find(segment=>segment.segment_id===segmentId));
 const product=variant.product_id??manifest?.product_id??campaign?.artifact?.proof_references.find(proof=>proof.product_id)?.product_id,language=variant.language??manifest?.language??campaign?.artifact?.language;
 useEffect(()=>{if(!showSwap)return;let active=true;setLoading(true);setError('');void fetchVeaAssets(org,product,language).then(result=>{if(active)setAssets(result.assets);}).catch(failure=>{if(active)setError(failure instanceof Error?failure.message:'Asset lookup failed');}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[org,product,language,showSwap]);
 return <article id={`video-${variant.id}`} className="space-y-3 rounded-xl border border-border p-4 text-xs">
  <div className="flex flex-wrap justify-between gap-2"><h3 className="text-sm font-medium">{variant.preset_id}{variant.is_default?' · automatic cut':''}</h3><span>Revision {variant.revision} · {variant.status}</span></div>
  {variant.artifact&&<VeaPreview artifact={variant.artifact}/>}
  {['queued','rendering'].includes(variant.status)&&<p role="status">{variant.status==='queued'?'Waiting for renderer':'Rendering narration, clips and captions…'}</p>}
  {variant.error&&<p role="alert" className="whitespace-pre-wrap text-error">{variant.error}</p>}
  {(draft?.superseded_by||variant.artifact?.superseded||draft?.vea_artifact?.superseded)&&<p>This video was replaced by a new revision. Review its replacement.</p>}
  {draft?.status==='REJECTED'&&<p>Video rejected</p>}
  <div className="flex flex-wrap gap-2">
   {capabilities.canApprove&&<><button className={`${button} bg-black text-white`} disabled={busy} onClick={()=>onDecide('approve')}>Approve &amp; Export</button><button className={button} disabled={busy} onClick={()=>onDecide('reject')}>Reject</button></>}
   {capabilities.canExport&&variant.artifact&&<button className={button} disabled={busy} onClick={()=>downloadVideo(variant.artifact!)}>Download MP4</button>}
   {capabilities.canSwap&&segments.length>0&&<button className={button} disabled={busy} onClick={()=>setShowSwap(value=>!value)}>Swap Clip &amp; Re-render</button>}
   {capabilities.canRetry&&<button className={button} disabled={busy} onClick={onRetry}>Retry render</button>}
  </div>
  {capabilities.canExport&&<p className="text-text-muted">Approved for export</p>}
  {showSwap&&capabilities.canSwap&&<form onSubmit={event=>{event.preventDefault();if(segmentId&&eligibleAssets.some(asset=>asset.id===assetId))onSwap(segmentId,assetId);}} className="space-y-3 border-t border-border pt-3">
   <label className="block">Timeline segment<select className={input} required value={segmentId} onChange={event=>setSegmentId(event.target.value)}><option value="">Choose a clip to replace</option>{segments.map(segment=><option key={segment.segment_id} value={segment.segment_id}>{(segment.start_ms/1000).toFixed(1)}–{(segment.end_ms/1000).toFixed(1)}s · {segment.asset_id}</option>)}</select></label>
   <label className="block">Eligible replacement<select className={input} required value={assetId} onChange={event=>setAssetId(event.target.value)}><option value="">Choose an asset</option>{eligibleAssets.map(asset=><option key={asset.id} value={asset.id}>{asset.id} · {Array.isArray(asset.tags)?asset.tags.join(', '):Object.values(asset.tags).flat().join(', ')}</option>)}</select></label>
   {loading&&<p role="status">Loading eligible clips…</p>}{error&&<p role="alert" className="text-error">{error}</p>}{!segmentId&&<p>Choose a timeline segment to see clips long enough to replace it.</p>}{segmentId&&!loading&&!error&&eligibleAssets.length===0&&<p>No eligible clips. Add matching, rights-confirmed video clips long enough for this segment to your Brand Asset Vault.</p>}
   <p className="text-text-muted">Narration stays the same. The replacement video needs a new approval.</p><button className={button} disabled={busy||loading||!segmentId||!eligibleAssets.some(asset=>asset.id===assetId)}>Render replacement</button>
  </form>}
 </article>;
}
