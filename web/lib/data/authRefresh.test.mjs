import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import loader from '../../tests/load.cjs';
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));

function harness(){
  const values=[],writes=[],effects=[];let callback,release,reject,index=0,calls=0,resets=0;
  let workspace={user:{id:'owner'},orgId:'org',passport:{owner_user_id:'owner',org_id:'org'},generation:1};
  const router={replace(){}};
  const {default:Layout}=loader({
    react:{...React,useState:initial=>{const n=index++;values[n]=initial;return [initial,value=>{values[n]=typeof value==='function'?value(values[n]):value;writes.push([n,values[n]]);}];},useEffect:fn=>effects.push(fn),useSyncExternalStore:(_s,get)=>get()},
    'next/navigation':{usePathname:()=>'/onboarding',useRouter:()=>router},
    '@/components/sidebar/Sidebar':{default:()=>null},
    '@/lib/org':{getWorkspaceSession:()=>workspace,subscribeSession(){},resetWorkspaceSession(){resets++;workspace={...workspace,user:null,passport:null,orgId:null};}},
    '@/lib/supabase/client':{getSupabaseBrowserClient:()=>({auth:{onAuthStateChange:fn=>{callback=fn;return {data:{subscription:{unsubscribe(){}}}};}}})},
    '@/lib/api/session':{restoreWorkspaceSession:()=>++calls===1?Promise.resolve(workspace):new Promise((yes,no)=>{release=yes;reject=no;})},
  })('components/layout/MainLayout.tsx');
  Layout({children:React.createElement('form',null,'Unsaved onboarding')});
  const cleanup=effects[0]();
  return {values,writes,refresh:(event='TOKEN_REFRESHED',owner='owner')=>callback(event,{user:{id:owner}}),
    finish:()=>release?.(workspace),fail:()=>reject?.(new Error('Lookup unavailable')),close:cleanup,resets:()=>resets};
}

test('same-owner token revalidation preserves the mounted onboarding form',async()=>{
  const h=harness();await tick();h.writes.length=0;
  try{h.refresh();await tick();assert.equal(h.values[1],'allowed');assert.equal(h.resets(),0);assert.ok(!h.writes.some(([n,v])=>n===1&&v==='checking'));h.finish();await tick();}
  finally{h.close();}
});

test('account changes immediately invalidate the mounted form before revalidation',async()=>{
  const h=harness();await tick();
  try{h.refresh('SIGNED_IN','another-owner');assert.equal(h.resets(),1);await tick();assert.equal(h.values[1],'checking');h.finish();await tick();}
  finally{h.close();}
});

test('failed same-owner revalidation blocks access and exposes the retryable error',async()=>{
  const h=harness();await tick();
  try{h.refresh();await tick();h.fail();await tick();assert.equal(h.values[1],'blocked');assert.equal(h.values[2],'Lookup unavailable');assert.equal(h.resets(),1);}
  finally{h.close();}
});
