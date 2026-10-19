import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createRequire,Module} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript'),React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const filename=fileURLToPath(new URL('../../components/workspace/MiloCampaigns.tsx',import.meta.url));
const compiled=new Module(filename);compiled.filename=filename;compiled.paths=Module._nodeModulePaths(fileURLToPath(new URL('../../components/workspace/',import.meta.url)));
const realRequire=compiled.require.bind(compiled);
compiled.require=id=>id==='@/lib/data/milo'?require('./milo.ts'):id.startsWith('@/')?{}:realRequire(id);
compiled._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,filename);
const {CampaignCard}=compiled.exports;
const campaign={id:'c',org_id:'org',revision:3,status:'awaiting_review',trigger:'spike',script_status:'pending',build_status:null,compliance:{passed:true,violations:[]},missing_evidence:[],artifact:{trigger_reason:'14 buyer DMs ask about durability',target_persona:{id:'p',name:'Daily commuter',description:'Needs durability'},language:'uz',brand_revision:4,buyer_quotes:[{source_id:'buyer-1',text:'Will it last in the rain?'}],proof_references:[{source_id:'spec-1',revision:2,quote:'Water resistance rated IP67'}],hooks:[{framework:'A',text:'Pain question'},{framework:'B',text:'Proof hook'},{framework:'C',text:'Offer hook'}],video_script:[{spoken_narration:'Exact approved words',visual_broll_cues:'Show rain test',on_screen_text:'IP67'}],social_captions:{instagram:'Instagram caption',telegram:'Telegram caption',tiktok:'TikTok caption'}}};
function render(change={}){return renderToStaticMarkup(React.createElement(CampaignCard,{campaign:{...campaign,...change},busy:false,onDecide:async()=>null}));}
test('campaign review renders buyer language, current proof and all script and caption channels',()=>{
 const html=render();
 for(const text of ['14 buyer DMs','Daily commuter','Will it last in the rain?','buyer-1','spec-1','revision 2','Pain question','Proof hook','Offer hook','Exact approved words','Show rain test','IP67','Instagram caption','Telegram caption','TikTok caption','Brand compliance: Passed','Approve script &amp; queue Vea'])assert.ok(html.includes(text),text);
 assert.equal(html.includes('>Approve<'),false);
});
test('blocked campaign renders actionable missing evidence and disables script approval',()=>{
 const html=render({status:'blocked',missing_evidence:['Confirm current warranty'],compliance:{passed:false,violations:['Unsupported guarantee']}});
 assert.ok(html.includes('Confirm current warranty'));
 assert.ok(html.includes('Unsupported guarantee'));
 assert.match(html,/<button[^>]*disabled=""[^>]*>Approve script &amp; queue Vea<\/button>/);
});
test('completed build preserves video review link and approved script cannot be approved again',()=>{
 const html=render({script_status:'approved',build_status:'completed',result:{video_url:'https://example.com/render.mp4'}});
 assert.ok(html.includes('Vea build: completed'));
 assert.ok(html.includes('href="https://example.com/render.mp4"'));
 assert.match(html,/<button[^>]*disabled=""[^>]*>Approve script &amp; queue Vea<\/button>/);
 const malicious=render({build_status:'completed',build_result:{video_url:'javascript:alert(1)'}});
 assert.equal(malicious.includes('href="javascript:'),false);
});
test('uncertain provider submissions expose reconciliation instead of a duplicate build retry',()=>{
 const {JobRecovery}=compiled.exports;
 const job={id:'j',kind:'vea_build',status:'failed',last_error:'Provider timeout',payload:{submission_state:'submission_started'}};
 const html=renderToStaticMarkup(React.createElement(JobRecovery,{job,busy:false,onRetry:async()=>{},onReconcile:async()=>{}}));
 assert.ok(html.includes('Original provider task ID'));
 assert.ok(html.includes('Link original provider task'));
 assert.equal(html.includes('>Retry job<'),false);
 const retry=renderToStaticMarkup(React.createElement(JobRecovery,{job:{...job,payload:{}},busy:false,onRetry:async()=>{},onReconcile:async()=>{}}));
 assert.ok(retry.includes('>Retry job<'));
});
