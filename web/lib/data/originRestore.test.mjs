import test from 'node:test';
import assert from 'node:assert/strict';
import loader from '../../tests/load.cjs';

test('Docker internal request URL accepts the explicitly configured public origin',()=>{
  const previous=process.env.WEB_PUBLIC_ORIGIN;
  process.env.WEB_PUBLIC_ORIGIN='http://127.0.0.1:3000';
  const {assertSameOrigin}=loader()('lib/server/backend.ts');
  try {
    assert.doesNotThrow(()=>assertSameOrigin(new Request('http://0.0.0.0:3000/api/session',{headers:{origin:'http://127.0.0.1:3000','sec-fetch-site':'same-origin'}})));
    assert.throws(()=>assertSameOrigin(new Request('http://0.0.0.0:3000/api/session',{headers:{origin:'https://evil.test','x-forwarded-host':'evil.test'}})));
    assert.throws(()=>assertSameOrigin(new Request('http://0.0.0.0:3000/api/session',{headers:{origin:'http://127.0.0.1:3000','sec-fetch-site':'cross-site'}})));
  } finally {if(previous===undefined)delete process.env.WEB_PUBLIC_ORIGIN;else process.env.WEB_PUBLIC_ORIGIN=previous;}
});

test('successful workspace restoration chooses the persisted access destination',async()=>{
  const {restoreWorkspaceDestination}=loader({'@/lib/api/session':{restoreWorkspaceSession:async()=>({user:{id:'owner'},passport:{owner_user_id:'owner',org_id:'persisted',onboarding_completed_at:'2026-01-01',paywall_status:'paid'}})}})('lib/access.ts');
  assert.equal(await restoreWorkspaceDestination(),'/');
});

test('workspace lookup failure never becomes new onboarding',async()=>{
  const {restoreWorkspaceDestination}=loader({'@/lib/api/session':{restoreWorkspaceSession:async()=>{throw new Error('Lookup unavailable');}}})('lib/access.ts');
  await assert.rejects(()=>restoreWorkspaceDestination(),/Lookup unavailable/);
});

test('public origin configuration fails closed in production and rejects malformed authorities',()=>{
  const previous={origin:process.env.WEB_PUBLIC_ORIGIN,env:process.env.NODE_ENV};
  const {assertSameOrigin}=loader()('lib/server/backend.ts');
  const request=new Request('http://0.0.0.0:3000/api/session');
  try{
    process.env.NODE_ENV='production';delete process.env.WEB_PUBLIC_ORIGIN;
    assert.throws(()=>assertSameOrigin(request),/not configured/);
    for(const value of ['not-a-url','https://user:password@converza.test','https://converza.test/path','https://converza.test?next=evil','file:///tmp/frontend']){
      process.env.WEB_PUBLIC_ORIGIN=value;assert.throws(()=>assertSameOrigin(request),/Invalid public origin/);
    }
  }finally{
    if(previous.origin===undefined)delete process.env.WEB_PUBLIC_ORIGIN;else process.env.WEB_PUBLIC_ORIGIN=previous.origin;
    if(previous.env===undefined)delete process.env.NODE_ENV;else process.env.NODE_ENV=previous.env;
  }
});

test('incomplete restored account resumes onboarding while a completed unpaid account resumes reveal',async()=>{
  for(const [passport,expected] of [[{owner_user_id:'owner',org_id:'persisted',onboarding_answers:{business_name:'Saved'}},'/onboarding'],[{owner_user_id:'owner',org_id:'persisted',onboarding_completed_at:'2026-01-01',paywall_status:'pending'},'/onboarding/reveal']]){
    const {restoreWorkspaceDestination}=loader({'@/lib/api/session':{restoreWorkspaceSession:async()=>({user:{id:'owner'},passport})}})('lib/access.ts');
    assert.equal(await restoreWorkspaceDestination(),expected);
  }
});

test('returning-user credentials are not subject to newly introduced sign-up complexity rules',()=>{
  const {isAuthFormValid}=loader()('lib/access.ts');
  const values={email:'owner@example.test',password:'legacy',phone:''};
  assert.equal(isAuthFormValid('signIn',values),true);
  assert.equal(isAuthFormValid('signUp',values),false);
  assert.equal(isAuthFormValid('signIn',{...values,password:''}),false);
  assert.equal(isAuthFormValid('signUp',{...values,password:'NewPassword1',phone:'+998901234567'}),true);
});
