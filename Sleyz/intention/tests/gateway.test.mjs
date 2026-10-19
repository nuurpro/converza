import test from 'node:test';
import assert from 'node:assert/strict';
import { extractJSON } from '../src/services/gateway.ts';

test('qualifier sends extraction to trusted backend without direct provider credentials',async()=>{
  const previous=global.fetch,oldKey=process.env.LLM_SERVICE_API_KEY;
  let request;
  process.env.LLM_SERVICE_API_KEY='test-service-key';
  global.fetch=async(url,init)=>{request={url,init};return new Response(JSON.stringify({intent:'LEAD_HOT'}),{status:200});};
  try{
    const value=await extractJSON([{role:'user',content:'Training?'}],{type:'object'},1024);
    assert.equal(value.intent,'LEAD_HOT');
    assert.equal(request.url,'http://127.0.0.1:8000/api/internal/llm/extract');
    assert.equal(request.init.headers['x-llm-service-key'],'test-service-key');
    const body=JSON.parse(request.init.body);
    assert.equal(body.max_tokens,1024);assert.equal(body.model,undefined);assert.equal(body.temperature,undefined);
  }finally{global.fetch=previous;if(oldKey===undefined)delete process.env.LLM_SERVICE_API_KEY;else process.env.LLM_SERVICE_API_KEY=oldKey;}
});

test('missing backend service credential fails before network use',async()=>{
  const oldKey=process.env.LLM_SERVICE_API_KEY;delete process.env.LLM_SERVICE_API_KEY;
  try{await assert.rejects(()=>extractJSON([],{type:'object'},1024),/LLM_SERVICE_API_KEY/);}
  finally{if(oldKey!==undefined)process.env.LLM_SERVICE_API_KEY=oldKey;}
});
