import test from 'node:test';
import assert from 'node:assert/strict';
import {scriptDecisionRequest, campaignCapabilities, keepScriptEditor} from './milo.ts';
const scenes=[{spoken_narration:'Buyer words',visual_broll_cues:'Show material',on_screen_text:'Verified spec'}];
const campaign={id:'c',org_id:'org',revision:2,status:'awaiting_review',script_status:'pending',compliance:{passed:true,violations:[]},artifact:{video_script:scenes}};
test('script decisions pin tenant, revision and idempotency key; editing never approves',()=>{
 const request=scriptDecisionRequest('org/one',campaign,'edit','stable-key',scenes);
 assert.equal(request.path,'/api/milo/org%2Fone/campaigns/c/script/edit');
 assert.equal(request.init.headers['Idempotency-Key'],'stable-key');
 assert.deepEqual(JSON.parse(request.init.body),{expected_revision:2,video_script:scenes});
 assert.throws(()=>scriptDecisionRequest('org', {...campaign,revision:0},'approve','key'),/revision/);
 assert.throws(()=>scriptDecisionRequest('org',campaign,'edit','key',[]),/scene/);
});
test('approval requires compliant saved current script and a reviewable campaign',()=>{
 assert.equal(campaignCapabilities(campaign,false,false).canApprove,true);
 for(const [change,dirty,stale] of [[{},true,false],[{},false,true],[{status:'blocked'},false,false],[{compliance:{passed:false}},false,false],[{script_status:'approved'},false,false],[{build_status:'queued'},false,false]])
 assert.equal(campaignCapabilities({...campaign,...change},dirty,stale).canApprove,false);
});
test('polling retains in-progress edits and their original expected revision',()=>{
 const editor={revision:2,scenes:[{...scenes[0],spoken_narration:'Unsaved'}],dirty:true};
 assert.equal(keepScriptEditor(editor,{...campaign,revision:3}),editor);
 assert.deepEqual(keepScriptEditor({...editor,dirty:false},{...campaign,revision:3}),{revision:3,scenes,dirty:false});
});
test('script edit rejects empty visual instructions and overlong text before submitting',()=>{
 assert.throws(()=>scriptDecisionRequest('org',campaign,'edit','key',[{...scenes[0],visual_broll_cues:''}]),/visual/i);
 assert.throws(()=>scriptDecisionRequest('org',campaign,'edit','key',[{...scenes[0],on_screen_text:'a'.repeat(501)}]),/500/);
});
test('rejected scripts cannot be edited or approved and blocked scripts may be rejected',()=>{
 assert.equal(campaignCapabilities({...campaign,script_status:'rejected'},false,false).canEdit,false);
 assert.equal(campaignCapabilities({...campaign,script_status:'rejected'},false,false).canApprove,false);
 assert.equal(campaignCapabilities({...campaign,status:'blocked'},false,false).canReject,true);
});
