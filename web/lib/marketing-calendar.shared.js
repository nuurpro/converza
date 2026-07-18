export const MAX_RECOMMENDED_PLATFORMS = 2;
export const FALLBACK_PLATFORMS = ["instagram_reels", "youtube_shorts"];

export function platformConstraint(selected, literacyLevel = "new") {
  if (selected.length <= MAX_RECOMMENDED_PLATFORMS) return null;
  const countWord = { 3: "three", 4: "four", 5: "five" }[selected.length] ?? String(selected.length);
  const explanation =
    literacyLevel === "new"
      ? "Starting with two gives us enough repetition to learn what works without splitting your attention."
      : "Two focused channels give the plan enough repetition to produce a useful signal.";
  return {
    blocked: true,
    recommended: [...FALLBACK_PLATFORMS],
    message: `You selected ${countWord} platforms. We recommend Instagram Reels and YouTube Shorts first. ${explanation}`,
  };
}

export function resourceCommitment(hoursPerWeek, durationDays = 14) {
  const weeks = durationDays / 7;
  const videosPerWeek = Math.max(1, Math.min(7, Math.floor(hoursPerWeek)));
  return {
    hoursPerWeek,
    targetVideoCount: Math.max(1, Math.round(videosPerWeek * weeks)),
    regenerateLighterPlan: hoursPerWeek < 3,
  };
}
