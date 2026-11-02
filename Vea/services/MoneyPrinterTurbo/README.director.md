# Local director provider

The `/api/v1/director` API uses `Authorization: Bearer $MPT_API_KEY` even when
legacy API authentication is disabled. Keep `MILO_DIRECTOR_ENABLED` disabled
until the core migration and operator dependency checks are complete.

Endpoints:

- `POST /scenes` accepts the approved scene and immutable org/run/campaign,
  storyboard revision, attempt, canonical specification SHA256, idempotency key,
  language, optional product, and targeted correction notes.
- `POST /masters` accepts ordered verified scene references and an approved
  assembly manifest. Hard cuts and 150 ms crossfades are supported. Optional
  `background_asset_id` selects a rights-cleared tenant music asset.
- `GET /tasks/{task_id}?org_id=...` returns durable status and measured evidence.
- `GET /tasks?org_id=...&idempotency_key=...` authoritatively reconciles a lost
  submission response. Replaying the original POST returns the same task.
- `GET /context?org_id=...&product_id=...&language=en` hashes current tenant
  assets, narration, renderer code/binaries, fonts, local model and OCR data.
- `GET /tasks/{task_id}/artifacts/{filename}?org_id=...` authenticates immutable
  MP4, canonical narration WAV, or evidence JSON downloads. Only final master
  MP4/JPG previews enter the existing public `/tasks/{UUID}/final-1.*` surface.

Receipts commit with SQLite `synchronous=FULL` before acknowledgment. Each
idempotency key and each immutable attempt slot has one receipt. Claims use an
exclusive transaction and a random fence; terminal results cannot be replaced.
Queued submissions are dispatched when polled after a crash. Expired running
leases fail visibly rather than silently rerendering uncertain work. Core
creates new retry attempts and decides all verification/progression.

## Provision before jobs

Set `VEA_ASSET_ROOT` to the existing read-only catalog. Configure explicit
`VEA_WHISPER_MODEL` as a local model directory, `VEA_TESSERACT` as the installed
OCR executable, and provision `eng`, `rus`, and `uzb` language packs. FFmpeg,
FFprobe, faster-whisper, and local fonts must be available. Jobs never download
models or skip missing inspections.

Narration uses either the configured local Piper voice or
`VEA_DIRECTOR_NARRATION_ROOT/catalog.json`:

```json
{"recordings":[{"org_id":"tenant","language":"en","text_sha256":"<canonical approved text hash>","audio_sha256":"<file hash>","path":"approved.wav"}]}
```

The recording path must remain inside that root. Wording, tenant, language and
audio checksum must match exactly. Remote speech fallback is disabled. Audio
that exceeds scene timing by more than 150 ms fails; otherwise its full waveform
is retained, with silence padding when needed.

Whisper operates on actual PCM utterances separated by at least 300 ms of
measured silence, retaining 20 ms shoulders and restoring absolute sample
offsets. This prevents long inter-sentence silence from shifting word anchors.
Approved words are the only caption source. Independent ASR of encoded audio
and OCR of actual encoded frames are returned to Milo. Overlay OCR samples the
specified screen region separately from narration captions. Technical evidence
does not establish perceptual brand/negative-visual compliance.

Music is attenuated during measured speech windows and recovers during pauses.
Actual narration/background PCM stems, per-word RMS levels, final clipping
counts, final-master OCR and ordered source hashes accompany the master.

For persistent storage set `VEA_DIRECTOR_DB` and `VEA_DIRECTOR_ROOT` to mounted
volumes. Preserve both with the normal provider storage/tasks volume. The core
recovery endpoint should reconcile receipts before making new attempts.

## Reproducible local validation

Run `python -m unittest test.services.test_director_provider
test.services.test_vea_pipeline test.services.test_vea_evaluation`. Setting
`VEA_TESSERACT` enables actual EN/RU/UZ encoded-frame OCR tests.

`scripts/validate_director_local.py` takes an approved speech fixture JSON and
explicit model/tool paths. `--crossfade --music --durable-worker` exercises
actual HTTP scene rendering, independent media inspections, sequential
DirectorWorker progression, master assembly, and exactly one final HITL draft.
Its core repository is in-memory; real PostgreSQL concurrency is tested by the
core suite. The coherence model in this local utility is an explicit test
double, so it does not establish live text-model quality.

`scripts/record_alignment_reference.ps1 -OutputDirectory <folder>` records
offline Windows speech with independent engine word/phoneme callbacks, using an
explicit 16 kHz clock and excluding silence phonemes. Run
`scripts/evaluate_vea_alignment.py <annotations.json> --cache <folder>
--tolerance-ms 150` against that actual waveform. This evaluates acoustic
recognition against independent timing, rather than comparing fabricated
timestamps. Generated English speech remains a limited calibration fixture;
human and multilingual annotated recordings are still needed for production
quality evaluation. Keep failed calibration reports and do not widen timing
tolerances to obtain a pass.
