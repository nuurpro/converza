import assert from "node:assert/strict";
import test from "node:test";

import {
  FALLBACK_PLATFORMS,
  platformConstraint,
  resourceCommitment,
} from "../lib/marketing-calendar.shared.js";

test("platform warning is deterministic and starts only above two", () => {
  assert.equal(platformConstraint(["instagram_reels", "youtube_shorts"]), null);
  const selected = ["instagram_reels", "youtube_shorts", "tiktok"];
  assert.deepEqual(platformConstraint(selected), platformConstraint(selected));
  assert.deepEqual(platformConstraint(selected)?.recommended, FALLBACK_PLATFORMS);
});

test("resource commitment derives count from hours rather than asking twice", () => {
  assert.deepEqual(resourceCommitment(1, 14), {
    hoursPerWeek: 1,
    targetVideoCount: 2,
    regenerateLighterPlan: true,
  });
  assert.equal(resourceCommitment(5, 14).targetVideoCount, 10);
});
