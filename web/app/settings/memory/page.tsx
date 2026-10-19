"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { memoryRequest, type IndexJob, type KnowledgeRecord } from "@/lib/api/memory";

const input = "w-full rounded-lg border border-border bg-bg-elevated px-3 py-2 text-sm text-text-primary";

export default function MemoryPage() {
  const [records,setRecords] = useState<KnowledgeRecord[]>([]);
  const [jobs,setJobs] = useState<IndexJob[]>([]);
  const [editing,setEditing] = useState<string|null>(null);
  const [kind,setKind] = useState("faq");
  const [title,setTitle] = useState("");
  const [content,setContent] = useState("");
  const [query,setQuery] = useState("");
  const [searching,setSearching] = useState(false);
  const [busy,setBusy] = useState(false);
  const [message,setMessage] = useState("");
  const load = useCallback(async()=>{
    const [knowledge,indexing] = await Promise.all([
      memoryRequest<{knowledge:KnowledgeRecord[]}>("/knowledge"),
      memoryRequest<{jobs:IndexJob[]}>("/jobs"),
    ]);
    setRecords(knowledge.knowledge);setJobs(indexing.jobs);
    setSearching(false);
  },[]);
  useEffect(()=>{void load().catch(error=>setMessage(error.message));},[load]);
  async function save(event:FormEvent) {
    event.preventDefault();setBusy(true);setMessage("");
    try {
      await memoryRequest(`/knowledge${editing?`/${editing}`:""}`,{method:editing?"PUT":"POST",body:JSON.stringify({kind,title,content})});
      setEditing(null);setTitle("");setContent("");setQuery("");await load();setMessage("Saved. Search uses current text while indexing finishes.");
    } catch(error){setMessage(error instanceof Error?error.message:"Save failed");} finally {setBusy(false);}
  }
  async function forget(record:KnowledgeRecord) {
    try {await memoryRequest(record.source_id?`/sources/${record.source_id}`:`/knowledge/${record.id}`,{method:"DELETE"});await load();setMessage("Forgotten. This source is excluded from retrieval.");}
    catch(error){setMessage(error instanceof Error?error.message:"Forget failed");}
  }
  async function search(event:FormEvent) {
    event.preventDefault();setMessage("");
    try {
      if(!query.trim()){await load();return;}
      const result=await memoryRequest<{results:KnowledgeRecord[]}>(`/search?q=${encodeURIComponent(query)}`);
      setRecords(result.results.map(row=>({...row,id:row.id??row.source_id!})));
      setSearching(true);
    }catch(error){setMessage(error instanceof Error?error.message:"Search failed");}
  }
  return <div className="space-y-8">
    <header><h2 className="text-[28px] font-medium tracking-tight text-text-primary">Agent memory</h2>
      <p className="mt-2 text-sm text-text-secondary">Current facts, FAQs, and resolved buyer objections. <Link className="underline" href="/products">Manage products and prices</Link>.</p></header>
    {message&&<p role="status" className="rounded-lg border border-border p-3 text-sm">{message}</p>}
    <form onSubmit={search} className="flex gap-2"><input aria-label="Search memory" className={input} value={query} onChange={event=>setQuery(event.target.value)} placeholder="Search facts or objections…"/><button className="rounded-lg border border-border px-4">Search</button></form>
    <form onSubmit={save} className="space-y-3 rounded-xl border border-border p-4">
      <h3 className="font-medium">{editing?"Edit knowledge":"Add knowledge"}</h3>
      <label className="block text-xs">Type<select aria-label="Knowledge type" className={input} value={kind} onChange={event=>setKind(event.target.value)}><option value="faq">FAQ</option><option value="manual">Brand knowledge</option></select></label>
      <label className="block text-xs">Title<input className={input} required maxLength={250} value={title} onChange={event=>setTitle(event.target.value)}/></label>
      <label className="block text-xs">Exact question and answer or fact<textarea className={input} required rows={4} maxLength={40000} value={content} onChange={event=>setContent(event.target.value)}/></label>
      <button disabled={busy} className="rounded-full bg-text-primary px-5 py-2 text-sm text-bg-elevated disabled:opacity-50">{busy?"Saving…":"Save knowledge"}</button>
      {editing&&<button type="button" className="ml-3 text-sm underline" onClick={()=>{setEditing(null);setTitle("");setContent("");}}>Cancel edit</button>}
    </form>
    <div className="space-y-3">{records.length===0&&<p className="text-sm text-text-muted">No knowledge found. Add an FAQ or a product to begin.</p>}
      {records.map(record=><article key={record.id} className="rounded-xl border border-border p-4">
        <div className="flex items-start justify-between gap-4"><div><h3 className="font-medium">{record.title}</h3><p className="mt-1 text-xs text-text-muted">{record.kind} · revision {record.revision}{record.updated_at?` · ${new Date(record.updated_at).toLocaleString()}`:""}</p></div>
          <div className="flex gap-3 text-xs">{!searching&&!record.read_only&&["faq","manual"].includes(record.kind)&&<button onClick={()=>{setEditing(record.id);setKind(record.kind);setTitle(record.title);setContent(record.content);}}>Edit</button>}<button className="text-error" onClick={()=>void forget(record)}>Forget</button></div></div>
        <p className="mt-3 whitespace-pre-wrap text-sm">{record.content}</p>
        {record.summary&&<p className="mt-3 border-t border-border pt-3 text-sm text-text-secondary">Summary: {record.summary}</p>}
        {record.atoms?.map((atom,i)=><blockquote key={i} className="mt-2 border-l-2 border-border pl-3 text-sm"><p>{atom.objection||atom.text}</p>{atom.answer&&<p className="mt-1">{atom.answer}</p>}{atom.resolved_at&&<time className="text-xs text-text-muted">{atom.resolved_at}</time>}</blockquote>)}
      </article>)}
    </div>
    <section className="border-t border-border pt-5"><div className="flex items-center justify-between"><h3 className="font-medium">Background indexing</h3><button className="text-xs underline" onClick={()=>void load().catch(error=>setMessage(error.message))}>Refresh status</button></div>
      {jobs.length===0&&<p className="mt-2 text-sm text-text-muted">No indexing jobs.</p>}
      {jobs.map(job=><div key={job.id} className="flex flex-wrap items-center gap-3 border-b border-border py-3 text-sm"><span>{job.source_id.slice(0,8)}</span><span>{job.status}</span>{(job.error||job.last_error)&&<span className="text-error">{job.error||job.last_error}</span>}{job.status==="failed"&&<button className="underline" onClick={()=>void memoryRequest(`/jobs/${job.id}/retry`,{method:"POST"}).then(load).catch(error=>setMessage(error.message))}>Retry indexing</button>}</div>)}
    </section>
  </div>;
}
