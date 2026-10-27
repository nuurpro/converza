"use client";

import {useEffect,useRef,useState,type FormEvent} from 'react';
import {campaignCapabilities,keepScriptEditor,type MiloCampaign,type MiloJob,type MiloScene,type MiloSettings,type ScriptEditor} from '@/lib/data/milo';
import {createMiloCampaign,decideMiloScript,fetchMiloCampaigns,fetchMiloJobs,fetchMiloSettings,retryMiloJob,reconcileMiloJob,saveMiloSettings} from '@/lib/api/milo';
import {useMiloOrg} from '@/lib/hooks/useMiloOrg';

const input='mt-1 w-full rounded-lg border border-border bg-white px-3 py-2 text-xs';
const button='rounded-full border border-border px-3 py-2 text-xs disabled:cursor-not-allowed disabled:opacity-50';
const languageOptions=<><option value="en">English</option><option value="ru">Russian</option><option value="uz">Uzbek</option></>;

export function MiloCampaigns(){
 const org=useMiloOrg();
 return org?<CampaignWorkspace key={org} org={org}/>:<p className="px-5 py-4 text-xs text-text-muted">Sign in to review Milo campaigns.</p>;
}
function CampaignWorkspace({org}:{org:string}){
 const [campaigns,setCampaigns]=useState<MiloCampaign[]>([]),[jobs,setJobs]=useState<MiloJob[]>([]);
 const [prompt,setPrompt]=useState(''),[language,setLanguage]=useState(''),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false);
 const [loaded,setLoaded]=useState(false);
 const keys=useRef(new Map<string,string>()),alive=useRef(true),sequence=useRef(0),actionLock=useRef(false);
 function keyFor(signature:string){let key=keys.current.get(signature);if(!key){key=crypto.randomUUID();keys.current.set(signature,key);}return key;}
 async function refresh(){
  const request=++sequence.current;
  try{const [result,work]=await Promise.all([fetchMiloCampaigns(org),fetchMiloJobs(org)]);
   if(alive.current&&request===sequence.current){setCampaigns(result.campaigns);setJobs(work.jobs);setLoaded(true);}
  }catch(failure){if(alive.current)setError(failure instanceof Error?failure.message:'Campaign refresh failed');}
 }
 useEffect(()=>{alive.current=true;void refresh();const timer=setInterval(()=>void refresh(),5000);return()=>{alive.current=false;clearInterval(timer);};},[org]); // eslint-disable-line react-hooks/exhaustive-deps
 async function perform<T,>(signature:string,work:(key:string)=>Promise<T>,message:string):Promise<T|null>{
  if(actionLock.current)return null;actionLock.current=true;setBusy(true);setError('');setNotice('');
  try{const result=await work(keyFor(signature));keys.current.delete(signature);if(alive.current){setNotice(message);await refresh();}return result;}
  catch(failure){if(alive.current){setError(failure instanceof Error?failure.message:'Milo action failed');await refresh();}return null;}
  finally{actionLock.current=false;if(alive.current)setBusy(false);}
 }
 function generate(event:FormEvent){event.preventDefault();void perform(JSON.stringify(['generate',prompt,language]),key=>createMiloCampaign(org,prompt,language,key),'Campaign queued. Milo is checking buyer evidence and brand proof.');}
 async function decide(campaign:MiloCampaign,action:'edit'|'approve'|'reject',scenes?:MiloScene[]){
  return perform(JSON.stringify([campaign.id,campaign.revision,action,scenes]),key=>decideMiloScript(org,campaign,action,key,scenes),action==='edit'?'Script saved for a new compliance check. Review it before approving.':action==='approve'?'Script approved. Vea build queued.':'Script rejected.');
 }
 return <section className="mx-auto w-full max-w-3xl shrink-0 space-y-4 px-5 py-5 font-workspace-sans">
  <div className="rounded-xl border border-border p-4"><h2 className="text-sm font-medium">Evidence-backed campaigns</h2><p className="mt-2 text-xs text-text-muted">Turn buyer objections into hooks, scripts and captions. Review each script before Vea builds the video.</p>
   <form onSubmit={generate} className="mt-3 space-y-3"><label className="block text-xs">Campaign direction<textarea className={input} rows={2} maxLength={8000} value={prompt} onChange={event=>setPrompt(event.target.value)} placeholder="Use recent durability objections for our everyday buyers."/></label>
    <div className="flex flex-wrap items-end gap-3"><label className="text-xs">Campaign language<select className={input} value={language} onChange={event=>setLanguage(event.target.value)}><option value="">Brand default</option>{languageOptions}</select></label>
    <button disabled={busy} className={`${button} bg-black text-white`}>{busy?'Working…':'Generate campaign'}</button></div>
   </form>
  </div>
  <MiloAutomation org={org}/>
  {error&&<p role="alert" className="rounded-lg border border-border p-3 text-xs text-error">{error}</p>}
  {notice&&<p role="status" className="rounded-lg border border-border p-3 text-xs">{notice}</p>}
  {!loaded&&!error&&<p role="status" className="text-xs text-text-muted">Loading campaigns…</p>}
  {loaded&&campaigns.length===0&&<p className="text-xs text-text-muted">No campaigns yet. Generate one from current buyer evidence or enable an automatic trigger.</p>}
  {campaigns.map(campaign=><CampaignCard key={campaign.id} campaign={campaign} busy={busy} onDecide={decide}/>)}
  {jobs.filter(job=>job.status==='failed'||job.status==='ambiguous').map(job=><JobRecovery key={job.id} job={job} busy={busy} onRetry={()=>perform(`retry:${job.id}`,key=>retryMiloJob(org,job.id,key),'Retry queued.')} onReconcile={taskId=>perform(`reconcile:${job.id}:${taskId}`,key=>reconcileMiloJob(org,job.id,taskId,key),'Original provider task linked. Vea is checking its status.')}/>)}
 </section>;
}
export function CampaignCard({campaign,busy,onDecide}:{campaign:MiloCampaign;busy:boolean;onDecide:(campaign:MiloCampaign,action:'edit'|'approve'|'reject',scenes?:MiloScene[])=>Promise<MiloCampaign|null>}){
 const [editor,setEditor]=useState<ScriptEditor>(()=>keepScriptEditor(undefined,campaign));
 useEffect(()=>setEditor(current=>keepScriptEditor(current,campaign)),[campaign]);
 const artifact=campaign.artifact,stale=editor.revision!==campaign.revision,videoUrl=campaign.result?.video_url??campaign.build_result?.video_url;
 const capabilities=campaignCapabilities(campaign,editor.dirty,stale);
 function changeScene(index:number,field:keyof MiloScene,value:string){setEditor(current=>({...current,dirty:true,scenes:current.scenes.map((scene,i)=>i===index?{...scene,[field]:value}:scene)}));}
 return <article id={`campaign-${campaign.id}`} className="space-y-4 rounded-xl border border-border p-4 text-xs">
  <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-medium">{artifact?.trigger_reason??`${campaign.trigger} campaign`}</h3><span className="font-workspace-mono text-[10px] text-text-muted">Revision {campaign.revision} · {campaign.status.replaceAll('_',' ')}</span></div>
  <p className="text-text-muted">Trigger: {campaign.trigger} · Script: {campaign.script_status}{artifact?` · ${artifact.language} · ${artifact.target_persona.name}`:''}</p>
  {campaign.last_error&&<p role="alert" className="text-error">{campaign.last_error}</p>}
  {campaign.missing_evidence?.length>0&&<div className="rounded-lg bg-milo-dim p-3"><h4 className="font-medium">Evidence needed</h4><ul className="mt-2 list-disc space-y-1 pl-4">{campaign.missing_evidence.map((item,index)=><li key={index}>{item}</li>)}</ul><a className="mt-2 inline-block underline" href="/settings/brand">Update Brand Passport proof and personas</a></div>}
  {artifact&&<>
   <details><summary className="cursor-pointer font-medium">Buyer evidence and verified proof</summary><p className="mt-2 text-text-muted">{artifact.target_persona.description} · Brand revision {artifact.brand_revision}</p>
    {artifact.buyer_quotes.map((quote,index)=><blockquote key={index} className="mt-3 border-l-2 border-milo pl-3"><p className="whitespace-pre-wrap">{quote.text}</p><cite className="break-all text-[10px] not-italic text-text-muted">Buyer source: {quote.source_id}</cite></blockquote>)}
    {artifact.proof_references.map((proof,index)=><div key={index} className="mt-3"><p className="whitespace-pre-wrap">{proof.quote}</p><p className="break-all text-[10px] text-text-muted">Brand source: {proof.source_id} · revision {proof.revision}</p></div>)}
   </details>
   <div><h4 className="font-medium">Hooks</h4>{artifact.hooks.map(hook=><p key={hook.framework} className="mt-2 whitespace-pre-wrap"><span className="font-medium">{hook.framework==='A'?'A · Pain question':hook.framework==='B'?'B · Proof / mechanism':'C · Low-friction offer'}:</span> {hook.text}</p>)}</div>
   <div className="border-y border-border py-3"><h4 className="font-medium">Video script</h4><p className="mt-1 text-text-muted">Saving changes creates a new revision for review. Approval queues this script for Vea.</p>
    {editor.scenes.map((scene,index)=><fieldset key={index} disabled={busy||!capabilities.canEdit} className="mt-3 space-y-2"><legend className="font-medium">Scene {index+1}</legend>
     {(['spoken_narration','visual_broll_cues','on_screen_text'] as const).map(field=><label key={field} className="block text-text-secondary">{field==='spoken_narration'?'Spoken narration':field==='visual_broll_cues'?'Visual / B-roll cues':'On-screen text'}<textarea className={input} rows={2} maxLength={field==='on_screen_text'?500:1500} value={scene[field]} onChange={event=>changeScene(index,field,event.target.value)}/></label>)}
    </fieldset>)}
    {stale&&<p role="alert" className="mt-3 text-milo">A newer script revision is available. Your edits are preserved. Discard them to review the current revision.</p>}
    {editor.dirty&&<div className="mt-3 flex flex-wrap gap-2"><button className={button} disabled={busy||stale||!capabilities.canEdit||editor.scenes.some(scene=>!scene.spoken_narration.trim()||!scene.visual_broll_cues.trim())} onClick={()=>void onDecide({...campaign,revision:editor.revision},'edit',editor.scenes).then(saved=>{if(saved)setEditor(keepScriptEditor(undefined,saved));})}>Save script for review</button><button className={button} disabled={busy} onClick={()=>setEditor(keepScriptEditor(undefined,campaign))}>Discard edits</button></div>}
   </div>
   <div><h4 className="font-medium">Brand compliance: {campaign.compliance.passed?'Passed':'Needs attention'}</h4>{campaign.compliance.violations.map((violation,index)=><p key={index} className="mt-1 text-error">{violation}</p>)}</div>
   <div className="flex flex-wrap gap-2"><button className={`${button} bg-black text-white`} disabled={busy||!capabilities.canApprove} onClick={()=>void onDecide(campaign,'approve')}>Approve script & queue Vea</button><button className={button} disabled={busy||!capabilities.canReject} onClick={()=>void onDecide(campaign,'reject')}>Reject script</button></div>
   <details><summary className="cursor-pointer font-medium">Social captions</summary>{Object.entries(artifact.social_captions).map(([channel,text])=><div key={channel} className="mt-3"><h4 className="capitalize">{channel}</h4><p className="mt-1 whitespace-pre-wrap text-text-secondary">{text}</p></div>)}</details>
  </>}
  {campaign.build_status&&<p role="status" className="rounded-lg bg-[#f4f4f5] p-3">Vea build: {campaign.build_status}{campaign.build_status==='ambiguous'?' · Checking provider confirmation before retry.':''}{campaign.build_status==='completed'&&videoUrl&&<a className="ml-3 underline" href={safeVideoUrl(videoUrl)} target="_blank" rel="noopener noreferrer">Review rendered video</a>}</p>}
 </article>;
}
function safeVideoUrl(value:string){try{const url=new URL(value);return url.protocol==='https:'||url.protocol==='http:'?url.href:undefined;}catch{return undefined;}}
function MiloAutomation({org}:{org:string}){
 const [settings,setSettings]=useState<MiloSettings|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 useEffect(()=>{let active=true;void fetchMiloSettings(org).then(value=>{if(active)setSettings(value);}).catch(error=>{if(active)setMessage(error.message);});return()=>{active=false;};},[org]);
 async function save(event:FormEvent){event.preventDefault();if(!settings||busy)return;setBusy(true);setMessage('');try{setSettings(await saveMiloSettings(org,settings));setMessage('Automation settings saved.');}catch(error){setMessage(error instanceof Error?error.message:'Save failed');}finally{setBusy(false);}}
 return <details className="rounded-xl border border-border p-4 text-xs"><summary className="cursor-pointer font-medium">Daily and objection-spike triggers</summary>{message&&<p role="status" className="mt-3">{message}</p>}{settings&&<form onSubmit={save} className="mt-3 space-y-3">
  <label className="flex items-center gap-2"><input type="checkbox" checked={settings.daily_enabled} onChange={event=>setSettings({...settings,daily_enabled:event.target.checked})}/>Generate a daily campaign</label>
  <div className="grid grid-cols-2 gap-3"><label>Daily hour (0–23)<input className={input} type="number" min={0} max={23} required value={settings.daily_hour} onChange={event=>setSettings({...settings,daily_hour:Number(event.target.value)})}/></label><label>Timezone<input className={input} required value={settings.timezone} onChange={event=>setSettings({...settings,timezone:event.target.value})}/></label></div>
  <label className="flex items-center gap-2"><input type="checkbox" checked={settings.spike_enabled} onChange={event=>setSettings({...settings,spike_enabled:event.target.checked})}/>Generate on an objection spike</label>
  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">{([{field:'spike_threshold',label:'Distinct buyer conversations',min:1},{field:'window_days',label:'Evidence window (days)',min:1},{field:'cooldown_hours',label:'Cooldown (hours)',min:1}] as const).map(({field,label,min})=><label key={field}>{label}<input className={input} type="number" min={min} required value={settings[field]} onChange={event=>setSettings({...settings,[field]:Number(event.target.value)})}/></label>)}</div>
  <button className={button} disabled={busy}>{busy?'Saving…':'Save trigger settings'}</button>
 </form>}</details>;
}

