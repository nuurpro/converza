# Autonomous director frontend validation

The Milo campaign workspace shows the server's persisted director snapshot. Scene rendering, verification and retries advance automatically. No scene approval control is present. Final master approval stays in the Central Approval Feed.

Bulk edits first show their changed and reusable scene indices, exact proposed narration, visuals and caption formatting. Unresolved instructions and stale preview revisions disable apply. Initial sign-off uses the existing script approval. Subsequent narration changes expose the revised exact narration and require the dedicated narration sign-off only after the campaign script was approved; visual-only changes resume without another approval.

All cards share one authenticated workspace SSE subscription. Persisted `agent_run_step` events and reconnect snapshots refetch authoritative production state. A ten-second snapshot poll also reconciles state while the stream is disconnected. Organization changes remount the campaign workspace, and unmounted requests cannot write into the new view. Accepted edit operations keep their idempotency key across uncertain failures.

An inspected master uses the additive `director_artifact` draft field. It shows “Milo recommends approval · automated checks passed” only when its artifact has both `director_run_id` and `inspection.passed === true`. The inspection report remains visible alongside the final video review. Superseded masters cannot approve or download. These checks do not claim to establish perceptual visual quality.

The Brand Passport's Milo campaign identity editor exposes visual constraints separately from prohibited claim wording. Each nonblank line is saved to `negative_visual_constraints` and enters scene prompts. Final review still owns perceptual brand judgment.

Run from `web/`:

```powershell
npm run typecheck
npm test
npm run build
```

`lib/data/director.test.mjs` covers production states, retry text, missing dependencies, narration sign-off, revision guards, unresolved edits, request ownership/idempotency, SSE replay refresh and unmount safety. `lib/data/veaCard.test.mjs` covers inspected master recommendations in the final review card. Existing workspace stream tests cover authentication changes and replay cursors.

For live QA, use gstack `/browse` with an authenticated local workspace: generate and approve a script, observe sequential scenes, preview/apply visual edits, preview/apply narration edits and approve the exact new narration, then inspect and decide the final master in the feed. Test missing local inspection dependencies and exhausted retries with backend fixtures. The production build requires access to the existing Google Fonts imports in the application's layouts.

Restart the frontend with `npm run dev` after local source changes, or rebuild with `npm run build` and restart `npm start` for a production-mode local instance. This change does not authorize deployment.
