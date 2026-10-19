import test from 'node:test';
import assert from 'node:assert/strict';
import { subscribeWorkspaceTransport } from './workspaceStream.ts';

const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup(){
  const calls=[],events=[],sources=[];
  let auth;
  const dependencies={
    getOrgId:owner=>owner?'org-'+owner:'org-a',
    createSource:async(org,cursor)=>{calls.push({org,cursor});const source={close(){this.closed=true;},closed:false};sources.push(source);return source;},
    subscribeAuth:callback=>{auth=callback;return()=>{};},
  };
  const stop=subscribeWorkspaceTransport(event=>events.push(event),()=>{},dependencies);
  return {calls,events,sources,stop,auth:(event,id)=>auth(event,id)};
}

test('token refresh resumes same organization with last cursor',async()=>{
  const f=setup();await settle();
  f.sources[0].onmessage({data:JSON.stringify({type:'draft_transition',event_id:9,row:{id:'d',revision:3}}),lastEventId:'9'});
  f.auth('TOKEN_REFRESHED','a');await settle();
  assert.deepEqual(f.calls[1],{org:'org-a',cursor:9});
  f.stop();
});

test('signing into another organization clears prior data and requests a snapshot',async()=>{
  const f=setup();await settle();
  f.sources[0].onmessage({data:JSON.stringify({type:'snapshot',cursor:8,drafts:[],messages:[],steps:[]}),lastEventId:'8'});
  f.auth('SIGNED_IN','b');await settle();
  assert.deepEqual(f.calls[1],{org:'org-b',cursor:undefined});
  assert.deepEqual(f.events.at(-1),{type:'snapshot',cursor:0,drafts:[],messages:[],steps:[]});
  assert.equal(f.sources[0].closed,true);f.stop();
});

test('signout invalidates an in-flight source and clears the tenant snapshot',async()=>{
  let finish,auth;const source={closed:false,close(){this.closed=true;}};const events=[];
  const stop=subscribeWorkspaceTransport(event=>events.push(event),()=>{}, {
    getOrgId:()=> 'org-a',createSource:()=>new Promise(resolve=>{finish=resolve;}),
    subscribeAuth:callback=>{auth=callback;return()=>{};},
  });
  auth('SIGNED_OUT');finish(source);await settle();
  assert.equal(source.closed,true);assert.equal(source.onmessage,undefined);
  assert.equal(events.at(-1).cursor,0);stop();
});
