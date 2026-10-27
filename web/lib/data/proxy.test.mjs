import test from 'node:test';
import assert from 'node:assert/strict';
import loader from '../../tests/load.cjs';

process.env.BACKEND_URL = 'http://backend.test:8000';
process.env.BACKEND_API_KEY = 'private-service-key';
process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://auth.test';
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = 'anon';
const load = loader();
const route = load('app/api/backend/[...path]/route.ts');
function request(path, {token = 'user-token', method = 'GET', origin, headers = {}, search = ''} = {}) {
  const req = new Request('http://localhost:3000/api/backend/' + path.join('/') + search, {
    method, headers: {...(token ? {authorization: 'Bearer ' + token} : {}), ...(origin ? {origin} : {}), ...headers},
    ...(method === 'POST' ? {body: '{}'} : {}),
  });
  req.nextUrl = new URL(req.url);
  return route[method](req, {params: Promise.resolve({path})});
}
async function withFetch(run, upstream = () => new Response('{}')) {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({url: String(url), init});
    return String(url).startsWith('https://auth.test/') ? new Response(JSON.stringify({id: 'owner-a'})) : upstream();
  };
  try { await run(calls); } finally { globalThis.fetch = original; }
}
test('proxy rejects missing or invalid user sessions before adding service credentials', async () => {
  await withFetch(async calls => {
    assert.equal((await request(['api','squad','stream'], {token: null})).status, 401);
    assert.equal(calls.length, 0);
  });
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response('{}', {status: 401});
  try { assert.equal((await request(['api','squad','stream'])).status, 401); } finally { globalThis.fetch = original; }
});
test('proxy rejects absolute, encoded, traversal, internal and unlisted paths without upstream calls', async () => {
  await withFetch(async calls => {
    for (const path of [['https:', '', 'evil.test'], ['api','internal','jobs'], ['api','squad','..','internal'], ['api','%69nternal','jobs'], ['api','memory','org','%252e%252e'], ['api','memory','org%2f..','identity'], ['api','unknown'], ['api','squad\\internal'], ['api','llm','extract']]) {
      assert.ok((await request(path)).status >= 400, path.join('/'));
    }
    assert.equal(calls.length, 0);
  });
});
test('proxy enforces same origin and rejects cross-site requests', async () => {
  await withFetch(async calls => {
    assert.equal((await request(['api','squad','message'], {method:'POST', origin:'https://evil.test'})).status, 403);
    assert.equal((await request(['api','squad','stream'], {headers:{'sec-fetch-site':'cross-site'}})).status, 403);
    assert.equal(calls.length, 0);
  });
});
test('proxy forwards only trusted headers, validates SSE tokens and never follows redirects', async () => {
  await withFetch(async calls => {
    const response = await request(['api','squad','stream'], {token:null, search:'?org_id=org&access_token=sse-token', headers:{cookie:'private-cookie', 'x-supabase-access-token':'forged', 'x-api-key':'secret'}});
    assert.equal(response.status, 502);
    assert.equal(calls[0].init.headers.get('authorization'), 'Bearer sse-token');
    const upstream = calls[1];
    assert.equal(upstream.url, 'http://backend.test:8000/api/squad/stream?org_id=org');
    assert.equal(upstream.init.redirect, 'manual');
    assert.equal(upstream.init.headers.get('authorization'), 'Bearer private-service-key');
    assert.equal(upstream.init.headers.get('x-supabase-access-token'), 'sse-token');
    assert.equal(upstream.init.headers.get('cookie'), null);
    assert.equal(upstream.init.headers.get('x-api-key'), null);
    assert.equal(response.headers.get('location'), null);
    assert.equal(response.headers.get('set-cookie'), null);
  }, () => new Response(null, {status:302, headers:{location:'https://evil.test', 'set-cookie':'secret'}}));
});
test('session endpoint returns verified user and server passport for a fresh browser', async () => {
  const {GET} = load('app/api/session/route.ts');
  await withFetch(async calls => {
    const response = await GET(new Request('http://localhost:3000/api/session', {headers:{authorization:'Bearer user-token'}}));
    assert.deepEqual(await response.json(), {user:{id:'owner-a'}, passport:{org_id:'server-org', owner_user_id:'owner-a'}});
    assert.equal(calls[1].url, 'http://backend.test:8000/api/onboarding/state/owner-a');
  }, () => Response.json({passport:{org_id:'server-org', owner_user_id:'owner-a'}}));
});
