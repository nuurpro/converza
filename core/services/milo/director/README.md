# Autonomous Milo director

Milo now measures whether each scene can advance, rather than treating a complete
render as one opaque build. The measurable invariants are zero successor renders
before predecessor verification, at most two automated retries, and exactly one
human-review draft per inspected master.

The only human gates are initial script/narration sign-off (including narration
edits) and final master approval. There is no scene approval endpoint or state.

## Workflow and boundaries

`DIRECTING_SCENE → AWAITING_SCENE_VERIFICATION → SCENE_VERIFIED` repeats in order,
then Vea receives the assembly manifest and Milo inspects the master. Attempts
append DAG nodes; storyboard edits create successor revisions and fence old
workers and masters transactionally. Existing campaigns without a director
storyboard keep their legacy build path. `MILO_DIRECTOR_ENABLED` defaults off.

The strict public contracts are in `contracts.py`: `ScenePromptPayload`,
`SceneVerificationResult`, and `MasterAssemblyManifest`. Inference can propose
creative directions or scene patches; it cannot assign approval, source
constraints, verified tokens, or workflow state. All text inference uses the
existing shared `services.llm` boundary without provider/model fallback.

Scene verification evaluates actual FFprobe decoding/bounds, independent Whisper
observations within 150 ms of rendered word cues, normalized OCR of encoded
frames, and tenant/SKU provenance. Missing measurements or dependencies fail.
Verified records retain measured durations, transcripts, OCR observations, source
IDs and artifact hashes. Technical checks do not prove perceptual visual quality.

Master inspection binds ordered tokens, scene pacing, exact approved overlays and
formatting, total duration (250 ms), actual music identity, per-speech-window
ducking (at least 12 dB), clipping and audible narration to the approved snapshot.
Shared-model coherence review runs only after deterministic checks pass. Passing
creates one `drafts.director_artifact` in `AWAITING_HITL`; approval/export are
allowed, publishing and text editing are refused.

## Durable execution and caching

PostgreSQL CAS commits, leases, fencing and outbox intents cover crashes and
concurrent decisions. Initial script approval binds narration in the same
transaction as its build intent; workers cannot grant approval. A changed
storyboard immediately makes old paid work unable to advance and old masters
unapprovable, even before successor creation.

Vea stores immutable receipts before acknowledgment. Lost responses are looked
up by the original key. A per-tenant/campaign execution barrier prevents overlap
across revisions. Unknown submissions are never blindly repeated. Transient
failures back off 30–300 seconds; recovery preserves the receipt and attempt.
Three failed attempts raise a visible alert; editing a corrected storyboard is
the route to another production revision.

Reuse requires the complete scene specification plus matching language, product,
brand constraints, actual asset catalog, renderer/model/font/config context.
Requests bind that expected context, and Vea checks it before and after rendering.
Unavailable cache context disables reuse; it never makes an unverified scene pass.

## Owner API

All paths are under `/api/milo/{org_id}/campaigns/{campaign_id}/director`:

- `GET /`: current storyboard, sanitized run progress, error and inspection.
- `POST /edits/preview`: `{directive, expected_revision}` produces minimal changed
  scenes, reuse candidates, unresolved requests and a narration-change indicator.
- `POST /edits`: `{preview_id, expected_revision}` saves an approved-evidence edit.
  Visual-only edits advance automatically; narration edits require sign-off.
- `POST /storyboard/approve`: `{expected_revision}` explicitly signs changed
  narration. The initial campaign uses its existing script approval action.
- `POST /recover`: `{run_id, expected_revision}` expedites a deferred receipt or
  dependency check without resetting exhausted attempts or creating paid work.

Mutations except preview require `Idempotency-Key`; stale revisions return 409.
Persisted `agent_run_step` events carry run/revision/index/count/attempt/state and
readable messages through the existing authenticated workspace SSE stream.
Reconnect snapshots and replay cursors remain authoritative.

See `docs/milo-director-rollout.md` and `docs/milo-director-verification.md` for
operator commands and the precise evidence/limitations.
