"use client";

import {useEffect,useState} from 'react';
import Link from 'next/link';
import {Instagram,Send,Plug} from 'lucide-react';
import {fetchSleyzConnections,type SleyzConnectionStatus} from '@/lib/api/workspace';
import {useMiloOrg} from '@/lib/hooks/useMiloOrg';

export default function ConnectChannelsPage(){
  const org=useMiloOrg();return org?<Connections key={org} org={org}/>:<p className="p-5 text-sm">Sign in to view channel status.</p>;
}
function Connections({org}:{org:string}){
  const [connections,setConnections]=useState<SleyzConnectionStatus[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  useEffect(()=>{let active=true;void fetchSleyzConnections(org).then(result=>{if(active)setConnections(result.connections);}).catch(failure=>{if(active)setError(failure.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[org]);
  return <div className="flex h-full flex-col bg-white font-workspace-sans">
    <header className="border-b border-border bg-white px-6 py-6 pl-14 md:px-10"><h1 className="font-workspace-display text-[24px] font-bold text-text-primary">Channel status</h1></header>
    <main className="flex-1 overflow-y-auto bg-bg-primary px-6 py-8 md:px-10">
      {loading&&<p role="status" className="text-sm text-text-muted">Loading connections...</p>}
      {error&&<p role="alert" className="text-sm text-error">{error}</p>}
      {!loading&&!error&&connections.length===0&&<p className="text-sm text-text-muted">No Sleyz connections configured.</p>}
      <div className="grid max-w-4xl gap-3">{connections.map((connection,index)=>{
        const Icon=connection.platform==='telegram'?Send:connection.platform==='instagram'?Instagram:Plug;
        const status=connection.status??(connection.connected?'connected':connection.configured?'configured':'not configured');
        return <article key={connection.connection_id??`${connection.platform}:${index}`} className="flex items-center gap-4 rounded-lg border border-border bg-bg-elevated p-5">
          <Icon size={18} className="shrink-0 text-text-secondary"/><div className="min-w-0 flex-1"><h2 className="text-[15px] font-medium capitalize">{connection.platform}</h2>{connection.account_id&&<p className="mt-1 break-all text-[13px] text-text-secondary">{connection.account_id}</p>}</div>
          <span className="text-right font-workspace-mono text-[10px] uppercase text-text-muted">{status}</span>
        </article>;
      })}</div>
      <Link href="/agents/sleyz" className="mt-8 inline-flex text-sm underline">Sleyz inbox</Link>
    </main>
  </div>;
}
