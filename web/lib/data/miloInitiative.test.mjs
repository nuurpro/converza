import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import loader from '../../tests/load.cjs';
const require=createRequire(import.meta.url),React=require('react');
const tick=()=>new Promise(resolve=>setImmediate(resolve));

function nodes(view){
 if(!view||typeof view!=='object')return [];
 return [view,...React.Children.toArray(view.props?.children).flatMap(nodes)];
}
function workspace({org='org-a',memory=async()=>({products:[{id:'initiative-a',name:'Arts festival'}]}),create=async()=>({})}={}){
 const state=[],refs=[],effects=[];let stateIndex=0,refIndex=0,mounted=false;
 const react={...React,useState:initial=>{const index=stateIndex++;if(!(index in state))state[index]=typeof initial==='function'?initial():initial;return [state[index],value=>{state[index]=typeof value==='function'?value(state[index]):value;}];},
  useRef:initial=>{const index=refIndex++;return refs[index]??(refs[index]={current:initial});},
  useEffect:effect=>{if(!mounted)effects.push(effect);}};
 const {MiloCampaigns}=loader({'react':react,'@/lib/hooks/useMiloOrg':{useMiloOrg:()=>org},
  '@/lib/api/memory':{memoryRequest:memory},'@/lib/api/milo':{
   fetchMiloCampaigns:async()=>({campaigns:[{id:'visible-campaign'}]}),
   fetchMiloJobs:async()=>({jobs:[{id:'failed-job',status:'failed'}]}),createMiloCampaign:create,
  }})( 'components/workspace/MiloCampaigns.tsx');
 const root=MiloCampaigns();let cleanups=[];
 return {render(){stateIndex=0;refIndex=0;return root.type(root.props);},
  mount(){cleanups=effects.map(effect=>effect());mounted=true;},
  close(){cleanups.forEach(cleanup=>cleanup?.());},state,root};
}

test('campaign creation sends optional canonical product_id through the authenticated org route',async()=>{
 const requests=[];
 const {createMiloCampaign}=loader({'@/lib/api/session':{authenticatedFetch:async(url,init)=>{
  requests.push({url,init});return Response.json({id:'campaign',product_id:'initiative'});
 }}})('lib/api/milo.ts');
 await createMiloCampaign('org/a','Direction','uz','fixed-key','initiative');
 assert.equal(requests[0].url,'/api/backend/api/milo/org%2Fa/campaigns');
 assert.deepEqual(JSON.parse(requests[0].init.body),{prompt:'Direction',language:'uz',product_id:'initiative'});
 assert.equal(requests[0].init.headers.get('Idempotency-Key'),'fixed-key');
 await createMiloCampaign('org/a','Direction','','auto-key');
 assert.deepEqual(JSON.parse(requests[1].init.body),{prompt:'Direction'});
});

test('native initiative picker loads the authenticated org catalog and defaults to automatic scope',async()=>{
 const calls=[];const view=workspace({memory:async(...args)=>{calls.push(args);return {products:[{id:'initiative-a',name:'Arts festival'}]};}});
 try{
  view.render();view.mount();await tick();
  const tree=view.render(),select=nodes(tree).find(node=>node.type==='select'&&node.props['aria-label']==='Product or initiative');
  assert.ok(select,'initiative select exists');assert.equal(select.props.value,'');
  assert.ok(nodes(select).some(node=>node.type==='option'&&node.props.value==='initiative-a'&&node.props.children==='Arts festival'));
  assert.deepEqual(calls,[['/products',undefined,'org-a']]);
 }finally{view.close();}
});

test('catalog failure preserves campaigns, failed jobs, automatic generation and a catalog retry',async()=>{
 const sent=[];let fail=true;
 const view=workspace({memory:async()=>{if(fail)throw new Error('Catalog unavailable');return {products:[{id:'initiative-a',name:'Arts festival'}]};},create:async(...args)=>{sent.push(args);return {};}});
 try{
  view.render();view.mount();await tick();let tree=view.render();
  assert.ok(nodes(tree).some(node=>node.props?.campaign?.id==='visible-campaign'));
  assert.ok(nodes(tree).some(node=>node.props?.job?.id==='failed-job'));
  const form=nodes(tree).find(node=>node.type==='form');form.props.onSubmit({preventDefault(){}});await tick();
  assert.equal(sent.length,1);assert.ok(!sent[0][4]);
  const retry=nodes(tree).find(node=>node.type==='button'&&node.props.children==='Retry catalog');assert.ok(retry);
  fail=false;retry.props.onClick();await tick();tree=view.render();
  assert.ok(nodes(tree).some(node=>node.props?.campaign?.id==='visible-campaign'));
  assert.ok(nodes(tree).some(node=>node.type==='option'&&node.props.value==='initiative-a'));
  assert.ok(!nodes(tree).some(node=>node.type==='button'&&node.props.children==='Retry catalog'));
 }finally{view.close();}
});

test('uncertain retries retain their key but a changed initiative gets a different operation identity',async()=>{
 const sent=[];const view=workspace({create:async(...args)=>{sent.push(args);throw new TypeError('Connection lost');}});
 try{
  view.render();view.mount();await tick();
  const select=()=>nodes(view.render()).find(node=>node.type==='select'&&node.props['aria-label']==='Product or initiative');
  const submit=async()=>{nodes(view.render()).find(node=>node.type==='form').props.onSubmit({preventDefault(){}});await tick();};
  assert.ok(select(),'initiative select exists');
  select().props.onChange({target:{value:'initiative-a'}});await submit();await submit();
  assert.equal(sent[0][4],'initiative-a');assert.equal(sent[0][3],sent[1][3]);
  select().props.onChange({target:{value:''}});await submit();
  assert.notEqual(sent[2][3],sent[0][3]);assert.ok(!sent[2][4]);
  select().props.onChange({target:{value:'initiative-a'}});await submit();
  assert.equal(sent[3][3],sent[0][3]);
 }finally{view.close();}
});

test('an old organization catalog response cannot populate an unmounted workspace',async()=>{
 let release;const view=workspace({memory:()=>new Promise(resolve=>{release=resolve;})});
 view.render();view.mount();view.close();await tick();const before=JSON.stringify(view.state);
 release?.({products:[{id:'old',name:'Previous owner'}]});await tick();
 assert.equal(JSON.stringify(view.state),before);
});

test('initiative and operation state is remounted for a different organization and hidden on signout',()=>{
 let org='org-a';
 const {MiloCampaigns}=loader({'@/lib/hooks/useMiloOrg':{useMiloOrg:()=>org}})('components/workspace/MiloCampaigns.tsx');
 const first=MiloCampaigns();org='org-b';const second=MiloCampaigns();
 assert.equal(first.key,'org-a');assert.equal(second.key,'org-b');assert.equal(second.props.org,'org-b');
 org=null;assert.notEqual(MiloCampaigns().type,first.type);
});
