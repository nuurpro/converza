import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync,readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import loader from '../../tests/load.cjs';
const require=createRequire(import.meta.url);
const tick=()=>new Promise(resolve=>setImmediate(resolve));

for(const [file,name] of [['app/products/page.tsx','default'],['app/settings/memory/page.tsx','default'],['app/agents/[agentId]/page.tsx','default'],['components/workspace/SleyzInbox.tsx','SleyzInbox']]){
  test(`${file} remounts all tenant state for a new org and hides state on signout`,()=>{
    const react={...require('react'),useState:value=>[value,()=>{}],useRef:value=>({current:value}),useEffect:()=>{},useCallback:fn=>fn};
    let org='org-a';const load=loader({'react':react,'@/lib/hooks/useWorkspace':{useWorkspace:()=>({drafts:{}})},'@/lib/hooks/useMiloOrg':{useMiloOrg:()=>org},'next/navigation':{useParams:()=>({agentId:'milo'})}});
    const page=load(file)[name],first=page();org='org-b';const next=page();
    assert.equal(first.key,'org-a');assert.equal(next.key,'org-b');assert.equal(next.props.org,'org-b');
    org=null;assert.notEqual(page().type,first.type);
  });
}
for(const [file,path,payload] of [['app/products/page.tsx','/products',{products:[{id:'stale'}]}],['app/settings/memory/page.tsx','/knowledge',{knowledge:[{id:'stale'}]}]]){
  test(`${file} ignores a previous owner's delayed load after unmount`,async()=>{
    const effects=[],writes=[];let finish;
    const react={...require('react'),useState:initial=>[initial,value=>writes.push(value)],useEffect:effect=>effects.push(effect),useCallback:fn=>fn,useRef:value=>({current:value})};
    const page=loader({'react':react,'@/lib/hooks/useMiloOrg':{useMiloOrg:()=> 'org'},'@/lib/api/memory':{memoryRequest:p=>p===path?new Promise(resolve=>{finish=resolve;}):Promise.resolve({jobs:[]})}})(file).default;
    const view=page();if(view.key)view.type(view.props);
    const cleanup=effects[0]();cleanup?.();finish(payload);await tick();assert.deepEqual(writes,[]);
  });
}
test('Vea variants remain visible when either the preset or campaign catalog fails',async()=>{
  for(const failed of ['presets','campaigns']){
    const effects=[],writes=[];
    const react={...require('react'),useState:initial=>[initial,value=>writes.push(value)],useEffect:effect=>effects.push(effect),useRef:initial=>({current:initial})};
    const {VeaVideos}=loader({'react':react,'@/lib/hooks/useMiloOrg':{useMiloOrg:()=> 'org'},'@/lib/hooks/useWorkspace':{useWorkspace:()=>({drafts:{}})},'@/lib/api/vea':{fetchVeaVariants:async()=>({variants:[{id:'visible-video'}]}),fetchVeaPresets:async()=>{if(failed==='presets')throw new Error('catalog down');return {presets:[]};}},'@/lib/api/milo':{fetchMiloCampaigns:async()=>{if(failed==='campaigns')throw new Error('campaigns down');return {campaigns:[]};}}})('components/workspace/VeaVideos.tsx');
    const view=VeaVideos();view.type(view.props);const cleanup=effects[0]();await tick();cleanup();
    assert.ok(writes.some(value=>Array.isArray(value)&&value[0]?.id==='visible-video'));
    assert.ok(writes.includes(true));
  }
});
test('obsolete demos and OpenClaw widgets are not routes or shipped components',()=>{
  for(const file of ['app/api/chat/route.ts','components/dag/DagVisualizer.tsx','components/hitl/ApprovalCard.tsx','components/hitl/PermissionPill.tsx',...['projects','calendar','analytics','integrations','office','competitors','settings/profile','settings/billing','settings/tokens','settings/models','settings/integrations'].map(route=>`app/${route}/page.tsx`)]){
    assert.equal(existsSync(new URL('../../'+file,import.meta.url)),false,file);
  }
  for(const [file,target] of [['strategy','/agents/milo'],['copilot','/squad']])assert.ok(readFileSync(new URL(`../../app/${file}/page.tsx`,import.meta.url),'utf8').includes(`redirect("${target}")`));
});

test('old audience entry points redirect to the persisted Brand Passport editor',()=>{
  for(const route of ['audience','settings/audience']){
    let target;
    loader({'next/navigation':{redirect:path=>{target=path;}}})(`app/${route}/page.tsx`).default();
    assert.equal(target,'/settings/brand');
  }
});

test('workspace header reserves enough mobile height for a wrapped title and subtitle',()=>{
  const {WorkspaceHeader}=loader()('components/workspace/AgentWorkspace.tsx');
  const header=WorkspaceHeader({title:'Squad chat',subtitle:'everyone, in one room'});
  assert.match(header.props.className,/min-h-16/);
  assert.match(header.props.className,/flex-col/);
  assert.doesNotMatch(header.props.className,/(?:^|\s)h-16(?:\s|$)/);
});
