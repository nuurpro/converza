import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createRequire,Module} from 'node:module';
const require=createRequire(import.meta.url),ts=require('typescript');
function load(dependencies){const filename=fileURLToPath(new URL('../../components/workspace/VeaVideos.tsx',import.meta.url)),mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(fileURLToPath(new URL('.',import.meta.url)));const real=mod.require.bind(mod);mod.require=id=>id in dependencies?dependencies[id]:id.startsWith('@/')?{}:real(id);mod._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,filename);return mod.exports;}
test('organization switch remounts the complete Vea workspace and signout hides prior videos',()=>{
 let org='old';const {VeaVideos}=load({'@/lib/hooks/useMiloOrg':{useMiloOrg:()=>org}});
 const old=VeaVideos();org='new';const next=VeaVideos();assert.equal(old.key,'old');assert.equal(next.key,'new');assert.equal(next.props.org,'new');org=null;assert.equal(VeaVideos().props.children,'Sign in to review Vea videos.');
});
test('unmounted Vea workspace ignores delayed variant and preset responses',async()=>{
 const effects=[],writes=[];let resolveVideos;const react={...require('react'),useState:initial=>[initial,value=>writes.push(value)],useEffect:effect=>effects.push(effect),useRef:initial=>({current:initial})};
 const {VeaVideos}=load({'react':react,'@/lib/hooks/useMiloOrg':{useMiloOrg:()=> 'org'},'@/lib/hooks/useWorkspace':{useWorkspace:()=>({drafts:{}})},'@/lib/api/vea':{fetchVeaVariants:()=>new Promise(resolve=>{resolveVideos=resolve;}),fetchVeaPresets:async()=>({presets:[]})},'@/lib/api/milo':{fetchMiloCampaigns:async()=>({campaigns:[]})}});
 const workspace=VeaVideos();workspace.type(workspace.props);const cleanup=effects[0]();cleanup();resolveVideos({variants:[{id:'old-video'}]});await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(writes,[]);
});
test('VEA API errors surface server details and preserve explicit retry keys',async()=>{
 const filename=fileURLToPath(new URL('../api/vea.ts',import.meta.url)),mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(fileURLToPath(new URL('.',import.meta.url)));const real=mod.require.bind(mod);mod.require=id=>id==='@/lib/api/session'?{authHeaders:async headers=>headers}:id==='@/lib/data/vea'?require('./vea.ts'):real(id);mod._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,filename);
 const original=globalThis.fetch,requests=[];globalThis.fetch=async(url,init)=>{requests.push({url,init});return new Response(JSON.stringify({detail:{message:'Evidence changed. Review the current script.'}}),{status:409});};
 try{await assert.rejects(mod.exports.mutateVeaVariant('org/a',{id:'v',revision:4},'retry','stable'),/Evidence changed/);assert.equal(requests[0].url,'/api/backend/api/vea/org%2Fa/variants/v/retry');assert.equal(requests[0].init.headers['Idempotency-Key'],'stable');assert.deepEqual(JSON.parse(requests[0].init.body),{expected_revision:4});}finally{globalThis.fetch=original;}
});
