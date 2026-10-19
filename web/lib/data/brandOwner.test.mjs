import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createRequire,Module} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript');
function load(relative,dependencies){const filename=fileURLToPath(new URL(relative,import.meta.url));const mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(fileURLToPath(new URL('.',import.meta.url)));const original=mod.require.bind(mod);mod.require=id=>id in dependencies?dependencies[id]:original(id);mod._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,filename);return mod.exports;}
test('memory requests bind the selected organization before async authentication and support explicit owner context',async()=>{
 let org='old-org',release;
 const {memoryRequest}=load('../api/memory.ts',{'@/lib/api/session':{authHeaders:()=>new Promise(resolve=>{release=resolve;})},'@/lib/org':{getCurrentOrgId:()=>org}});
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
 const {miloRequest}=load('../api/milo.ts',{'@/lib/api/session':{authHeaders:async()=>new Headers()},'@/lib/data/milo':{}});
 const originalFetch=globalThis.fetch;
 globalThis.fetch=async()=>new Response(JSON.stringify({detail:{message:'Campaign needs revalidation or new evidence.',violations:['Current spec changed','Unsupported guarantee']}}),{status:409});
 try{await assert.rejects(miloRequest('org','/campaigns/c/script/approve'),/Current spec changed.*Unsupported guarantee/);}finally{globalThis.fetch=originalFetch;}
});
