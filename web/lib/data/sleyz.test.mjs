import test from 'node:test';
import assert from 'node:assert/strict';
import { draftCapabilities, simulationRequest, productCommerceFields, withUnlinkedDrafts } from './sleyz.ts';

test('simulated and superseded drafts cannot be delivered or resolved', () => {
  const draft={id:'d',agent_slug:'sleyz',prospect_id:'p',status:'APPROVED',delivery_status:'idle'};
  assert.equal(draftCapabilities(draft).canDeliver,true);
  assert.equal(draftCapabilities({...draft,simulated:true}).canDeliver,false);
  assert.equal(draftCapabilities({...draft,superseded_by:'new'}).canDeliver,false);
  assert.equal(draftCapabilities({...draft,status:'PUBLISHED',simulated:true}).canResolve,false);
  assert.equal(draftCapabilities({...draft,delivery_status:'ambiguous'}).canDeliver,false);
  assert.equal(draftCapabilities({...draft,delivery_status:'failed',delivery_error:'catalog_changed: product price changed'}).canDeliver,false);
  assert.equal(draftCapabilities({...draft,delivery_status:'failed',delivery_error:'catalog_changed: product price changed'}).canRefresh,true);
});

test('simulation request preserves tenant and explicit idempotency key', () => {
  const request=simulationRequest('org',{platform:'instagram',customer_id:' 123 ',customer_handle:' @buyer ',text:' Can I buy two? '},'key');
  assert.equal(request.path,'/api/simulate/inbound-dm');
  assert.equal(request.init.method,'POST');
  assert.equal(request.init.headers['Idempotency-Key'],'key');
  assert.deepEqual(JSON.parse(request.init.body),{org_id:'org',platform:'instagram',customer_id:'123',customer_handle:'@buyer',text:'Can I buy two?'});
  assert.throws(()=>simulationRequest('org',{platform:'telegram',customer_id:'',text:'Hi'},'key'),/Customer/);
  assert.throws(()=>simulationRequest('org',{platform:'telegram',customer_id:'x',text:' '},'key'),/Message/);
});

test('catalog payload represents unknown inventory and enforces safe checkout templates', () => {
  assert.deepEqual(productCommerceFields({sku:' A-1 ',stock_count:'',checkout_url_template:''}),{sku:'A-1',stock_count:null,checkout_url_template:null});
  assert.equal(productCommerceFields({sku:'',stock_count:'0',checkout_url_template:'https://shop.example/pay?sku={sku}&q={quantity}'}).stock_count,0);
  assert.throws(()=>productCommerceFields({sku:'a',stock_count:'-1',checkout_url_template:''}),/Stock/);
  assert.throws(()=>productCommerceFields({sku:'a',stock_count:'1.5',checkout_url_template:''}),/Stock/);
  assert.throws(()=>productCommerceFields({sku:'a',stock_count:'',checkout_url_template:'http://shop.example/{sku}'}),/HTTPS/);
  assert.throws(()=>productCommerceFields({sku:'a',stock_count:'',checkout_url_template:'https://shop.example/{secret}'}),/placeholder/);
});

test('inbound drafts render even when a linked status message belongs to another sender', () => {
  const draft={id:'d',org_id:'org',agent_slug:'sleyz',status:'AWAITING_HITL'};
  const notice={id:'notice',sender_slug:'converza',hitl_draft_id:'d'};
  assert.equal(withUnlinkedDrafts([notice],{d:draft}).length,2);
  const own={id:'own',sender_slug:'sleyz',hitl_draft_id:'d'};
  assert.equal(withUnlinkedDrafts([own],{d:draft}).length,1);
});
