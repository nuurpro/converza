import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {createRequire,Module} from 'node:module';

const require=createRequire(import.meta.url);
const ts=require('typescript');
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
// Execute the actual TSX component in memory; no build output is written.
const filename=fileURLToPath(new URL('../../components/workspace/AgentWorkspace.tsx',import.meta.url));
const compiled=new Module(filename);
compiled.filename=filename;
compiled.paths=Module._nodeModulePaths(fileURLToPath(new URL('../../components/workspace/',import.meta.url)));
compiled._compile(ts.transpileModule(readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,filename);
const {HitlCard}=compiled.exports;
const artifact={schema_version:1,customer_handle:'@buyer',platform:'instagram',incoming_message:'Can I buy two?',intent_score:.9,intent:'HOT',detected_objection:'price',cited_brand_passport_atoms:[{source_id:'source-1',revision:3,atom_index:0}],draft_reply:'Original generated reply',checkout_link:'https://shop.example/checkout?sku=A',product_snapshot:[{id:'p',sku:'A',name:'Serum',price:'12.00',currency:'USD',stock_count:5,revision:2}],quantity:2,operator_notes:['Confirm selection']};

test('review card shows authoritative edited reply and immutable generated evidence',()=>{
  const html=renderToStaticMarkup(React.createElement(HitlCard,{card:{id:'d',label:'Review',status:'edited',content:'Approved edited reply',artifact,learningStatus:'failed',learningError:'Analysis failed'},onApprove(){},onEdit(){},onSkip(){},onRetryLearning(){}}));
  for(const text of ['Approved edited reply','Original generated reply','HOT','90% readiness','@buyer','Can I buy two?','Objection: price','Serum','5 in stock','quantity 2','source-1','revision 3','Confirm selection','Retry learning','Analysis failed'])assert.ok(html.includes(text),text);
  assert.ok(html.includes('href="https://shop.example/checkout?sku=A"'));
});

test('superseded simulated drafts expose no approval or delivery controls',()=>{
  const html=renderToStaticMarkup(React.createElement(HitlCard,{card:{id:'d',label:'Review',status:'pending',content:'Reply',simulated:true,supersededBy:'replacement',canDeliver:false},onApprove(){},onEdit(){},onSkip(){}}));
  assert.ok(html.includes('Simulation'));
  assert.ok(html.includes('Replaced by a refreshed draft'));
  assert.equal(html.includes('Send buyer reply'),false);
  assert.equal(html.includes('>Approve<'),false);
});
