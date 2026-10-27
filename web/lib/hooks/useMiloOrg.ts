"use client";
import {useSyncExternalStore} from 'react';
import {getWorkspaceSession,subscribeSession} from '@/lib/org';
/** Changing owners unmounts keyed campaign/settings state and discards old requests. */
export function useMiloOrg(){
 return useSyncExternalStore(subscribeSession,()=>getWorkspaceSession().orgId,()=>null);
}
