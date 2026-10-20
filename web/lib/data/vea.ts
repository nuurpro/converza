export interface VeaSegment {segment_id:string;asset_id:string;start_ms:number;end_ms:number;}
export interface VeaManifest {segments:VeaSegment[];product_id?:string;language?:string;}
export interface VeaVideoArtifact {
 schema_version:1;id:string;variant_revision:number;video_url:string;thumbnail_url:string;duration_sec:number;preset_used:string;preset_version:number|string;preset_sha256:string;source_milo_script_id:string;approved_script_revision:number;composition_sha256:string;render_telemetry:Record<string,unknown>;composition_manifest?:VeaManifest;superseded?:boolean;
}
export interface VeaVariant {
 id:string;org_id:string;campaign_id:string;approved_script_revision:number;revision:number;preset_id:string;status:'queued'|'rendering'|'completed'|'failed';job_id?:string;draft_id?:string;artifact?:VeaVideoArtifact|null;error?:string|null;is_default:boolean;composition_manifest?:VeaManifest;segments?:VeaSegment[];product_id?:string|null;language?:string;
}
export interface VeaPreset {id:string;name:string;version:number|string;}
export interface VeaAsset {id:string;tags:string[]|Record<string,string[]>;duration_sec?:number;kind?:'video'|'music';}
export function replacementAssets(assets:VeaAsset[],segment?:Pick<VeaSegment,'start_ms'|'end_ms'>){
 if(!segment)return [];
 const seconds=(segment.end_ms-segment.start_ms)/1000;
 return assets.filter(asset=>seconds>0&&asset.kind==='video'&&Number.isFinite(asset.duration_sec)&&(asset.duration_sec??0)>=seconds);
}
export function safeVideoUrl(value:string|undefined):string|undefined {
 if(!value||value.includes('\\')||/[\u0000-\u0020]/.test(value))return;
 if(value.startsWith('/')&&!value.startsWith('//'))return value;
 try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:undefined;}catch{return;}
}
export function variantMutationRequest(org:string,variant:{id:string;revision:number},action:'swap'|'retry',key:string,extra:Record<string,string>={}){
 if(!Number.isSafeInteger(variant.revision)||variant.revision<1)throw new Error('Video revision is missing. Refresh before deciding.');
 return {path:`/api/vea/${encodeURIComponent(org)}/variants/${encodeURIComponent(variant.id)}/${action}`,init:{method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({expected_revision:variant.revision,...extra})}};
}
export function videoCapabilities(variant:{status:string;artifact?:{video_url:string;superseded?:boolean}|null},draft?:{status:string;superseded_by?:string|null;vea_artifact?:{superseded?:boolean}|null}){
 const current=!draft?.superseded_by&&!variant.artifact?.superseded&&!draft?.vea_artifact?.superseded,complete=variant.status==='completed'&&!!safeVideoUrl(variant.artifact?.video_url);
 return {canApprove:current&&complete&&draft?.status==='AWAITING_HITL',canExport:current&&complete&&draft?.status==='APPROVED',canSwap:current&&complete&&draft?.status!=='REJECTED',canRetry:variant.status==='failed'};
}
export function downloadVideo(artifact:VeaVideoArtifact){
 if(artifact.superseded)return;
 const url=safeVideoUrl(artifact.video_url);if(!url)return;
 const link=document.createElement('a');link.href=url;link.download=`vea-${artifact.id}.mp4`;link.target='_blank';link.rel='noopener noreferrer';link.click();
}
