import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import loader from '../../tests/load.cjs';
import {canApplyDirectorEdit,directorStatus,sceneNumbers} from './director.ts';
const require=createRequire(import.meta.url),React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {DirectorProgress,DirectorEditImpact}=loader({'@/lib/api/milo':{},'@/lib/api/workspace':{}})('components/workspace/MiloDirector.tsx');
const preview={preview_id:'p',base_revision:4,scenes:[],changed_scene_indices:[1,3],reusable_scene_indices:[2],unresolved_instructions:[],narration_changed:false};
const render=(Component,props)=>renderToStaticMarkup(React.createElement(Component,props));
test('edit impact blocks stale, unresolved and empty changes while visual edits preserve signoff',()=>{
 assert.equal(canApplyDirectorEdit(preview,4),true);
 assert.equal(canApplyDirectorEdit(preview,5),false);
 assert.equal(canApplyDirectorEdit({...preview,unresolved_instructions:['Missing SKU image']},4),false);
 assert.equal(canApplyDirectorEdit({...preview,changed_scene_indices:[]},4),false);
 assert.equal(sceneNumbers([1,3]),'1, 3');
 const html=render(DirectorEditImpact,{preview,revision:4,busy:false,onApply(){}});
 assert.ok(html.includes('Changed scenes: 1, 3'));
 assert.ok(html.includes('No additional approval'));
 const blocked=render(DirectorEditImpact,{preview:{...preview,unresolved_instructions:['Missing SKU image'],narration_changed:true},revision:5,busy:false,onApply(){}});
 for(const text of ['Missing SKU image','renewed script sign-off','Storyboard changed','disabled=""'])assert.ok(blocked.includes(text),text);
});
test('all production states render automatic progress with retries and no scene approval',()=>{
 for(const status of ['DIRECTING_SCENE','AWAITING_SCENE_VERIFICATION','SCENE_VERIFIED','ASSEMBLING_MASTER','REVIEWING_MASTER','AWAITING_HITL','BLOCKED']){
  const html=render(DirectorProgress,{snapshot:{run:{id:'r',status,storyboard_revision:4,scene_index:2,total_scenes:3,attempt:3,scenes:[{scene_index:1,status:'SCENE_VERIFIED'}],error:status==='BLOCKED'?'Whisper model missing: configure local model path':null,inspection:{passed:true,duration_delta_ms:10}}}});
  assert.ok(html.includes(directorStatus(status)));
  assert.ok(html.includes('Scene 2 of 3'));
  assert.ok(html.includes('Attempt 3 of 3'));
  assert.ok(html.includes('Automated targeted retry'));
  assert.ok(html.includes('Master inspection evidence'));
  assert.equal(/Approve scene|Scene visual approval|AWAITING_SCENE_VISUAL_APPROVAL/i.test(html),false);
  if(status==='BLOCKED')assert.ok(html.includes('Whisper model missing'));
  if(status==='AWAITING_HITL')assert.ok(html.includes('Central Approval Feed'));
 }
});
test('director requests scope org/campaign and preserve optimistic revision and idempotency',async()=>{
 const requests=[];const api=loader({'@/lib/api/session':{authenticatedFetch:async(url,init)=>{requests.push({url,init});return Response.json({});}}})('lib/api/milo.ts');
 await api.fetchMiloDirector('org/a','c/b');
 await api.previewMiloDirectorEdit('org/a','c/b','Larger captions',4);
 await api.applyMiloDirectorEdit('org/a','c/b','preview',4,'operation-key');
 await api.approveMiloDirectorNarration('org/a','c/b',5,'narration-key');
 await api.recoverMiloDirector('org/a','c/b','run',5,'recover-key');
 assert.equal(requests[0].url,'/api/backend/api/milo/org%2Fa/campaigns/c%2Fb/director');
 assert.deepEqual(JSON.parse(requests[1].init.body),{directive:'Larger captions',expected_revision:4});
 assert.deepEqual(JSON.parse(requests[2].init.body),{preview_id:'preview',expected_revision:4});
 assert.equal(requests[2].init.headers.get('Idempotency-Key'),'operation-key');
 assert.ok(requests[3].url.endsWith('/director/storyboard/approve'));
 assert.deepEqual(JSON.parse(requests[3].init.body),{expected_revision:5});
 assert.equal(requests[3].init.headers.get('Idempotency-Key'),'narration-key');
 assert.ok(requests[4].url.endsWith('/director/recover'));
 assert.deepEqual(JSON.parse(requests[4].init.body),{run_id:'run',expected_revision:5});
 assert.equal(requests[4].init.headers.get('Idempotency-Key'),'recover-key');
});

