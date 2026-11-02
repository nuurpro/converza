# Milo director verification — 2026-11-02

The scoped worktree contains the autonomous director implementation, with
initial narration sign-off and final master HITL as the only human gates.
Production remains unchanged. The live text-model gate is open: the configured
Huawei resource returned HTTP 403 `ModelArts.81006`, `The resource is frozen.`
No alternate inference provider or model was used.

## Evidence by requirement

| Requirement | Authoritative evidence |
| --- | --- |
| Exact structured scenes and approved brand constraints | Strict Pydantic contracts; decomposition, exact Unicode narration/overlay, field/index/timing validation and auto-selected product SKU regression tests. |
| Selective text edits | Minimal validated patches, current confirmed facts, stale-preview rejection, unresolved claims, cache candidates and narration invalidation tests. |
| Sequential dispatch and two retries | Memory/SQL state tests, independent provider campaign barrier tests, and actual worker dispatch sequence scene 1 → scene 2 → master. |
| Durable approval and recovery | PostgreSQL concurrency, lease fencing, unknown-submission reconciliation, atomic initial sign-off, delayed narration revert and exactly-once final promotion tests. |
| No intermediate human gate | Owner API tests, autonomous worker proof and UI fixture tests; no scene approval endpoint or state exists. |
| 150 ms local scene checks | Boundary tests at 150/151 ms; actual encoded audio, Whisper observations and OCR; independent recorded-speech calibration described below. |
| Provenance and cache validity | Tenant/product/SKU tests, immutable artifact checksums, asset/config cache snapshots bound before and after execution, stale context rejection. |
| Master inspection | Ordering, original overlay formatting, pacing/duration, clipping, exact requested background asset, actual stem levels and semantic coherence rejection tests. |
| Central approval and SSE | Transactional PostgreSQL events/replay, final approval-only guard, stale master removal from feed, typed director artifact and UI stream/reconnect tests. |

## Recorded runs

- Scoped full backend suite: 504 tests total — 480 passed and 24 optional integration tests skipped,
  with a fresh disposable PostgreSQL database enabled. This includes the atomic
  narration sign-off and delayed-job regression gates.
- Scoped frontend: 101 tests and type checking passed. Production Next build
  passed after installing dependencies locally in the worktree; a temporary
  cross-drive junction was unsuitable for Next's module resolution and removed.
- Provider: 39 focused provider/legacy tests passed, including actual encoded
  English, Russian and Uzbek OCR and concurrent cross-revision submission refusal.
- Actual clean-source worker proof passed: two scenes, each at attempt 1, then
  one crossfade/music master and exactly one `AWAITING_HITL` draft; 13 persisted
  progress events. Duration 5.266667 s against a 5.25 s target; zero clipped
  samples; minimum measured narration/background separation 39.6319 dB.
  The coherence evaluator was explicitly mocked in this media proof.
- The scoped renderer Docker image built and passed authenticated route/OCR-language
  smoke checks. Compose validated without real environment-file resolution.
- Director fixture text eval passed. Live director text eval failed availability
  because the configured shared Huawei resource is frozen; no live quality pass
  is claimed.
- Browser fixtures verified initial single sign-off, autonomous progression,
  final master video/report/badge and 390 px mobile width without overflow. The
  production-demo fixture and canonical master-card fixture are distinct; see
  `web/tests/director-browser-qa.md`. They do not replace the PostgreSQL/API proof.

Local raw artifacts remain ignored under `.gstack/director-clean-proof-final/`.
The actual final worker master checksum is
`d246f835ae02a58cd8afe231615dcd96e4f19c528b036faa48c98daff29fe276`.
No media, model weights, fonts, local credentials, or third-party binaries belong
in the source commit.

## Independent speech calibration

Two actual generated-English recordings used independent Microsoft speech
engine word/phoneme timing annotations, not Whisper-derived reference labels.
The original tiny model run failed: 14/16 boundaries within 150 ms, maximum
235 ms. Physical PCM silence partitioning, with restored absolute offsets,
corrected long-pause anchoring without changing approved text or reference data.
The unchanged tiny-model reference then passed 16/16 boundaries, maximum 85 ms.

This is limited calibration, not a claim of general human or multilingual speech
accuracy. The base model still failed the same unchanged threshold, and no
default-small-model pass is claimed. Keep those failures and calibrate the exact
deployed model/voice/languages on representative independent recordings. Runtime
verification always retains the 150 ms threshold and fails missing/low-confidence
evidence. Do not widen tolerances or select a model silently to obtain a pass.

## Reproduce

```powershell
$env:PYTHONPATH='core'
$env:CONVERZA_WORKFLOW_TEST_DSN='host=127.0.0.1 port=55459 user=postgres dbname=test_converza_director_final_20261102'
python -m unittest discover -s core/tests -q
python -m services.milo.director.evals
python -m services.milo.director.evals --live
npm test --prefix web
npm run typecheck --prefix web
npm run build --prefix web
docker build -f Vea/services/MoneyPrinterTurbo/Dockerfile.milo -t converza/milo-director-validation:local Vea/services/MoneyPrinterTurbo
```

The database DSN must name an explicitly disposable test database. Provider media
and calibration commands, fixture shapes and dependency setup are documented in
`Vea/services/MoneyPrinterTurbo/README.director.md`. Production migration/restarts
require the separately approved procedure in `milo-director-rollout.md`.
