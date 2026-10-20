# Deterministic VEA renderer

VEA turns approved Milo scenes into versioned 1080×1920, 30fps MP4s with local,
rights-cleared clips, approved overlays, branded word captions and optional music.
It never generates scripts, fetches unrelated stock or publishes to social media.
The existing authenticated API, durable SQLite receipts and single-process lease
recovery remain in use. Keep `MPT_APPROVED_ONLY=1` and persistent `storage/`.

## Provision and enable

Build `Dockerfile.milo`. Its focused requirements include faster-whisper and Piper,
and it installs FFmpeg/libass and DejaVu fonts. Preset JSON is copied into the
image. Assets and model weights are server-managed volumes, outside Git:

```sh
docker run --name converza-vea -p 127.0.0.1:8080:8080 \
  --env-file /secure/vea.env \
  -v /srv/vea/storage:/MoneyPrinterTurbo/storage \
  -v /srv/vea/assets:/assets:ro \
  -v /srv/vea/models:/models:ro converza-vea-milo
```

Use these server-only environment settings:

```ini
MPT_API_KEY=<shared control secret>
VEA_ENABLED=1
VEA_ASSET_ROOT=/assets
ELEVENLABS_API_KEY=<provider key>
VEA_ELEVENLABS_VOICES={"en":"<voice-id>","ru":"<voice-id>","uz":"<voice-id>"}
VEA_WHISPER_MODEL=/models/faster-whisper-small
VEA_WHISPER_DEVICE=cpu
VEA_WHISPER_COMPUTE_TYPE=int8
VEA_PIPER_VOICES={"en":{"model":"/models/en_US-voice.onnx"}}
```

`VEA_ENABLED` defaults to `0`; capability `deterministic_presets_v1` is advertised
only when enabled. Set Converza's corresponding VEA feature flag after provisioning
and smoke tests. Voice maps use language codes `en`, `ru`, `uz`. ElevenLabs uses
`eleven_v3`; legacy Edge voice names are never forwarded. Piper is attempted only
for an installed ONNX model whose companion JSON declares the requested language.
Missing language support produces an actionable failure; another language is
never substituted. Verify voice-model licensing before provisioning. Configure
`VEA_PIPER_EXE` for a nonstandard Piper executable; the installed CLI must support
`--model`, `--config` and `--output_file`.

The Whisper model must already be downloaded: the renderer uses
`local_files_only=True` and never downloads during a job. No paid speech calls or
model downloads occur in ordinary tests. Full speech quality must be evaluated
against local annotated recordings before production rollout.

`VEA_FFMPEG`, `VEA_FFPROBE`, and `VEA_X264_PRESET` optionally override executable
paths and the encoder speed preset. `VEA_PUBLIC_ENDPOINT` optionally supplies an
absolute media origin; otherwise Converza's adapter resolves relative URLs using
`MONEYPRINTERTURBO_PUBLIC_BASE_URL`.

## Seed the asset vault

Create `/assets/catalog.json` with organization-scoped records. Paths must be
relative to the asset root. Checksums, media duration, dimensions, organization,
product association, advertising rights and permitted uses are rechecked before
each render. An empty `product_ids` list means a brand-generic asset; a null
campaign product cannot select another product's footage.

```json
{
  "schema_version": 1,
  "assets": [{
    "id": "steel-hinge-closeup-01",
    "org_id": "organization-id",
    "path": "organization-id/hinge.mp4",
    "sha256": "<64 lowercase hex characters from the file>",
    "kind": "video",
    "duration_sec": 8.0,
    "width": 1080,
    "height": 1920,
    "tags": {"en": ["steel hinge", "product closeup"], "ru": ["стальная петля"], "uz": ["po‘lat ilgak"]},
    "product_ids": ["product-id"],
    "rights_confirmed": true,
    "permitted_uses": ["advertising"]
  }]
}
```

Record the exact `ffprobe` format duration, with tolerance 0.1 seconds. Clips must
be long enough for selected cuts; no matching clip produces `missing_assets` with
seeding guidance. Matching uses BM25 on the requested language's tags plus `und`
tags, stable asset-ID tie breaking and no automatic remote stock fallback.

Music records use `kind: "music"`, audio-file paths and durations, the same tenant
and rights fields, and no dimensions. The first eligible music asset by ID is
selected, normalized, mixed at −18dB under narration and persisted by ID/checksum
in the manifest. Swaps preserve that choice. Omit music records for narration only.

Catalog APIs `/api/v1/vea/presets` and `/api/v1/vea/assets?org_id=...&product_id=...&language=en`
require the same bearer secret as all renderer controls and return the existing
`{status,message,data:{presets|assets}}` response envelope. Asset metadata excludes
filesystem paths. Converza applies authenticated organization access before calling.

