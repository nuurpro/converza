"use client";
import {useEffect,useState} from 'react';
import {getCurrentOrgId,ORG_ID_STORAGE_KEY} from '@/lib/org';
import {getSupabaseBrowserClient} from '@/lib/supabase/client';
/** Changing owners unmounts keyed campaign/settings state and discards old requests. */
export function useMiloOrg(){
 const [org,setOrg]=useState<string|null>(null);
 useEffect(()=>{
  setOrg(getCurrentOrgId());
  const listener=getSupabaseBrowserClient()?.auth.onAuthStateChange((event,session)=>{
   if(event==='SIGNED_OUT')setOrg(null);
   else if(event==='SIGNED_IN')setOrg(getCurrentOrgId(session?.user.id));
  });
  const storage=(event:StorageEvent)=>{if(event.key?.startsWith(ORG_ID_STORAGE_KEY))setOrg(getCurrentOrgId());};
  window.addEventListener('storage',storage);
  return()=>{listener?.data.subscription.unsubscribe();window.removeEventListener('storage',storage);};
 },[]);
 return org;
}
