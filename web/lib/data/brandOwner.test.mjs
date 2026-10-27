import test from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import loader from '../../tests/load.cjs';
const require=createRequire(import.meta.url);
function load(relative,dependencies){return loader(dependencies)(fileURLToPath(new URL(relative,import.meta.url)));}
test('memory requests bind the selected organization before async authentication and support explicit owner context',async()=>{
 let org='old-org',release;
 const {memoryRequest}=load('../api/memory.ts',{'@/lib/api/session':{authenticatedFetch:async(url,init)=>{await new Promise(resolve=>{release=resolve;});return fetch(url,init);}},'@/lib/org':{getCurrentOrgId:()=>org}});
 const originalFetch=globalThis.fetch,urls=[];
 globalThis.fetch=async url=>{urls.push(url);return new Response('{}',{status:200});};
 try{
  const pending=memoryRequest('/identity');org='new-org';release(new Headers());await pending;
  assert.equal(urls[0],'/api/backend/api/memory/old-org/identity');
  const explicit=memoryRequest('/identity',{method:'PUT'},'chosen-org');org='third-org';release(new Headers());await explicit;
  assert.equal(urls[1],'/api/backend/api/memory/chosen-org/identity');
 }finally{globalThis.fetch=originalFetch;}
});
test('Brand Passport remounts the entire editor when the active organization changes',()=>{
 let org='old-org';
 const {default:BrandPage}=load('../../app/settings/brand/page.tsx',{'@/lib/api/memory':{},'@/lib/hooks/useMiloOrg':{useMiloOrg:()=>org},'@/components/workspace/MiloBrandConfig':{}});
 const old=BrandPage();org='new-org';const next=BrandPage();
 assert.equal(old.key,'old-org');assert.equal(next.key,'new-org');assert.equal(old.props.org,'old-org');assert.equal(next.props.org,'new-org');
 org=null;const signedOut=BrandPage();assert.equal(signedOut.props.children,'Sign in to edit Brand Passport.');
});
test('unmounted Brand Passport editor ignores a delayed identity response',async()=>{
 let resolveIdentity;const effects=[],writes=[],calls=[];
 const react={...require('react'),useState:initial=>[initial,value=>writes.push(value)],useEffect:callback=>effects.push(callback),useRef:initial=>({current:initial})};
 const {default:BrandPage}=load('../../app/settings/brand/page.tsx',{'react':react,'@/lib/api/memory':{memoryRequest:(...args)=>{calls.push(args);return new Promise(resolve=>{resolveIdentity=resolve;});}},'@/lib/hooks/useMiloOrg':{useMiloOrg:()=> 'old-org'},'@/components/workspace/MiloBrandConfig':{}});
 const element=BrandPage();element.type(element.props);const cleanup=effects[0]();cleanup();
 resolveIdentity({org_id:'old-org',revision:7,passport:{brand_name:'Previous owner'},exports:{}});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls[0][2],'old-org');assert.deepEqual(writes,[]);
});
test('Milo API exposes structured compliance evidence errors to the reviewer',async()=>{
 const {miloRequest}=load('../api/milo.ts',{'@/lib/api/session':{authenticatedFetch:(...args)=>fetch(...args)},'@/lib/data/milo':{}});
 const originalFetch=globalThis.fetch;
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:{message:'Campaign needs revalidation or new evidence.',violations:['Current spec changed','Unsupported guarantee']}}),{status:409});
 try{await assert.rejects(miloRequest('org','/campaigns/c/script/approve'),/Current spec changed.*Unsupported guarantee/);}finally{globalThis.fetch=originalFetch;}
});
