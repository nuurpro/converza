import test from 'node:test';
import assert from 'node:assert/strict';
import * as vea from './vea.ts';

test('video URLs only permit local static paths and HTTP media',()=>{
 assert.equal(vea.safeVideoUrl('/static/vea/render.mp4'),'/static/vea/render.mp4');
 for(const value of ['javascript:alert(1)','data:video/mp4;base64,AA','//evil.example/x','/\\evil.example/x'])assert.equal(vea.safeVideoUrl(value),undefined);
 assert.equal(vea.safeVideoUrl('https://media.example/video.mp4'),'https://media.example/video.mp4');
});
test('variant mutations carry revisions and stable idempotency keys',()=>{
 const variant={id:'v/a',revision:4};
 const request=vea.variantMutationRequest('org/a',variant,'swap','stable-key',{segment_id:'s',asset_id:'a'});
 assert.equal(request.path,'/api/vea/org%2Fa/variants/v%2Fa/swap');
 assert.equal(request.init.headers['Idempotency-Key'],'stable-key');
 assert.deepEqual(JSON.parse(request.init.body),{expected_revision:4,segment_id:'s',asset_id:'a'});
 assert.throws(()=>vea.variantMutationRequest('org',{id:'v',revision:0},'retry','k'),/revision/);
});
test('only current complete videos can be approved or exported; failed renders can retry',()=>{
 assert.deepEqual(vea.videoCapabilities({status:'completed',artifact:{video_url:'/static/v.mp4'}},{status:'AWAITING_HITL'}),{canApprove:true,canExport:false,canSwap:true,canRetry:false});
 assert.equal(vea.videoCapabilities({status:'completed',artifact:{video_url:'/static/v.mp4'}},{status:'APPROVED',superseded_by:'new'}).canExport,false);
 assert.equal(vea.videoCapabilities({status:'failed'},undefined).canRetry,true);
 assert.equal(vea.videoCapabilities({status:'rendering'},undefined).canRetry,false);
});
test('replacement picker offers only video clips long enough for the selected segment',()=>{
 const clips=[{id:'video',kind:'video',duration_sec:3,tags:[]},{id:'music',kind:'music',duration_sec:90,tags:[]},{id:'short',kind:'video',duration_sec:2.9,tags:[]},{id:'unknown',duration_sec:4,tags:[]}];
 assert.deepEqual(vea.replacementAssets(clips,{start_ms:0,end_ms:3000}).map(asset=>asset.id),['video']);
 assert.deepEqual(vea.replacementAssets(clips,undefined),[]);
});
