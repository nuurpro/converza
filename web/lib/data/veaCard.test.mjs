import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createRequire,Module} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
function load(relative){const filename=fileURLToPath(new URL(relative,import.meta.url)),compiled=new Module(filename);compiled.filename=filename;compiled.paths=Module._nodeModulePaths(fileURLToPath(new URL('../../components/workspace/',import.meta.url)));const real=compiled.require.bind(compiled);compiled.require=id=>id==='@/lib/data/vea'?require('./vea.ts'):id.startsWith('@/')?{}:real(id);compiled._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,filename);return compiled.exports;}
const {HitlCard}=load('../../components/workspace/AgentWorkspace.tsx');
const artifact={schema_version:1,id:'v',variant_revision:1,video_url:'/static/v.mp4',thumbnail_url:'/static/v.jpg',duration_sec:12.5,preset_used:'editorial_showcase',preset_version:1,source_milo_script_id:'c',approved_script_revision:3,render_telemetry:{}};
function render(changes={}){return renderToStaticMarkup(React.createElement(HitlCard,{card:{id:'d',label:'Review',status:'pending',content:'Structured video',veaArtifact:artifact,...changes},onApprove(){},onEdit(){},onSkip(){}}));}
test('video feed renders playable preview and approval/export without text editing or publishing',()=>{
 const html=render();for(const text of ['<video','poster="/static/v.jpg"','src="/static/v.mp4"','12.5s','editorial_showcase','Approve &amp; Export','Review clips in Vea'])assert.ok(html.includes(text),text);
 assert.equal(html.includes('Request edit'),false);assert.equal(html.includes('Replacement content'),false);assert.equal(html.includes('Publish'),false);
});
test('approved video is downloadable and superseded video cannot export or approve',()=>{
 const html=render({status:'approved'});assert.ok(html.includes('Download MP4'));assert.ok(html.includes('Approved for export'));assert.equal(html.includes('awaiting publisher'),false);
 const stale=render({status:'approved',supersededBy:'new'});assert.equal(stale.includes('Download MP4'),false);assert.equal(stale.includes('Approve &amp; Export'),false);
});
test('invalid video URLs never enter a media element',()=>{
 const html=render({veaArtifact:{...artifact,video_url:'javascript:alert(1)',thumbnail_url:'data:image/png,x'}});assert.equal(html.includes('src="javascript:'),false);assert.equal(html.includes('poster="data:'),false);
});
const {VeaVariantCard}=(()=>{
 const filename=fileURLToPath(new URL('../../components/workspace/VeaVideos.tsx',import.meta.url)),compiled=new Module(filename);compiled.filename=filename;compiled.paths=Module._nodeModulePaths(fileURLToPath(new URL('../../components/workspace/',import.meta.url)));const real=compiled.require.bind(compiled);compiled.require=id=>id==='@/components/workspace/AgentWorkspace'?load('../../components/workspace/AgentWorkspace.tsx'):id==='@/lib/data/vea'?require('./vea.ts'):id.startsWith('@/')?{}:real(id);compiled._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,filename);return compiled.exports;
})();
function variantHtml(changes={},draft={status:'AWAITING_HITL'}){return renderToStaticMarkup(React.createElement(VeaVariantCard,{org:'o',variant:{id:'v',revision:1,preset_id:'editorial_showcase',status:'completed',artifact,composition_manifest:{segments:[{segment_id:'s',asset_id:'a',start_ms:0,end_ms:12500}]},...changes},draft,busy:false,onDecide(){},onRetry(){},onSwap(){}}));}
test('workspace completed variants support clip replacement and approval but never publishing',()=>{
 const html=variantHtml();for(const text of ['Swap Clip &amp; Re-render','Approve &amp; Export','Reject'])assert.ok(html.includes(text),text);assert.equal(html.includes('Publish'),false);
 const superseded=variantHtml({},{status:'APPROVED',superseded_by:'next'});assert.equal(superseded.includes('Download MP4'),false);assert.equal(superseded.includes('Swap Clip &amp; Re-render'),false);
});
test('queued, rendering, and failed videos show distinct recovery states',()=>{
 assert.ok(variantHtml({status:'queued',artifact:null},undefined).includes('Waiting for renderer'));
 const rendering=variantHtml({status:'rendering',artifact:null},undefined);assert.ok(rendering.includes('Rendering narration'));assert.equal(rendering.includes('Retry render'),false);
 const failed=variantHtml({status:'failed',artifact:null,error:'Missing rights-confirmed clips'},undefined);assert.ok(failed.includes('Missing rights-confirmed clips'));assert.ok(failed.includes('Retry render'));
});
test('server superseded artifact marker disables all review and export controls',()=>{
 const html=render({status:'approved',veaArtifact:{...artifact,superseded:true}});assert.equal(html.includes('Download MP4'),false);assert.ok(html.includes('Replaced by a new video revision'));
 assert.equal(variantHtml({artifact:{...artifact,superseded:true}}, {status:'APPROVED'}).includes('Download MP4'),false);
});
test('public variant segments expose clip swap without private manifest',()=>{
 const html=variantHtml({composition_manifest:undefined,segments:[{segment_id:'s',asset_id:'a',start_ms:0,end_ms:12500}]});assert.ok(html.includes('Swap Clip &amp; Re-render'));
});
test('dashboard approval feed renders structured video controls without generic text edits',()=>{
 const filename=fileURLToPath(new URL('../../app/page.tsx',import.meta.url)),mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(fileURLToPath(new URL('.',import.meta.url)));const real=mod.require.bind(mod);let stateIndex=0;
 const react={...React,useState:initial=>[stateIndex++===0?[{id:'workflow:d',kind:'workflow',source_id:'d',revision:2,restrictions:{can_approve:true,can_edit:false,can_reject:true,reasons:[]},payload:{draft:{id:'d',agent_slug:'vea',revision:2,status:'AWAITING_HITL',draft_content:'Video',vea_artifact:artifact}}}]:initial,()=>{}],useEffect(){},useRef:initial=>({current:initial})};
 mod.require=id=>id==='react'?react:id==='@/components/workspace/AgentWorkspace'?load('../../components/workspace/AgentWorkspace.tsx'):id==='@/lib/api/workspace'?{mapSquadMessage:(_,draft)=>({hitlCard:{id:draft.id,label:'Review video',status:'pending',content:draft.draft_content,revision:draft.revision,veaArtifact:draft.vea_artifact}})}:id==='@/lib/hooks/useWorkspace'?{useWorkspace:()=>({drafts:{},steps:[],setError(){}})}:id==='@/lib/hooks/useMiloOrg'?{useMiloOrg:()=> 'org'}:id==='@/lib/data/vea'?require('./vea.ts'):id.startsWith('@/')?{}:real(id);
 mod._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,filename);
 const html=renderToStaticMarkup(React.createElement(mod.exports.default));assert.ok(html.includes('<video'));assert.ok(html.includes('Approve &amp; Export'));assert.equal(html.includes('Request edit'),false);assert.equal(html.includes('Replacement content'),false);
});
test('swap form hides music and short footage from the rendered replacement choices',()=>{
 const filename=fileURLToPath(new URL('../../components/workspace/VeaVideos.tsx',import.meta.url)),mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(fileURLToPath(new URL('.',import.meta.url)));const real=mod.require.bind(mod);
 const state=[true,[{id:'eligible-video',kind:'video',duration_sec:3,tags:[]},{id:'music-track',kind:'music',duration_sec:60,tags:[]},{id:'too-short',kind:'video',duration_sec:2,tags:[]}],'','s','',false];let index=0;
 mod.require=id=>id==='react'?{...React,useState:()=>[state[index++],()=>{}],useEffect(){}}:id==='@/lib/data/vea'?require('./vea.ts'):id==='@/components/workspace/AgentWorkspace'?load('../../components/workspace/AgentWorkspace.tsx'):id.startsWith('@/')?{}:real(id);
 mod._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,filename);
 const html=renderToStaticMarkup(React.createElement(mod.exports.VeaVariantCard,{org:'org',variant:{id:'v',revision:1,status:'completed',artifact,segments:[{segment_id:'s',asset_id:'original',start_ms:0,end_ms:3000}]},busy:false,onSwap(){},onRetry(){},onDecide(){}}));
 assert.ok(html.includes('eligible-video'));assert.equal(html.includes('music-track'),false);assert.equal(html.includes('too-short'),false);
});
