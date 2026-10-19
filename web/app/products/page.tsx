"use client";
import {useCallback,useEffect,useState,type FormEvent} from "react";
import Link from "next/link";
import {memoryRequest,type ProductRecord} from "@/lib/api/memory";

const blank={name:"",description:"",price:"",currency:"USD",sku:""};
const input="mt-1 w-full rounded-lg border border-border bg-bg-elevated px-3 py-2 text-sm";

export default function ProductsPage(){
  const [products,setProducts]=useState<ProductRecord[]>([]);
  const [form,setForm]=useState(blank);
  const [editing,setEditing]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const load=useCallback(async()=>{const data=await memoryRequest<{products:ProductRecord[]}>("/products");setProducts(data.products);},[]);
  useEffect(()=>{void load().catch(error=>setMessage(error.message));},[load]);
  async function save(event:FormEvent){event.preventDefault();setBusy(true);setMessage("");try{
    const {sku,...fields}=form;
    const existing=products.find(row=>row.id===editing);
    await memoryRequest(`/products${editing?`/${editing}`:""}`,{method:editing?"PUT":"POST",body:JSON.stringify({...fields,metadata:{...existing?.metadata,sku}})});
    setForm(blank);setEditing(null);await load();setMessage("Saved. Agents can use the current price immediately.");
  }catch(error){setMessage(error instanceof Error?error.message:"Save failed");}finally{setBusy(false);}}
  async function remove(id:string){try{await memoryRequest(`/products/${id}`,{method:"DELETE"});await load();}catch(error){setMessage(error instanceof Error?error.message:"Delete failed");}}
  return <main className="h-full overflow-y-auto p-6 md:p-10"><div className="mx-auto max-w-5xl space-y-7">
    <header><h1 className="text-3xl font-medium tracking-tight">Products & pricing</h1><p className="mt-2 text-sm text-text-secondary">The current catalog agents use in buyer replies and creative briefs.</p><Link href="/settings/memory" className="mt-2 inline-block text-sm underline">FAQs and agent memory</Link></header>
    {message&&<p role="status" className="rounded-lg border border-border p-3 text-sm">{message}</p>}
    <form onSubmit={save} className="space-y-4 rounded-xl border border-border p-5"><h2 className="font-medium">{editing?"Edit product":"Add product"}</h2>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-xs">Name<input required maxLength={250} className={input} value={form.name} onChange={event=>setForm({...form,name:event.target.value})}/></label><label className="text-xs">SKU<input className={input} value={form.sku} onChange={event=>setForm({...form,sku:event.target.value})}/></label></div>
      <label className="block text-xs">Description<textarea rows={3} maxLength={12000} className={input} value={form.description} onChange={event=>setForm({...form,description:event.target.value})}/></label>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-xs">Current price<input required inputMode="decimal" type="number" min="0" step="0.000001" className={input} value={form.price} onChange={event=>setForm({...form,price:event.target.value})}/></label><label className="text-xs">Currency<input required pattern="[A-Z]{3}" maxLength={3} className={input} value={form.currency} onChange={event=>setForm({...form,currency:event.target.value.toUpperCase()})}/></label></div>
      <button disabled={busy} className="rounded-full bg-text-primary px-5 py-2 text-sm text-bg-elevated disabled:opacity-50">{busy?"Saving…":"Save product"}</button>{editing&&<button type="button" className="ml-3 text-sm underline" onClick={()=>{setForm(blank);setEditing(null);}}>Cancel edit</button>}
    </form>
    <div className="space-y-3">{products.length===0&&<p className="text-sm text-text-muted">Your catalog is empty. Add your first product above.</p>}{products.map(product=><article key={product.id} className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-border p-5"><div><h2 className="font-medium">{product.name}</h2><p className="mt-1 text-sm text-text-secondary">{product.description}</p><p className="mt-2 font-mono text-sm">{product.currency} {product.price}</p>{!!product.metadata?.sku&&<p className="mt-1 text-xs text-text-muted">SKU: {String(product.metadata.sku)}</p>}</div><div className="flex gap-4 text-xs"><button onClick={()=>{setEditing(product.id);setForm({name:product.name,description:product.description,price:String(product.price),currency:product.currency,sku:String(product.metadata?.sku??"")});}}>Edit price or details</button><button className="text-error" onClick={()=>void remove(product.id)}>Remove</button></div></article>)}</div>
  </div></main>;
}
