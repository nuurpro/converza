export interface MiloScene { spoken_narration:string; visual_broll_cues:string; on_screen_text:string; }
export interface MiloPersona { id:string; name:string; description:string; }
export interface MiloProof { id?:string; source_id:string; revision:number; quote:string; product_id?:string; objection_topics?:string[]; }
export interface MiloCampaignArtifact {
 schema_version:1; trigger_reason:string; target_persona:MiloPersona; language:string;
 hooks:{framework:'A'|'B'|'C';text:string}[]; video_script:MiloScene[];
 social_captions:{instagram:string;telegram:string;tiktok:string};
 buyer_quotes:{source_id:string;text:string}[]; proof_references:MiloProof[]; brand_revision:number;
}
export interface MiloCampaign {
 id:string;org_id:string;revision:number;status:'queued'|'generating'|'awaiting_review'|'needs_evidence'|'blocked'|'failed';
 product_id?:string|null;
 trigger:'manual'|'daily'|'spike';artifact:MiloCampaignArtifact|null;compliance:{passed:boolean;violations:string[]};missing_evidence:string[];
 script_status:'pending'|'approved'|'rejected';build_status:null|'queued'|'running'|'failed'|'ambiguous'|'completed';
 result?:{video_url?:string;task_id?:string;draft_id?:string};build_result?:{video_url?:string};last_error?:string;created_at:string;
}
export interface MiloSettings {daily_enabled:boolean;daily_hour:number;timezone:string;spike_enabled:boolean;spike_threshold:number;window_days:number;cooldown_hours:number;}
export interface MiloBrand {campaign_language:string;personas:MiloPersona[];proof_points:MiloProof[];banned_terms:string[];competitor_names:string[];}
export interface MiloJob {id:string;campaign_id?:string;kind?:string;status:string;last_error?:string;payload?:{submission_state?:string;provider_task_id?:string;task_id?:string};}
export interface ScriptEditor {revision:number;scenes:MiloScene[];dirty:boolean;}
export function keepScriptEditor(editor:ScriptEditor|undefined,campaign:Pick<MiloCampaign,'revision'|'artifact'>):ScriptEditor {
 if(editor?.dirty)return editor;
 return {revision:campaign.revision,scenes:campaign.artifact?.video_script.map(scene=>({...scene}))??[],dirty:false};
}
export function campaignCapabilities(campaign:Pick<MiloCampaign,'status'|'script_status'|'compliance'|'artifact'|'build_status'>,dirty:boolean,stale:boolean) {
 const pending=!!campaign.artifact&&['awaiting_review','blocked'].includes(campaign.status)&&campaign.script_status==='pending'&&!campaign.build_status;
 return {canEdit:pending,canApprove:pending&&campaign.status==='awaiting_review'&&campaign.compliance.passed&&!dirty&&!stale,canReject:pending&&!dirty&&!stale};
}
export function scriptDecisionRequest(orgId:string,campaign:Pick<MiloCampaign,'id'|'revision'>,action:'edit'|'approve'|'reject',key:string,scenes?:MiloScene[]) {
 if(!Number.isSafeInteger(campaign.revision)||campaign.revision<1)throw new Error('Campaign revision is missing. Refresh before deciding.');
 if(action==='edit'){
  if(!scenes?.length||scenes.length>12||scenes.some(scene=>!scene.spoken_narration.trim()))throw new Error('Each script scene needs spoken narration (1–12 scenes).');
  if(scenes.some(scene=>!scene.visual_broll_cues.trim()))throw new Error('Each scene needs visual / B-roll cues.');
  if(scenes.some(scene=>scene.spoken_narration.length>1500||scene.visual_broll_cues.length>1500))throw new Error('Narration and visual cues must be at most 1500 characters per scene.');
  if(scenes.some(scene=>scene.on_screen_text.length>500))throw new Error('On-screen text must be at most 500 characters per scene.');
 }
 return {path:`/api/milo/${encodeURIComponent(orgId)}/campaigns/${encodeURIComponent(campaign.id)}/script/${action}`,init:{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({expected_revision:campaign.revision,...(action==='edit'?{video_script:scenes}:{})})}};
}
