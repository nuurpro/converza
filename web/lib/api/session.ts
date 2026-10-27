import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import {getWorkspaceSession, setWorkspaceSession} from '@/lib/org';
import type {OnboardingPassport} from '@/lib/api/onboarding';

function assertActive(signal: AbortSignal) {
  if (signal.aborted) throw new DOMException('Workspace session changed', 'AbortError');
}

export async function getSupabaseAccessToken() {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) return null;
  const session = (await supabase.auth.getSession()).data.session;
  return session?.access_token ?? null;
}

export async function authHeaders(init?: HeadersInit) {
  const headers = new Headers(init);
  const token = await getSupabaseAccessToken();
  if (!token) throw new Error('Sign in required');
  headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

let restoration: {generation: number; promise: Promise<ReturnType<typeof getWorkspaceSession>>} | null = null;

export function restoreWorkspaceSession() {
  const scope = getWorkspaceSession();
  if (restoration?.generation === scope.generation) return restoration.promise;
  const promise = restoreSession(scope).finally(() => {
    if (restoration?.promise === promise) restoration = null;
  });
  restoration = {generation: scope.generation, promise};
  return promise;
}

async function restoreSession(scope: ReturnType<typeof getWorkspaceSession>) {
  const headers = await authHeaders();
  assertActive(scope.signal);
  const response = await fetch('/api/session', {headers, signal: scope.signal, cache:'no-store', redirect:'error'});
  const payload = await response.json();
  assertActive(scope.signal);
  if (!response.ok) throw new Error(payload?.detail ?? 'Could not restore workspace');
  setWorkspaceSession(payload.user, payload.passport as OnboardingPassport | null);
  return getWorkspaceSession();
}

const operations = new Map<string, string>();
let operationGeneration = -1;
/** A retry of the same mutation retains its key until a confirmed success. */
export async function authenticatedFetch(url: string, init: RequestInit = {}) {
  if (!url.startsWith('/api/backend/api/') || url.includes('\\')) throw new Error('Invalid API target');
  const scope = getWorkspaceSession();
  if (!scope.user) throw new Error('Sign in required');
  const session = (await getSupabaseBrowserClient()?.auth.getSession())?.data.session;
  assertActive(scope.signal);
  if (!session?.access_token || session.user.id !== scope.user.id) throw new Error('Workspace session changed');
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${session.access_token}`);
  const method = init.method ?? 'GET';
  const mutation = !['GET','HEAD'].includes(method);
  const signature = JSON.stringify([scope.user.id, scope.orgId, method, url, init.body]);
  if (operationGeneration !== scope.generation) {operations.clear(); operationGeneration = scope.generation;}
  if (mutation && !headers.has('Idempotency-Key')) {
    if (!operations.has(signature)) operations.set(signature, crypto.randomUUID());
    headers.set('Idempotency-Key', operations.get(signature)!);
  }
  const signal = init.signal ? AbortSignal.any([scope.signal, init.signal]) : scope.signal;
  const response = await fetch(url, {...init, headers, signal, cache:'no-store', redirect:'error'});
  assertActive(signal);
  // Check again after body decoding, including delayed responses from a prior owner.
  for (const name of ['json','text','blob'] as const) {
    const read = response[name]?.bind(response);
    if (read) Object.defineProperty(response, name, {value: async () => {
      const result = await read();
      assertActive(signal);
      if (response.ok && mutation && operations.get(signature) === headers.get('Idempotency-Key')) operations.delete(signature);
      return result;
    }});
  }
  return response;
}
