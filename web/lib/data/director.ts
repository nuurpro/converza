export interface DirectorScene {
 scene_index:number; status?:string;state?:string; attempt?:number; narration_chunk?:string;target_duration_sec?:number;
 visual_directive?:{prompt:string;subject_action:string;camera_movement:string;lighting_style:string};
 overlay_text?:{text:string;font_family:string;font_size:number;color:string;position:string;animation:string;start_sec:number;end_sec:number};
 [key:string]:unknown;
}
export interface DirectorRun {
 id:string;status:string;storyboard_revision:number;scene_index:number;total_scenes:number;attempt:number;
 scenes:DirectorScene[];inspection?:Record<string,unknown>|null;master_artifact?:Record<string,unknown>|null;error?:string|null;
}
export interface DirectorSnapshot {run:DirectorRun|null;storyboard:{revision:number;scenes:DirectorScene[];narration_approved:boolean}|null;}
export interface DirectorArtifact {director_run_id:string;inspection:{passed:boolean};inspection_report:Record<string,unknown>;video_url:string;thumbnail_url?:string;duration_sec?:number;superseded?:boolean;superseded_by?:string;}
export interface DirectorEditPreview {
 preview_id:string;base_revision:number;scenes:DirectorScene[];changed_scene_indices:number[];reusable_scene_indices:number[];
 unresolved_instructions:string[];narration_changed:boolean;
}
export function directorStatus(status:string){
 return ({DIRECTING_SCENE:'Directing scene',AWAITING_SCENE_VERIFICATION:'Checking scene automatically',SCENE_VERIFIED:'Scene verified',ASSEMBLING_MASTER:'Assembling master',REVIEWING_MASTER:'Inspecting master',AWAITING_HITL:'Master ready for your review',BLOCKED:'Production blocked',RECONCILING_SUBMISSION:'Checking original provider submission',AWAITING_NARRATION_APPROVAL:'Narration sign-off needed'} as Record<string,string>)[status]??status.replaceAll('_',' ');
}
export function canApplyDirectorEdit(preview:DirectorEditPreview|null,revision:number|undefined){
 return !!preview&&preview.base_revision===revision&&preview.unresolved_instructions.length===0&&preview.changed_scene_indices.length>0;
}
export function sceneNumbers(indices:number[]){return indices.length?indices.join(', '):'None';}