export function JobRecovery({job,busy,onRetry,onReconcile}:{job:MiloJob;busy:boolean;onRetry:()=>Promise<unknown>;onReconcile:(taskId:string)=>Promise<unknown>}){
 const [taskId,setTaskId]=useState('');
 const uncertain=job.status==='ambiguous'||(!job.payload?.provider_task_id&&!job.payload?.task_id&&['submitting','ambiguous','submission_started'].includes(job.payload?.submission_state??''));
 return <div className="rounded-xl border border-border p-3 text-xs"><p>{job.kind??'Milo job'} · {job.status}</p><p className="mt-1 text-error">{job.last_error}</p>
  {uncertain?<form className="mt-3 space-y-2" onSubmit={event=>{event.preventDefault();if(taskId.trim())void onReconcile(taskId.trim());}}><p className="text-text-muted">Provider confirmation is uncertain. Link the original provider task to check its status before another submission.</p><label className="block">Original provider task ID<input className={input} required maxLength={200} pattern="[A-Za-z0-9_-]+" value={taskId} onChange={event=>setTaskId(event.target.value)}/></label><button className={button} disabled={busy||!taskId.trim()}>Link original provider task</button></form>:<button disabled={busy} className={`${button} mt-2`} onClick={()=>void onRetry()}>Retry job</button>}
 </div>;
}
