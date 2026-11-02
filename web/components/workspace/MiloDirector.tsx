"use client";
import {useEffect,useRef,useState,type FormEvent} from 'react';
import {fetchMiloDirector,previewMiloDirectorEdit,applyMiloDirectorEdit,approveMiloDirectorNarration,recoverMiloDirector} from '@/lib/api/milo';
import {subscribeWorkspace} from '@/lib/api/workspace';
import {canApplyDirectorEdit,directorStatus,sceneNumbers,type DirectorSnapshot,type DirectorEditPreview} from '@/lib/data/director';

const button='rounded-full border border-border px-3 py-2 text-xs disabled:opacity-50';
// Campaign cards share one authenticated stream so a large campaign list cannot
// exhaust the browser's per-origin EventSource connection limit.
const progressListeners=new Set<{refresh:()=>void;error:(message:string|null)=>void}>();
let stopProgressStream:(()=>void)|undefined;
function subscribeProgress(refresh:()=>void,error:(message:string|null)=>void){
 const listener={refresh,error};progressListeners.add(listener);
 if(!stopProgressStream)stopProgressStream=subscribeWorkspace(event=>{
  if(event.type==='snapshot'||event.type==='agent_run_step')for(const item of progressListeners)item.refresh();
 },message=>{for(const item of progressListeners)item.error(message);});
 return()=>{progressListeners.delete(listener);if(progressListeners.size===0){stopProgressStream?.();stopProgressStream=undefined;}};
}
export function MiloDirector({org,campaignId,scriptStatus,onChanged}:{org:string;campaignId:string;scriptStatus:string;onChanged:()=>void}){
 const [snapshot,setSnapshot]=useState<DirectorSnapshot|null>(null),[error,setError]=useState(''),[streamError,setStreamError]=useState(''),[statusError,setStatusError]=useState('');
 const [directive,setDirective]=useState(''),[preview,setPreview]=useState<DirectorEditPreview|null>(null),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
 const alive=useRef(false),sequence=useRef(0),lock=useRef(false),keys=useRef(new Map<string,string>());
 async function refresh(){const request=++sequence.current;try{const value=await fetchMiloDirector(org,campaignId);if(alive.current&&request===sequence.current){setSnapshot(value);setStatusError('');}}catch(failure){if(alive.current&&request===sequence.current)setStatusError(failure instanceof Error?failure.message:'Production status unavailable');}}
 useEffect(()=>{
  alive.current=true;void refresh();
  const timer=setInterval(()=>void refresh(),10000);
  const unsubscribe=subscribeProgress(()=>void refresh(),message=>{if(alive.current)setStreamError(message??'');});
  return()=>{alive.current=false;sequence.current++;if(timer!==undefined)clearInterval(timer);unsubscribe();};
 },[org,campaignId]); // eslint-disable-line react-hooks/exhaustive-deps
 async function edit(event:FormEvent){event.preventDefault();const revision=snapshot?.storyboard?.revision;if(lock.current||revision===undefined||!directive.trim())return;lock.current=true;setBusy(true);setError('');setPreview(null);setNotice('');try{const value=await previewMiloDirectorEdit(org,campaignId,directive.trim(),revision);if(alive.current)setPreview(value);}catch(failure){if(alive.current)setError(failure instanceof Error?failure.message:'Edit preview failed');}finally{lock.current=false;if(alive.current)setBusy(false);}}
 async function apply(){if(lock.current||!canApplyDirectorEdit(preview,snapshot?.storyboard?.revision)||!preview)return;lock.current=true;setBusy(true);setError('');const signature=preview.preview_id;let key=keys.current.get(signature);if(!key){key=crypto.randomUUID();keys.current.set(signature,key);}try{await applyMiloDirectorEdit(org,campaignId,preview.preview_id,preview.base_revision,key);if(alive.current){setNotice(preview.narration_changed?'Edits saved. Review and approve the updated narration below before production resumes.':'Edits saved. Milo will reuse unchanged verified scenes and rebuild the master automatically.');setPreview(null);setDirective('');await refresh();onChanged();}}catch(failure){if(alive.current){setError(failure instanceof Error?failure.message:'Could not apply edits');await refresh();}}finally{lock.current=false;if(alive.current)setBusy(false);}}
 async function approveNarration(){const storyboard=snapshot?.storyboard;if(lock.current||scriptStatus!=='approved'||!storyboard||storyboard.narration_approved)return;lock.current=true;setBusy(true);setError('');const signature=`narration:${storyboard.revision}`;let key=keys.current.get(signature);if(!key){key=crypto.randomUUID();keys.current.set(signature,key);}try{await approveMiloDirectorNarration(org,campaignId,storyboard.revision,key);if(alive.current){setNotice('Narration approved. Autonomous production can resume.');await refresh();onChanged();}}catch(failure){if(alive.current){setError(failure instanceof Error?failure.message:'Narration approval failed');await refresh();}}finally{lock.current=false;if(alive.current)setBusy(false);}}
 async function recover(){
  const run=snapshot?.run,storyboard=snapshot?.storyboard;
  if(lock.current||!run||!storyboard?.narration_approved||!['BLOCKED','RECONCILING_SUBMISSION'].includes(run.status))return;
  lock.current=true;setBusy(true);setError('');setNotice('');
  const signature=`recover:${run.id}:${storyboard.revision}:${run.attempt}`;
  let key=keys.current.get(signature);if(!key){key=crypto.randomUUID();keys.current.set(signature,key);}
  try{await recoverMiloDirector(org,campaignId,run.id,storyboard.revision,key);keys.current.delete(signature);if(alive.current){setNotice('Recovery requested. Milo will reconcile existing submissions before continuing.');await refresh();onChanged();}}
  catch(failure){if(alive.current){setError(failure instanceof Error?failure.message:'Recovery failed');await refresh();}}
  finally{lock.current=false;if(alive.current)setBusy(false);}
 }
 if(!snapshot?.storyboard&&!snapshot?.run)return statusError?<div className="rounded-lg border border-border p-3 text-xs"><p role="alert">{statusError}</p><button className={`${button} mt-2`} onClick={()=>void refresh()}>Refresh production status</button></div>:null;
 return <section aria-label="Milo autonomous production" className="space-y-3 rounded-lg border border-border p-3 text-xs">
  <h4 className="font-medium">Milo autonomous director</h4>
  <p className="text-text-muted">Milo checks each scene before starting the next. Your final master review is in the Central Approval Feed.</p>
  {snapshot.run&&<DirectorProgress snapshot={snapshot}/>}
  {snapshot.run&&['BLOCKED','RECONCILING_SUBMISSION'].includes(snapshot.run.status)&&snapshot.storyboard?.narration_approved&&<button className={button} disabled={busy||!!statusError} onClick={()=>void recover()}>{snapshot.run.status==='RECONCILING_SUBMISSION'?'Reconcile original submission':'Resume after resolving issue'}</button>}
  {streamError&&<p role="status">{streamError} Production status refreshes automatically.</p>}
  {statusError&&<p role="alert" className="text-error">{statusError} Showing the last known production state.</p>}
  {error&&<p role="alert" className="text-error">{error}</p>}{notice&&<p role="status">{notice}</p>}
  {snapshot.storyboard&&<>
   {!snapshot.storyboard.narration_approved&&scriptStatus==='approved'&&<div className="space-y-2"><p role="status" className="text-milo">Narration sign-off needed. Read the exact narration before approving revision {snapshot.storyboard.revision}.</p><ol className="space-y-2">{snapshot.storyboard.scenes.map((scene,index)=><li key={scene.scene_index??index} className="whitespace-pre-wrap">Scene {scene.scene_index??index+1}: {scene.narration_chunk??''}</li>)}</ol><button className={button} disabled={busy||!!statusError||snapshot.storyboard.scenes.length===0||snapshot.storyboard.scenes.some(scene=>!scene.narration_chunk?.trim())} onClick={()=>void approveNarration()}>Approve narration</button></div>}
   <form onSubmit={edit}><label className="block">Edit across scenes<textarea className="mt-1 w-full rounded-lg border border-border bg-white px-3 py-2" rows={2} maxLength={8000} disabled={busy} value={directive} onChange={event=>{setDirective(event.target.value);setPreview(null);}} placeholder="Use larger captions in every scene and shorten the final shot."/></label><button className={`${button} mt-2`} disabled={busy||!directive.trim()}>{busy?'Working…':'Preview edit impact'}</button></form>
   {preview&&<DirectorEditImpact preview={preview} revision={snapshot.storyboard.revision} busy={busy} onApply={()=>void apply()}/>}
  </>}
 </section>;
}
export function DirectorProgress({snapshot}:{snapshot:DirectorSnapshot}){
 const run=snapshot.run;if(!run)return null;
 return <div className="space-y-2"><p role="status" aria-live="polite" className="font-medium">{directorStatus(run.status)} · Revision {run.storyboard_revision}</p>
  <p>Scene {Math.min(run.scene_index,run.total_scenes)} of {run.total_scenes} · Attempt {run.attempt} of 3{run.attempt>1?' · Automated targeted retry':''}</p>
  <ol className="space-y-1">{run.scenes.map((scene,index)=><li key={scene.scene_index??index}>Scene {scene.scene_index??index+1}: {directorStatus(scene.status??scene.state??'QUEUED')}{scene.attempt?` · attempt ${scene.attempt}`:''}</li>)}</ol>
  {run.error&&<div role="alert" className="rounded-lg bg-milo-dim p-3"><p className="font-medium">Production needs attention</p><p className="mt-1 whitespace-pre-wrap">{run.error}</p><p className="mt-1">Resolve the reported dependency or asset issue before recovering this run. Later scenes remain paused.</p></div>}
  {run.inspection&&<details><summary className="cursor-pointer">Master inspection evidence</summary><pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(run.inspection,null,2)}</pre><p className="mt-2 text-text-muted">Technical checks preserve approved words, timing and media requirements. Assess visual quality and coherence during final review.</p></details>}
  {run.status==='AWAITING_HITL'&&<a className="inline-block underline" href="/">Review final master in Central Approval Feed</a>}
 </div>;
}
export function DirectorEditImpact({preview,revision,busy,onApply}:{preview:DirectorEditPreview;revision:number;busy:boolean;onApply:()=>void}){
 return <div className="space-y-2 rounded-lg bg-milo-dim p-3"><h5 className="font-medium">Edit impact · Revision {preview.base_revision}</h5><p>Changed scenes: {sceneNumbers(preview.changed_scene_indices)}</p><p>Reusable verified scenes: {sceneNumbers(preview.reusable_scene_indices)}</p><p>{preview.narration_changed?'Narration changes require renewed script sign-off before production resumes.':'Approved narration is preserved. No additional approval is needed to resume production.'}</p>
 {preview.unresolved_instructions.length>0&&<div role="alert"><p>Resolve these instructions before applying:</p><ul className="list-disc pl-4">{preview.unresolved_instructions.map((item,index)=><li key={index}>{item}</li>)}</ul></div>}
 {preview.base_revision!==revision&&<p role="alert">Storyboard changed. Preview the edit again against the current revision.</p>}
 <details><summary className="cursor-pointer">Proposed storyboard</summary><ol className="mt-2 space-y-3">{preview.scenes.map(scene=><li key={scene.scene_index} className="space-y-1"><p className="font-medium">Scene {scene.scene_index} · {scene.target_duration_sec}s</p><p className="whitespace-pre-wrap">Narration: {scene.narration_chunk}</p><p className="whitespace-pre-wrap">Visual: {scene.visual_directive?.prompt}</p>{scene.visual_directive&&<p>Action: {scene.visual_directive.subject_action} · Camera: {scene.visual_directive.camera_movement} · Lighting: {scene.visual_directive.lighting_style}</p>}{scene.overlay_text&&<><p className="whitespace-pre-wrap">Caption: {scene.overlay_text.text}</p><p>{scene.overlay_text.start_sec}–{scene.overlay_text.end_sec}s · {scene.overlay_text.font_family}, {scene.overlay_text.font_size}px · {scene.overlay_text.color} · {scene.overlay_text.position} · {scene.overlay_text.animation}</p></>}</li>)}</ol></details>
 <button className={button} disabled={busy||!canApplyDirectorEdit(preview,revision)} onClick={onApply}>Apply storyboard edits</button></div>;
}
