# Vea renderer for approved Milo campaigns

This API deployment renders supplied narration and ordered stock-footage search
cues without generating new narration or campaign text. Approved on-screen text
uses a JSON timeline aligned to narration subtitles, preserving line breaks and
blank lines. Bound approved jobs bypass Upload-Post even when legacy automatic
upload settings are enabled. Rendered videos return to Converza's human review.

## Build and run

Run from this directory:

```sh
docker build -f Dockerfile.milo -t converza-vea-milo .
docker run --name converza-vea-milo -p 127.0.0.1:8080:8080 \
  --env-file /path/to/server-only.env \
  -v "$PWD/storage:/MoneyPrinterTurbo/storage" converza-vea-milo
```

Set `PEXELS_API_KEY` and a strong shared `MPT_API_KEY` in that server-only
environment file. Converza's Milo worker uses the same `MPT_API_KEY` to send
`Authorization: Bearer ...` on every renderer control request. Missing provider
keys reject control requests with503; missing worker keys block requests locally.
Never expose this key to the browser. The focused image sets
`MPT_APPROVED_ONLY=1`; it rejects unapproved scripts, disables text-generation
endpoints/provider calls, and disables automatic publishing. No config bind
mount is needed: defaults are read from the checked-in `config.example.toml`.
An optional real `config.toml` can still configure legacy provider behavior.
Configure Converza's `MONEYPRINTERTURBO_BASE_URL` for this private API. An API
capability check must report approved scenes, immutable job bindings, and disabled
automatic publishing. API creation, lookup, listing and deletion require that
bearer key. Public previews expose only `/tasks/{UUID}/final-N.mp4`, keeping scripts
and other task files private. The Docker example binds its host port to loopback.
When Converza runs in Compose, its worker uses
`MONEYPRINTERTURBO_BASE_URL=http://vea-renderer:8080`; set
`MONEYPRINTERTURBO_PUBLIC_BASE_URL` to the browser-accessible video origin
(locally `http://127.0.0.1:8080`). External storage URLs remain unchanged.

The image installs FFmpeg and Debian's licensed `fonts-dejavu-core` package,
then copies `DejaVuSans.ttf` and its license into the runtime resource directory.
No local font files, music, public UI files, model weights, or generated videos
are copied into the image. For a native install, install `requirements.milo.txt`,
set `MPT_FONT_PATH` to an installed DejaVuSans.ttf, run
`python scripts/prepare_resources.py`, and then `python main.py`.
For native approved-only operation also set `MPT_APPROVED_ONLY=1` and
`PEXELS_API_KEY` plus `MPT_API_KEY` in the server process environment. Edge TTS uses its existing
network service and needs no extra API key. Stock footage uses Pexels.

## Validation

```sh
python -m unittest discover -s test/services -p 'test_approved_scene*.py'
python -m unittest discover -s test/services -p test_milo_runtime.py
python -m unittest discover -s test/services -p test_milo_durable_state.py
MPT_RUN_API_TESTS=1 python -m unittest discover -s test/services -p test_milo_api.py
MPT_RUN_MEDIA_TESTS=1 python -m unittest discover -s test/services -p test_approved_scene_render.py
```

The media test uses synthetic local assets, the real MoviePy/FFmpeg composition,
and English/Russian/Uzbek overlays. It makes no TTS, LLM, stock-search, or
publishing calls. To run it after a native installation, prepare resources first.

## Restart and explicit retry

Approved-only task receipts and immutable bindings persist in
`storage/renderer-state.sqlite3`, with atomic SQLite transactions and synchronous
FULL commits before task acknowledgment. Keep the storage volume when recreating
the renderer. A process lock permits one API process per volume; Docker explicitly
uses one worker. Another state client can inspect the database without changing
live task statuses. On actual service startup, interrupted receipts become
definitively failed with `renderer_restarted`; completed results remain readable.

The worker records `provider_failed` for a bound failed receipt. Operator retry
then starts a new provider attempt while retaining the previous task receipt in
history. Each binding includes the attempt number, so old receipts cannot be
attached to a later attempt. Uncertain submissions still require reconciliation.

## Source manifest

Ship `app/**/*.py`, `app/services/data/azure_voices.json`, `main.py`,
`config.example.toml`, `LICENSE`, `Dockerfile.milo`,
`Dockerfile.milo.dockerignore`, `requirements.milo.txt`,
`scripts/prepare_resources.py`, this document, and the approved-scene tests.
The Azure voice JSON is runtime text data read by the existing voice service.
`SOURCE_MANIFEST.milo.txt` lists the exact repository-relative source paths.
Do not stage `config.toml`, `.env*`, `storage/`, `resource/`, `models/`, caches,
font binaries, generated previews, or the unrelated WebUI build.