function mountDirector(api,scriptStatus='approved'){
 const state=[],refs=[],effects=[];let si=0,ri=0,mounted=false,listener,fetches=0;
 const react={...React,useState:initial=>{const index=si++;if(!(index in state))state[index]=typeof initial==='function'?initial():initial;return [state[index],value=>{state[index]=typeof value==='function'?value(state[index]):value;}];},useRef:initial=>refs[ri++]??(refs[ri-1]={current:initial}),useEffect:effect=>{if(!mounted)effects.push(effect);}};
 const {MiloDirector}=loader({'react':react,'@/lib/api/milo':{...api,fetchMiloDirector:async(...args)=>{fetches++;return api.fetchMiloDirector(...args);}},'@/lib/api/workspace':{subscribeWorkspace:callback=>{listener=callback;return()=>{};}}})('components/workspace/MiloDirector.tsx');
 let cleanups=[];return {render(){si=0;ri=0;return MiloDirector({org:'org',campaignId:'c',scriptStatus,onChanged(){}});},mount(){cleanups=effects.map(effect=>effect());mounted=true;},close(){cleanups.forEach(cleanup=>cleanup?.());},emit(event){listener(event);},get fetches(){return fetches;}};
}
function nodes(view){return !view||typeof view!=='object'?[]:[view,...React.Children.toArray(view.props?.children).flatMap(nodes)];}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('reconnect snapshot and persisted scene steps refresh authoritative run, unmount ignores late responses',async()=>{
 let finish;const view=mountDirector({fetchMiloDirector:async()=>new Promise(resolve=>{finish=resolve;})});
 view.render();view.mount();assert.equal(view.fetches,1);
 finish({run:null,storyboard:{revision:1,scenes:[{scene_index:1,narration_chunk:'Exact narration'}],narration_approved:true}});await tick();
 view.emit({type:'snapshot'});assert.equal(view.fetches,2);
 view.emit({type:'agent_run_step',row:{id:'step'}});assert.equal(view.fetches,3);
 view.close();finish({run:null,storyboard:{revision:99,scenes:[],narration_approved:false}});await tick();
 assert.equal(nodes(view.render()).some(node=>node.props?.children==='Approve narration'),false);
});
test('narration reapproval displays exact approved revision and visual-only storyboard has no new approval',async()=>{
 const approvals=[];let approved=false;
 const view=mountDirector({fetchMiloDirector:async()=>({run:null,storyboard:{revision:5,scenes:[{scene_index:1,narration_chunk:'Точные слова · aniq so‘zlar'}],narration_approved:approved}}),approveMiloDirectorNarration:async(...args)=>{approvals.push(args);approved=true;}});
 try{view.render();view.mount();await tick();const tree=view.render();
 assert.ok(nodes(tree).some(node=>Array.isArray(node.props?.children)&&node.props.children.includes('Точные слова · aniq so‘zlar')));
 const approve=nodes(tree).find(node=>node.type==='button'&&node.props.children==='Approve narration');assert.ok(approve);assert.equal(approve.props.disabled,false);
 approve.props.onClick();await tick();assert.deepEqual(approvals[0].slice(0,3),['org','c',5]);assert.ok(approvals[0][3]);
 assert.equal(nodes(view.render()).some(node=>node.props?.children==='Approve narration'),false);
 }finally{view.close();}
});
test('blocked run recovery pins current run revision and does not introduce scene approval',async()=>{
 const recoveries=[];let approved=true;
 const view=mountDirector({fetchMiloDirector:async()=>({run:{id:'r',status:'BLOCKED',attempt:3},storyboard:{revision:5,scenes:[{scene_index:1,narration_chunk:'Words'}],narration_approved:approved}}),recoverMiloDirector:async(...args)=>{recoveries.push(args);}});
 try{view.render();view.mount();await tick();let tree=view.render();
 const recover=nodes(tree).find(node=>node.type==='button'&&node.props.children==='Resume after resolving issue');assert.ok(recover);
 recover.props.onClick();await tick();assert.deepEqual(recoveries[0].slice(0,4),['org','c','r',5]);assert.ok(recoveries[0][4]);
 approved=false;view.emit({type:'snapshot'});await tick();tree=view.render();
 assert.equal(nodes(tree).some(node=>node.props?.children==='Resume after resolving issue'),false);
 }finally{view.close();}
});
test('initial pending campaign uses existing script sign-off without a second narration approval',async()=>{
 const view=mountDirector({fetchMiloDirector:async()=>({run:null,storyboard:{revision:1,scenes:[{scene_index:1,narration_chunk:'Initial words'}],narration_approved:false}})},'pending');
 try{view.render();view.mount();await tick();assert.equal(nodes(view.render()).some(node=>node.props?.children==='Approve narration'),false);}finally{view.close();}
});
test('workspace maps standalone director evidence into final review card',()=>{
 const {mapSquadMessage}=loader({'@/lib/api/session':{},'@/lib/org':{},'@/lib/supabase/client':{},'@/lib/config':{DEMO_MODE:false}})('lib/api/workspace.ts');
 const director_artifact={director_run_id:'r',inspection:{passed:true},inspection_report:{passed:true},video_url:'/master.mp4'};
 const result=mapSquadMessage({id:'m',org_id:'org',sender_slug:'vea',content:'Review master',hitl_draft_id:'d'},{id:'d',org_id:'org',agent_slug:'vea',status:'AWAITING_HITL',revision:1,draft_content:'Master',director_artifact});
 assert.deepEqual(result.hitlCard.directorArtifact,director_artifact);
});
