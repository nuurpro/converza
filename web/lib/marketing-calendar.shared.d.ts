export const MAX_RECOMMENDED_PLATFORMS: number;
export const FALLBACK_PLATFORMS: string[];
export function platformConstraint(
  selected: string[],
  literacyLevel?: string,
): { blocked: true; recommended: string[]; message: string } | null;
export function resourceCommitment(
  hoursPerWeek: number,
  durationDays?: number,
): { hoursPerWeek: number; targetVideoCount: number; regenerateLighterPlan: boolean };
