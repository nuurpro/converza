# VEA verification, 2026-10-20

Implementation is on `codex/vea-production`, based on the existing Milo branch.
The change preserves unrelated working-tree deletions and untracked files.

## Automated gates

- Core: 344 discovered tests, no failures, eight optional unrelated tests skipped.
  The run used an isolated local PostgreSQL database named
  `test_converza_vea_release`, never production Supabase. VEA SQL tests exercised
  concurrent/idempotent creation, artifact completion, clip-swap approval guards,
  stale brand evidence, uncertain submission fences, legacy default compatibility,
  and service-role-only RPC access.
- Renderer: 60 focused tests passed under Python 3.11, including the real FFmpeg
  vertical-video/audio/thumbnail lane and authenticated ASGI task/preview tests.
  The suite includes three-scene MP3 duration checks, English/Russian/Uzbek
  caption coverage, recipe pins, fuzzy substitutions and syllable fragments,
  exactly-90% acceptance, bounded interpolation, rights/product isolation, cache
  reuse, missing local models/executables, and durable receipt recovery.
- Web: 49 tests passed; TypeScript checking and the production Next build passed.
  Tests cover video-only approval cards in dashboard and squad, revision-safe
  decisions, organization switching, delayed responses, superseded exports, and
  replacement filtering by media kind and segment duration.
- VEA core fixture evaluation: 12 cases, 100% source safety and determinism.
  Existing Milo and workflow fixture evaluations also passed.
- Renderer fixture evaluation: three multilingual interpolation/timing cases
  and deterministic catalog isolation/ranking passed. All synthetic reference
  boundaries were within 200ms; this is explicitly synthetic timing evidence.
- A direct core-payload-to-renderer-schema check passed for both recipe IDs,
  including canonical configuration and immutable receipt hashes.
- Both normal and VEA-override Docker Compose configurations validate.

## Browser and media inspection

A loopback QA harness used the actual Next UI and in-memory core Milo, VEA, and
workflow routers with synthetic local media and injected test authentication.
Browser automation used gstack `/browse`. It verified:

- A playable 1080x1920 preview and three-second duration.
- Approve & Export records `APPROVED` and enables MP4 download.
- Swapping a clip creates revision 2 and a new `AWAITING_HITL` draft, invalidating
  the previous approval.
- Editorial creation coexists with the automatic default variant.
- Video review cards replace generic text editing in dashboard and squad.
- The studio and swap controls fit a 375px viewport without horizontal overflow.

Retained screenshots are in the local temporary `vea-browser-qa` directory;
representative real-FFmpeg frames and MP4s are in `.gstack/vea-media/`. Dark and
bright brand caption backgrounds and Cyrillic/Uzbek text were visually inspected.
Generated media, screenshots, models, credentials and QA harnesses are excluded
from source commits. `scripts/verify_vea_media.py` regenerates media evidence.

## Deployment gates

Production migration, asset seeding, voice/model provisioning, and service
restarts were not performed. Both feature flags remain disabled by default.
Follow `vea-rollout.md` and the renderer's `README.vea.md` to provision them.

The annotated recorded-speech corpus and deployed voice-quality checks remain
unrun because no recorded multilingual corpus, local Whisper model, or deployment
voice configuration was supplied. The delivered corpus evaluator enforces 95%
of word boundaries within 200ms, including interpolated tokens, and fails on
missing inputs. Synthetic alignment results are not a claim of real ASR accuracy.

Docker Desktop's Linux daemon is unavailable, so image build and container
startup remain unverified. Native API and FFmpeg validation are separate evidence.
