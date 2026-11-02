# Milo Autonomous Director Implementation Plan

**Goal:** Execute the approved autonomous director specification, preserving script sign-off and final master HITL as the only human gates.

**Architecture:** Versioned scene contracts constrain a durable, fenced DAG. Milo verifies local media evidence before enqueuing successors; Vea renders and assembles through authenticated, idempotent operations. Existing jobs remain compatible behind a default-off feature flag.

**Tech Stack:** FastAPI, Pydantic, PostgreSQL RPCs, existing workspace SSE, Next.js, FFmpeg/FFprobe, faster-whisper, Tesseract.

## Work packages

- [x] Contracts and grounding: strict schemas; preserve approved narration; derive brand constraints; shared text-model decomposition and bounded bulk-edit patches. Test invalid indices, timing, claims, exact strings and narration approval invalidation.
- [x] Durable DAG: run/revision/attempt persistence, transactional events, idempotent intent/receipt handling, leased task claims, bounded retries, safe cache reuse, stale-run fencing and atomic final draft promotion. Test memory and real PostgreSQL adapters.
- [x] Vea execution: scene and assembly APIs, durable receipts, actual media probes, local Whisper/OCR evidence, artifact/provenance hashes, stems and ducking. Test authentication, replay, missing dependencies and actual synthetic media.
- [x] Integration: owner-scoped director/bulk-edit/recovery routes; generate storyboard before sign-off; redirect enabled new builds into director; poll director tasks in the worker without blocking legacy builds.
- [x] Command Center: autonomous progress via durable SSE, edit preview/save, actionable blocked states, final recommendation badge. No scene decision controls.
- [ ] Acceptance: run service and frontend suites, language/coherence/edit evals, local annotated speech alignment and complete scene-to-master media verification. Record exact limitations rather than treating missing dependencies as passes.
- [ ] Delivery: scoped diff review, no unrelated workspace changes or binaries; commit/push feature; rollout/recovery/dependency documentation. Production changes require separate approval.

## Acceptance invariants

No N+1 dispatch before N passes FFprobe, <=150ms alignment, normalized OCR and tenant provenance checks. Initial plus two automated attempts per scene/master; subsequent attempts are new DAG nodes. Narration changes require reapproval; compliant visual-only changes do not. Final master must be inspected and promoted exactly once to AWAITING_HITL, never published.

## Delivery status

Local acceptance gates pass, including real media and independent 150 ms speech calibration. The configured shared inference resource is frozen (HTTP403 ModelArts.81006), so the live quality gate remains open and the delivery stays draft. Production is unchanged.
