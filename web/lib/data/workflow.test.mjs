import test from 'node:test';
import assert from 'node:assert/strict';
import { applyWorkspaceEvent, emptyWorkspace, presentationStatus } from './workflow.ts';

test('snapshot hydrates authoritative drafts independently of message text', () => {
  const state = applyWorkspaceEvent(emptyWorkspace(), { type: 'snapshot', cursor: 5, drafts: [{id:'d',status:'APPROVED',revision:2}], messages:[{id:'m',content:'HITL rejected',hitl_draft_id:'d'}], steps:[] });
  assert.equal(state.drafts.d.status, 'APPROVED');
  assert.equal(state.cursor, 5);
  assert.equal(presentationStatus(state.drafts.d.status), 'approved');
});

test('duplicate and stale transitions cannot restore approval controls', () => {
  let state = applyWorkspaceEvent(emptyWorkspace(), {type:'draft_transition', event_id:7, row:{id:'d',status:'PUBLISHED',revision:4}});
  state = applyWorkspaceEvent(state, {type:'draft_transition', event_id:8, row:{id:'d',status:'AWAITING_HITL',revision:2}});
  assert.equal(state.drafts.d.status, 'PUBLISHED');
  assert.equal(presentationStatus(state.drafts.d.status), 'published');
});

test('new snapshot removes forgotten rows and retains its cursor', () => {
  let state = applyWorkspaceEvent(emptyWorkspace(), {type:'squad_message',event_id:1,row:{id:'m'}});
  state = applyWorkspaceEvent(state, {type:'snapshot',cursor:10,drafts:[],messages:[],steps:[]});
  assert.equal(state.messages.length,0);
  assert.equal(state.cursor,10);
});
