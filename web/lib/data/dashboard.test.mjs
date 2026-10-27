import test from 'node:test';
import assert from 'node:assert/strict';
import loader from '../../tests/load.cjs';
test('dashboard surfaces pending Milo review campaigns with links to the existing reviewer',()=>{
  const {pendingCampaignReviews}=loader()('lib/data/dashboard.ts');
  const rows=pendingCampaignReviews([
    {id:'review',status:'awaiting_review',script_status:'pending',artifact:{trigger_reason:'New launch'}},
    {id:'blocked',status:'blocked',script_status:'pending'},
    {id:'approved',status:'awaiting_review',script_status:'approved'},
    {id:'generating',status:'generating',script_status:'pending'},
  ]);
  assert.deepEqual(rows.map(row=>row.id),['review','blocked']);
  assert.equal(rows[0].href,'/agents/milo#campaign-review');
});
