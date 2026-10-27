import type {OnboardingPassport} from '@/lib/api/onboarding';

export interface WorkspaceUser {id: string; email?: string;}
const listeners = new Set<() => void>();
let controller = new AbortController();
let generation = 0;
let session: {user: WorkspaceUser | null; passport: OnboardingPassport | null; orgId: string | null; generation: number; signal: AbortSignal} = {
  user: null, passport: null, orgId: null, generation, signal: controller.signal,
};
export function getWorkspaceSession() { return session; }
export function subscribeSession(listener: () => void) { listeners.add(listener); return () => {listeners.delete(listener);}; }
export function resetWorkspaceSession() {
  controller.abort(); controller = new AbortController(); generation++;
  session = {user: null, passport: null, orgId: null, generation, signal: controller.signal};
  listeners.forEach(listener => listener());
}
export function setWorkspaceSession(user: WorkspaceUser, passport: OnboardingPassport | null) {
  if (passport && passport.owner_user_id !== user.id) throw new Error('Workspace owner mismatch');
  if (session.user?.id !== user.id || session.orgId !== (passport?.org_id ?? null)) resetWorkspaceSession();
  session = {user, passport, orgId: passport?.org_id ?? null, generation, signal: controller.signal};
  listeners.forEach(listener => listener());
}
export function getCurrentOrgId(ownerUserId?: string | null) {
  if (!session.user || !session.orgId || (ownerUserId && session.user.id !== ownerUserId)) {
    throw new Error('Sign in and restore your workspace first');
  }
  return session.orgId;
}
