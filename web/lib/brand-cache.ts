export const OWNER_USER_STORAGE_KEY = "converza.ownerUserId";

export function setActiveOwnerUserId(ownerUserId: string) {
  if (typeof window === "undefined" || !ownerUserId.trim()) return;
  window.localStorage.setItem(OWNER_USER_STORAGE_KEY, ownerUserId.trim());
  window.dispatchEvent(new Event("converza:owner-user-updated"));
}

function currentOwnerUserId(ownerUserId?: string | null) {
  if (ownerUserId?.trim()) return ownerUserId.trim();
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(OWNER_USER_STORAGE_KEY)?.trim() ?? "";
}

export function brandNameStorageKey(ownerUserId: string) {
  return `converza.brandName.${ownerUserId}`;
}

export function getCachedBrandName(ownerUserId?: string | null) {
  if (typeof window === "undefined") return "";
  const owner = currentOwnerUserId(ownerUserId);
  if (!owner) return "";
  return window.localStorage.getItem(brandNameStorageKey(owner))?.trim() ?? "";
}

export function setCachedBrandName(brandName: string, ownerUserId?: string | null) {
  if (typeof window === "undefined") return;
  const owner = currentOwnerUserId(ownerUserId);
  const normalizedName = brandName.trim();
  if (!owner || !normalizedName) return;

  window.localStorage.setItem(brandNameStorageKey(owner), normalizedName);
  window.dispatchEvent(new Event("converza:brand-name-updated"));
}
