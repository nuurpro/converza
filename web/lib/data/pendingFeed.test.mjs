import test from 'node:test';
import assert from 'node:assert/strict';
import loader from '../../tests/load.cjs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

test('pending query uses authenticated proxy, cursor and rejects upstream errors',async()=>{
  const calls=[];
  const {fetchPendingFeed}=loader({'@/lib/api/session':{authenticatedFetch:async(...args)=>{
    calls.push(args);return new Response(JSON.stringify({items:[],next_cursor:null}),{status:200});
  }}})('lib/api/feed.ts');
  await fetchPendingFeed('org/a','opaque cursor');
  assert.match(calls[0][0],/^\/api\/backend\/api\/feed\/pending\?/);
  const query=new URL(calls[0][0],'http://localhost').searchParams;
  assert.equal(query.get('org_id'),'org/a');assert.equal(query.get('cursor'),'opaque cursor');
  assert.equal(calls[0][1].cache,'no-store');
  const failing=loader({'@/lib/api/session':{authenticatedFetch:async()=>new Response(JSON.stringify({detail:'Refresh workspace'}),{status:403})}})('lib/api/feed.ts');
  await assert.rejects(()=>failing.fetchPendingFeed('a'),/Refresh workspace/);
});

const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
test('continuous SSE invalidations cannot starve successful feed pages',async()=>{
  const {createPendingFeedController}=loader({'@/lib/api/session':{}})('lib/api/feed.ts');
  const commits=[],pending=[];
  const controller=createPendingFeedController('a',page=>commits.push(page),()=>{}, {
    pollMs:100000,fetchPage:()=>new Promise(resolve=>pending.push(resolve)),
  });
  try{
    for(let n=0;n<8;n++){
      controller.refresh();pending.shift()({items:[{id:`workflow:${n}`}],next_cursor:null});await tick();
      assert.equal(commits.length,n+1);
    }
  }finally{controller.stop();pending.forEach(resolve=>resolve({items:[],next_cursor:null}));await tick();}
});
test('feed publishes ordered snapshots and coalesces SSE/reconnect follow-up reads',async()=>{
  const {createPendingFeedController}=loader({'@/lib/api/session':{}})('lib/api/feed.ts');
  const commits=[],errors=[],requests=[];let resolveFirst;
  const controller=createPendingFeedController('a',value=>commits.push(value),error=>errors.push(error),{
    pollMs:100000,fetchPage:async(org,cursor,signal)=>{
      requests.push([org,cursor,signal]);
      if(requests.length===1)return new Promise(resolve=>{resolveFirst=resolve;});
      return cursor?{items:[{id:'workflow:2'}],next_cursor:null}:{items:[{id:'milo:1'}],next_cursor:'second'};
    },
  });
  controller.refresh();controller.refresh(); // relevant SSE change while initial request is in flight
  resolveFirst({items:[{id:'earlier-snapshot'}],next_cursor:null});await tick();await tick();
  assert.equal(commits.length,2);assert.equal(commits[0].items[0].id,'earlier-snapshot');assert.equal(commits[1].items[0].id,'milo:1');
  controller.loadMore();await tick();await tick();
  assert.deepEqual(commits.at(-1).items.map(item=>item.id),['milo:1','workflow:2']);
  assert.equal(commits.at(-1).next_cursor,null);
  controller.refresh();await tick();await tick(); // reconnect restores the entire loaded range
  assert.deepEqual(commits.at(-1).items.map(item=>item.id),['milo:1','workflow:2']);
  assert.equal(errors.at(-1),null);
  controller.stop();assert.equal(requests[0][2].aborted,true);
});

test('unmount/account switching aborts old feed requests and ignores late responses',async()=>{
  const {createPendingFeedController}=loader({'@/lib/api/session':{}})('lib/api/feed.ts');
  let finish;const commits=[],errors=[];
  const controller=createPendingFeedController('old',value=>commits.push(value),error=>errors.push(error),{
    pollMs:100000,fetchPage:async()=>new Promise(resolve=>{finish=resolve;}),
  });
  controller.stop();finish({items:[{id:'old-tenant'}],next_cursor:null});await tick();
  assert.equal(commits.length,0);assert.equal(errors.length,0);
});