## Recipes, bindings and artifacts

`video_presets/preset_high_velocity_d2c.json` and
`video_presets/preset_editorial_showcase.json` define 2.0–2.5s and 2.5–3.5s cuts,
safe areas, typography, restrained grading, seeded grain and discrete 12fps graphic
states over 30fps footage. Cuts prefer word endings and retain complete narration.
Approved overlays retain wording and line breaks. Dark brand colors use a light
caption box with black inactive words; light brand colors use a dark box.

`POST /api/v1/videos` retains its approved scenes and immutable `milo_binding`.
For VEA it adds `vea_config` containing schema version 1, preset ID, pinned preset
version and SHA, brand revision and hex colors, nullable product ID, variant ID and
revision, clip overrides, and nullable reuse manifest. All defaults participate in
canonical hashing: sorted keys, UTF-8, unescaped Unicode, separators `,` and `:`.
The matching `milo_binding.vea_config_sha256` is mandatory. The binding retains
job, organization, campaign, approved script revision and provider attempt.
Unsupported or changed pins fail; clip swaps require the original recipe hash.

Each completed task stores `vea_artifact` and a sibling `composition_manifest`.
The artifact carries the versioned media contract; the manifest stores segment
IDs, source intervals, chosen clips and alternatives, music, word timing, approved
overlays, narration cache keys and input hashes. The manifest has no asset paths.
Only `/tasks/{UUID}/final-N.mp4` and `final-N.jpg` are public; narration, captions,
composition JSON and sources remain private. Approval and export happen in
Converza; any clip replacement creates a fresh revision requiring renewed approval.

Scene narration is cached per organization with voice/model/settings/text identity
and an audio checksum. Alignment is cached by audio checksum, approved text,
language and Whisper model. Swaps reuse original narration even if a previously
unavailable primary provider recovers. Normalized per-scene PCM is padded/trimmed
to its measured millisecond interval before concatenation, preventing MP3 delay
or padding from shifting subsequent scene captions.

Normalized fuzzy alignment requires a sequence score and acoustic-token coverage
of at least 90%. Substitution costs use normalized character edit distance; token
insertions/deletions cost one. Genuine syllable fragments can jointly anchor a
word. At most 10% of approved tokens, with at most two consecutive missing tokens,
receive linear neighboring-boundary interpolation; measured scene edges anchor
leading/trailing gaps. Captions retain approved tokens and telemetry marks every
interpolated index. Larger drops, invalid overlaps and out-of-scene timestamps fail.

## Validate and restart

```sh
python -m unittest test.services.test_vea_pipeline test.services.test_vea_contract test.services.test_vea_evaluation
MPT_APPROVED_ONLY=1 MPT_RUN_API_TESTS=1 python -m unittest test.services.test_vea_api test.services.test_milo_api
python scripts/verify_vea_media.py --output /tmp/vea-media-proof
python scripts/eval_vea.py
python scripts/eval_vea.py --corpus /srv/evals/annotations.json --cache /tmp/vea-alignment-eval
python scripts/evaluate_vea_alignment.py /srv/evals/annotations.json --cache /tmp/vea-alignment-eval
```

The media proof uses synthetic footage/audio and English/Russian/Uzbek text to
verify codecs, caption layout and durations; it does **not** validate speech
recognition quality. The evaluator accepts annotated local speech records with
`audio_path`, `language`, `approved_text`, and `reference_words` entries containing
`word`, `start_ms`, `end_ms`. It includes interpolated words and fails unless at
least 95% of start/end boundaries fall within 200ms for each recording. Include
English, Russian and Uzbek recordings and inspect sampled frames before rollout.
The separate `eval_vea.py` suite defaults to synthetic multilingual annotated
timing/interpolation and deterministic matching/isolation fixtures. It explicitly
labels this as synthetic evidence. Its `--corpus` mode requires all three languages
and a provisioned model; missing corpus/configuration exits 2, failing quality gates
exit 1, and passing evaluations exit 0.

Deploy core migration 009 before enabling the worker. Rebuild and restart the
renderer with persistent storage and read-only asset/model volumes, verify bearer
authentication and the capability, then restart the Converza worker. Renderer
startup marks interrupted receipts `renderer_restarted`; known completed receipts
remain pollable. Retry only definitive failures; uncertain submissions retain the
existing reconciliation gate. Do not delete receipts or persistent caches during
restart. Monitor completion rate, approval-to-preview time, missing-assets errors,
alignment scores/coverage/interpolation and fallback frequency from artifact
`render_telemetry`; failures carry safe `error_code`, `error_message`, and telemetry.
