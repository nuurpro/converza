"use client";
import {useCallback,useEffect,useRef,useState,type FormEvent} from "react";
import Link from "next/link";
import {memoryRequest,type ProductRecord} from "@/lib/api/memory";
import {productCommerceFields} from "@/lib/data/sleyz";
import {useMiloOrg} from '@/lib/hooks/useMiloOrg';

const blank={name:"",description:"",price:"",currency:"USD",sku:"",stock_count:"",checkout_url_template:""};
const input="mt-1 w-full rounded-lg border border-border bg-bg-elevated px-3 py-2 text-sm";

export default function ProductsPage(){
  const org=useMiloOrg();return org?<Products key={org} org={org}/>:<p className="p-5 text-sm">Sign in to manage products.</p>;
}
function Products({org}:{org:string}){
  const [products,setProducts]=useState<ProductRecord[]>([]);
  const [form,setForm]=useState(blank);
  const [editing,setEditing]=useState<string|null>(null);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const alive=useRef(false),lock=useRef(false),sequence=useRef(0);
  const load=useCallback(async()=>{if(!alive.current)return;const request=++sequence.current;const data=await memoryRequest<{products:ProductRecord[]}>("/products",undefined,org);if(alive.current&&request===sequence.current)setProducts(data.products);},[org]);
  useEffect(()=>{alive.current=true;void load().catch(error=>{if(alive.current)setMessage(error.message);});return()=>{alive.current=false;sequence.current++;};},[load]);
  async function save(event:FormEvent){event.preventDefault();if(lock.current)return;lock.current=true;setBusy(true);setMessage("");try{
    const {sku,stock_count,checkout_url_template,...fields}=form;
    const commerce=productCommerceFields({sku,stock_count,checkout_url_template});
    const existing=products.find(row=>row.id===editing);
    await memoryRequest(`/products${editing?`/${editing}`:""}`,{method:editing?"PUT":"POST",body:JSON.stringify({...fields,...commerce,metadata:{...existing?.metadata,sku:commerce.sku}})},org);
    if(!alive.current)return;setForm(blank);setEditing(null);await load();if(alive.current)setMessage("Saved. Agents can use the current price immediately.");
  }catch(error){if(alive.current)setMessage(error instanceof Error?error.message:"Save failed");}finally{lock.current=false;if(alive.current)setBusy(false);}}
  async function remove(id:string){if(lock.current)return;lock.current=true;try{await memoryRequest(`/products/${id}`,{method:"DELETE"},org);await load();}catch(error){if(alive.current)setMessage(error instanceof Error?error.message:"Delete failed");}finally{lock.current=false;}}
  return <main className="h-full overflow-y-auto p-6 md:p-10"><div className="mx-auto max-w-5xl space-y-7">
    <header><h1 className="text-3xl font-medium tracking-tight">Products & pricing</h1><p className="mt-2 text-sm text-text-secondary">The current catalog agents use in buyer replies and creative briefs.</p><Link href="/settings/memory" className="mt-2 inline-block text-sm underline">FAQs and agent memory</Link></header>
    {message&&<p role="status" className="rounded-lg border border-border p-3 text-sm">{message}</p>}
    <form onSubmit={save} className="space-y-4 rounded-xl border border-border p-5"><h2 className="font-medium">{editing?"Edit product":"Add product"}</h2>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-xs">Name<input required maxLength={250} className={input} value={form.name} onChange={event=>setForm({...form,name:event.target.value})}/></label><label className="text-xs">SKU<input className={input} value={form.sku} onChange={event=>setForm({...form,sku:event.target.value})}/></label></div>
      <label className="block text-xs">Description<textarea rows={3} maxLength={12000} className={input} value={form.description} onChange={event=>setForm({...form,description:event.target.value})}/></label>
      <div className="grid gap-4 sm:grid-cols-2"><label className="text-xs">Current price<input required inputMode="decimal" type="number" min="0" step="0.000001" className={input} value={form.price} onChange={event=>setForm({...form,price:event.target.value})}/></label><label className="text-xs">Currency<input required pattern="[A-Z]{3}" maxLength={3} className={input} value={form.currency} onChange={event=>setForm({...form,currency:event.target.value.toUpperCase()})}/></label></div>
      <label className="block text-xs">Stock count · leave blank if unknown<input type="number" min="0" step="1" inputMode="numeric" className={input} value={form.stock_count} onChange={event=>setForm({...form,stock_count:event.target.value})}/></label>
      <label className="block text-xs">Merchant checkout URL template<input className={input} value={form.checkout_url_template} onChange={event=>setForm({...form,checkout_url_template:event.target.value})} placeholder="https://shop.example/checkout?sku={sku}&quantity={quantity}"/><span className="mt-1 block text-text-muted">HTTPS only. Use {"{sku}"} and {"{quantity}"} for checkout values. Leave blank to disable checkout links.</span></label>
      <button disabled={busy} className="rounded-full bg-text-primary px-5 py-2 text-sm text-bg-elevated disabled:opacity-50">{busy?"Saving…":"Save product"}</button>{editing&&<button type="button" className="ml-3 text-sm underline" onClick={()=>{setForm(blank);setEditing(null);}}>Cancel edit</button>}
    </form>
    <div className="space-y-3">{products.length===0&&<p className="text-sm text-text-muted">Your catalog is empty. Add your first product above.</p>}{products.map(product=><article key={product.id} className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-border p-5"><div><h2 className="font-medium">{product.name}</h2><p className="mt-1 text-sm text-text-secondary">{product.description}</p><p className="mt-2 font-mono text-sm">{product.currency} {product.price}</p>{!!(product.sku??product.metadata?.sku)&&<p className="mt-1 text-xs text-text-muted">SKU: {String(product.sku??product.metadata.sku)}</p>}<p className="mt-1 text-xs text-text-muted">{product.stock_count==null?"Stock unknown":`${product.stock_count} in stock`} · {product.checkout_url_template?"Checkout configured":"Checkout not configured"}</p></div><div className="flex gap-4 text-xs"><button onClick={()=>{setEditing(product.id);setForm({name:product.name,description:product.description,price:String(product.price),currency:product.currency,sku:String(product.sku??product.metadata?.sku??""),stock_count:product.stock_count==null?"":String(product.stock_count),checkout_url_template:product.checkout_url_template??""});}}>Edit price or details</button><button className="text-error" onClick={()=>void remove(product.id)}>Remove</button></div></article>)}</div>
  </div></main>;
}
