# Huawei text inference

All backend text generation uses this boundary. The approved Huawei integration
supersedes the historical local-Claude/Groq/KIE text paths. KIE image/video
rendering remains separate; the configured text model cannot perform vision QC.

Set `HUAWEI_MAAS_API_KEY` and `HUAWEI_MAAS_MODEL` to your Huawei deployment values.
`HUAWEI_MAAS_BASE_URL` defaults to
`https://api.modelarts-maas.ap-southeast-1.myhuaweicloud.com/v1`.
Configuration is read lazily so importing backend modules never needs secrets.
There is no provider fallback or model default.

The configured Singapore deployment uses
`HUAWEI_MAAS_BASE_URL=https://api-ap-southeast-1.modelarts-maas.com/v2`.
Set this explicitly: the historical default hostname failed DNS verification.
The configured model is `deepseek-v4.1-flash`, matching the working Hermes
deployment (without an extra `deepseek-` prefix).

When diagnosing HTTP 401, compare the exact saved values with an existing working
client before requesting a replacement key. In this workspace the core key had
one extra trailing character compared with Hermes's existing key. Copying that
existing value exactly fixed authentication; no new key was needed. Keep all
credential comparisons local and never print the key or authorization header.

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH='core'
python -m unittest discover -s core/tests -p test_huawei_llm.py -v
python -m services.llm.smoke --live
python -m services.llm.evals --live
```

Smoke and eval commands load `core/.env` without overriding process settings.
Exit 2 means missing configuration, exit 1 means a failed deployment/check, and
exit 0 means success. Without `--live`, no deployment calls are made. Never paste
credentials into source or command arguments. Live evaluation needs a 100% pass
rate across five exact-output cases: exact quotes, Unicode quote fidelity,
unresolved conversations, identity edits, and stale price rejection.

## Public contract

- `complete(messages, *, operation='reasoning', tools=None, **kwargs)` returns an
  OpenAI SDK `ChatCompletion`. Tool arguments are JSON parsed and checked against
  each declared schema before returning.
- `complete_text(...)` returns nonempty visible text or raises
  `StructuredOutputError`.
- `complete_json(..., operation='extraction', schema=None, validator=None)` parses
  an object/array, optionally checks JSON Schema and/or a Pydantic/callable
  validator. Invalid, truncated, or scalar outputs fail closed. It does not rely
  on provider-specific JSON response-format support. The caller supplies a JSON
  domain instruction and schema. The shared client supplies the JSON-only output
  instruction and includes any JSON Schema in the model request as well as
  validating the response locally. Exact quote/domain validation belongs to
  the indexer before persistence.
- `stream(...)` yields SDK chunks. `core.llm.stream_gemini` retains the legacy
  text-token generator name. `legacy_complete` adapts existing Anthropic-shaped
  tool loops to Huawei function calls without importing Anthropic.
- `call_engine(system_prompt, user_input, tools=None, *, operation='reasoning')`
  keeps the existing plain-text interface. Tool loops should use `complete` or
  `legacy_complete` when they need tool results.

The `creative` operation uses temperature 0.7; extraction, tools, reasoning and
all other operations use 0.1. The deployment, provider and temperature cannot be
overridden per request. 429/503 receive at most three retries after the initial
request, with 1/2/4-second exponential delay plus jitter. Retry-After (seconds or
HTTP date) is respected up to a 30-second bound. SDK retries are disabled. A
stream can retry only before visible text or tool arguments have been emitted;
retrying a partial response could duplicate caller-visible content.

Logs contain operation, model, latency, retry count and usage, never prompts,
buyer text or API keys. Vision requests raise `UnsupportedCapabilityError`.
The legacy image/video pipeline returns failure when QC is unavailable instead
of silently switching providers or declaring an unchecked frame approved.

Restart the backend and indexer after installing updated requirements and setting
Huawei environment variables. The standalone legacy manager locates the shared core service automatically;
standalone Sleyz/Milo modules require the repository root on `PYTHONPATH`.
