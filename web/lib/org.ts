export const ORG_ID_STORAGE_KEY = "converza.orgId";
export const FALLBACK_ORG_ID = "00000000-0000-0000-0000-000000000001";
const OWNER_USER_STORAGE_KEY = "converza.ownerUserId";

function storageKeyFor(ownerUserId?: string | null) {
  const keyOwner = ownerUserId || window.localStorage.getItem(OWNER_USER_STORAGE_KEY) || "anonymous";
  return `${ORG_ID_STORAGE_KEY}.${keyOwner}`;
}

export function setCurrentOrgId(orgId: string, ownerUserId?: string | null) {
  if (typeof window === "undefined" || !orgId) return;
  window.localStorage.setItem(storageKeyFor(ownerUserId), orgId);
}

export function getCurrentOrgId(ownerUserId?: string | null) {
  if (typeof window === "undefined") return FALLBACK_ORG_ID;

  const storageKey = storageKeyFor(ownerUserId);
  const existing = window.localStorage.getItem(storageKey);
  if (existing) return existing;

  const next =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : FALLBACK_ORG_ID;
  window.localStorage.setItem(storageKey, next);
  return next;
}