test('recovery polling retries errors, retaining visible data until a confirmed replacement',async()=>{
  const {createPendingFeedController}=loader({'@/lib/api/session':{}})('lib/api/feed.ts');
  const commits=[],errors=[];let attempts=0;
  const controller=createPendingFeedController('a',page=>commits.push(page),error=>errors.push(error),{
    pollMs:5,fetchPage:async()=>{
      attempts++;
      if(attempts===1)throw new Error('Disconnected');
      return {items:[{id:'recovered'}],next_cursor:null};
    },
  });
  try {
    for(let n=0;n<30&&commits.length===0;n++)await new Promise(resolve=>setTimeout(resolve,5));
    assert.equal(errors[0],'Disconnected');
    assert.equal(commits[0].items[0].id,'recovered');
    assert.equal(errors.at(-1),null);
  } finally {controller.stop();}
});

test('dashboard preserves mixed chronology, pins source/revision, and retains uncertain mutation identity',async()=>{
  const rows=[
    {id:'milo:c',kind:'milo',source_id:'c',revision:7,restrictions:{can_approve:false,reasons:['Grant needs verification']},payload:{campaign:{id:'c',status:'blocked',artifact:{trigger_reason:'First campaign'}},review_href:'/agents/milo#campaign-c'}},
    {id:'workflow:d',kind:'workflow',source_id:'d',revision:3,restrictions:{can_approve:true,can_edit:true,can_reject:true,reasons:[]},payload:{draft:{id:'d',agent_slug:'sleyz',revision:3,status:'AWAITING_HITL',draft_content:'Second reply'}}},
    {id:'milo:c2',kind:'milo',source_id:'c2',revision:2,restrictions:{can_approve:true,reasons:[]},payload:{campaign:{id:'c2',status:'awaiting_review',artifact:{trigger_reason:'Third campaign'}},review_href:'/agents/milo#campaign-c2'}},
  ];
  let index=0,review;const calls=[];
  const mockReact={...React,useEffect(){},useState:initial=>[index++===0?rows:initial,()=>{}],useRef:current=>({current})};
  const {default:Dashboard}=loader({
    react:mockReact,
    '@/lib/hooks/useMiloOrg':{useMiloOrg:()=> 'a'},
    '@/lib/hooks/useWorkspace':{useWorkspace:()=>({drafts:{},steps:[],setError(){}})},
    '@/lib/api/feed':{},
    '@/lib/api/workspace':{
      mapSquadMessage:(_,draft)=>({hitlCard:{id:draft.id,content:draft.draft_content,revision:draft.revision}}),
      resolveHitlDraft:async(...args)=>{calls.push(args);if(calls.length===1)throw new Error('Response lost');return {status:'APPROVED'};},
    },
    '@/components/workspace/AgentWorkspace':{
      StatCard:()=>null,HitlCard:props=>{review=props;return React.createElement('p',null,props.card.content);},
    },
  })('app/page.tsx');
  const html=renderToStaticMarkup(React.createElement(Dashboard));
  assert.ok(html.indexOf('First campaign')<html.indexOf('Second reply'));
  assert.ok(html.indexOf('Second reply')<html.indexOf('Third campaign'));
  assert.ok(html.includes('Grant needs verification'));
  assert.ok(html.includes('/agents/milo#campaign-c'));
  review.onApprove();review.onApprove();await tick();
  assert.equal(calls.length,1); // double click cannot create a second decision
  review.onApprove();await tick();
  assert.equal(calls.length,2);
  assert.equal(calls[0][0],'d');assert.equal(calls[0][1],'approve');assert.equal(calls[0][3],3);
  assert.ok(calls[0][4]);assert.equal(calls[0][4],calls[1][4]);
});
