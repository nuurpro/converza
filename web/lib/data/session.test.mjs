import test from 'node:test';
import assert from 'node:assert/strict';
import loader from '../../tests/load.cjs';

test('simultaneous fresh-browser restores share one request and both acquire the server organization', async () => {
  const load = loader({'@/lib/supabase/client':{getSupabaseBrowserClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'token',user:{id:'a'}}}})}})}});
  const org=load('lib/org.ts'), {restoreWorkspaceSession}=load('lib/api/session.ts');
  const original=globalThis.fetch;
  let calls=0;
  globalThis.fetch=async()=>{calls++;return Response.json({user:{id:'a'},passport:{org_id:'server-org',owner_user_id:'a'}});};
  try {
    const restored=await Promise.all([restoreWorkspaceSession(),restoreWorkspaceSession()]);
    assert.equal(calls,1);
    assert.deepEqual(restored.map(row=>row.orgId),['server-org','server-org']);
    assert.equal(org.getCurrentOrgId(),'server-org');
  } finally {globalThis.fetch=original;}
});

test('org is unavailable until a verified passport arrives; switching owners aborts old scope', () => {
  const org = loader()('lib/org.ts');
  assert.throws(() => org.getCurrentOrgId(), /workspace|sign in/i);
  org.setWorkspaceSession({id:'owner-a'}, {org_id:'server-org', owner_user_id:'owner-a'});
  assert.equal(org.getCurrentOrgId(), 'server-org');
  const scope = org.getWorkspaceSession();
  org.resetWorkspaceSession();
  assert.equal(scope.signal.aborted, true);
  assert.throws(() => org.getCurrentOrgId(), /workspace|sign in/i);
  org.setWorkspaceSession({id:'owner-b'}, {org_id:'other-org', owner_user_id:'owner-b'});
  assert.equal(org.getCurrentOrgId(), 'other-org');
  assert.throws(() => org.getCurrentOrgId('owner-a'), /owner|workspace/i);
});

test('authenticated requests cancel before fetch if owner changes during token lookup', async () => {
  let release;
  const load = loader({'@/lib/supabase/client':{getSupabaseBrowserClient:()=>({auth:{getSession:()=>new Promise(resolve=>{release=resolve;})}})}});
  const org = load('lib/org.ts'), {authenticatedFetch} = load('lib/api/session.ts');
  org.setWorkspaceSession({id:'owner-a'}, {org_id:'org-a', owner_user_id:'owner-a'});
  const original = globalThis.fetch;
  let calls = 0; globalThis.fetch = async () => {calls++; return Response.json({});};
  try {
    const pending = authenticatedFetch('/api/backend/api/memory/org-a/products');
    org.resetWorkspaceSession();
    release({data:{session:{access_token:'token-a',user:{id:'owner-a'}}}});
    await assert.rejects(pending, /changed|abort|session/i);
    assert.equal(calls, 0);
  } finally {globalThis.fetch = original;}
});

test('mutation retries keep the operation key after ambiguous failure and isolate tenant scopes', async () => {
  let owner = 'owner-a';
  const load = loader({'@/lib/supabase/client':{getSupabaseBrowserClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'token',user:{id:owner}}}})}})}});
  const org = load('lib/org.ts'), {authenticatedFetch} = load('lib/api/session.ts');
  org.setWorkspaceSession({id:owner}, {org_id:'org-a', owner_user_id:owner});
  const original = globalThis.fetch, keys = []; let fail = true;
  globalThis.fetch = async (url, init) => {keys.push(init.headers.get('Idempotency-Key')); if (fail) {fail=false;throw new TypeError('connection lost');} return Response.json({ok:true});};
  const send = async () => {const response=await authenticatedFetch('/api/backend/api/drafts/deliver', {method:'POST',body:'{"expected_revision":4}'});await response.json();return response;};
  try {
    await assert.rejects(send()); await send();
    assert.ok(keys[0]); assert.equal(keys[0], keys[1]);
    await send(); assert.notEqual(keys[2], keys[1]);
    owner='owner-b';org.setWorkspaceSession({id:owner}, {org_id:'org-b',owner_user_id:owner});
    await send(); assert.notEqual(keys[3], keys[0]);
  } finally {globalThis.fetch=original;}
});

test('a successful header followed by a lost response body retains the mutation identity',async()=>{
  const load=loader({'@/lib/supabase/client':{getSupabaseBrowserClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'token',user:{id:'a'}}}})}})}});
  const org=load('lib/org.ts'),{authenticatedFetch}=load('lib/api/session.ts');
  org.setWorkspaceSession({id:'a'},{org_id:'org-a',owner_user_id:'a'});
  const original=globalThis.fetch,keys=[];
  globalThis.fetch=async(url,init)=>{
    keys.push(init.headers.get('Idempotency-Key'));
    if(keys.length===1)return {ok:true,json:async()=>{throw new TypeError('connection lost while reading receipt');}};
    return Response.json({saved:true});
  };
  try{
    const send=async()=>{const response=await authenticatedFetch('/api/backend/api/memory/org-a/products',{method:'POST',body:'{"name":"Course"}'});return response.json();};
    await assert.rejects(send());await send();await send();
    assert.equal(keys[0],keys[1]);assert.notEqual(keys[1],keys[2]);
  }finally{globalThis.fetch=original;}
});

test('delayed JSON cannot return data after signout', async () => {
  let release;
  const load = loader({'@/lib/supabase/client':{getSupabaseBrowserClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'token',user:{id:'a'}}}})}})}});
  const org=load('lib/org.ts'), {authenticatedFetch}=load('lib/api/session.ts');
  org.setWorkspaceSession({id:'a'}, {org_id:'org-a', owner_user_id:'a'});
  const original=globalThis.fetch;
  globalThis.fetch=async()=>({ok:true,json:()=>new Promise(resolve=>{release=resolve;})});
  try {
    const response=await authenticatedFetch('/api/backend/api/memory/org-a/products');
    const pending=response.json();org.resetWorkspaceSession();release({products:[{id:'old'}]});
    await assert.rejects(pending,/changed|abort|session/i);
  } finally {globalThis.fetch=original;}
});

test('local onboarding answers and brand names are owner scoped, never adopted from legacy global cache', () => {
  const values = new Map([['converza.onboarding.answers','{"business_name":"Wrong owner"}']]);
  const previous=globalThis.window;
  globalThis.window={localStorage:{getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)},dispatchEvent:()=>{}};
  const api=loader()('lib/onboarding.ts');
  try {
    api.saveLocalAnswers({business_name:'Owner A'}, 'a');
    assert.deepEqual(api.loadLocalAnswers('b'),{});
    assert.equal(api.loadLocalAnswers('a').business_name,'Owner A');
    assert.deepEqual(api.loadLocalAnswers(),{});
  } finally {globalThis.window=previous;}
});
