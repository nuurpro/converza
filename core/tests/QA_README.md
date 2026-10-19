# Local browser QA harness

This harness runs the actual FastAPI memory/workflow routes and SQL migrations against a disposable local PostgreSQL database. Authentication, publisher delivery receipts, rendering and inference are deterministic QA fixtures. It never changes production auth or inference code.

Requirements: `psycopg2-binary`, local PostgreSQL and the core dependencies. Create an empty database named `test_converza_qa`. The adapter refuses databases outside the `test_converza` prefix. The server binds only127.0.0.1.

```powershell
$env:TEST_DSN='host=127.0.0.1 port=55440 user=postgres dbname=test_converza_qa'
python core/tests/qa_harness.py
```

Start Next.js with test-only environment overrides (do not edit committed environment files):

```powershell
$env:BACKEND_URL='http://127.0.0.1:8019'
$env:BACKEND_API_KEY='qa-loopback-backend-key'
$env:NEXT_PUBLIC_SUPABASE_URL='http://127.0.0.1:8019'
$env:NEXT_PUBLIC_SUPABASE_ANON_KEY='qa-anon'
# From Web:
npm run dev -- --hostname 127.0.0.1 --port 3029
```

From a page on the Next origin, fetch `http://127.0.0.1:8019/qa/session` and set each returned `storage` entry in localStorage. Reload. The server-minted token is intentionally test-only and accepted only by this harness. `GET /qa/session` also returns the stable organization and seeded Sleyz/Milo draft IDs. Do not reuse these tokens outside the local QA browser.

Seeded flows:

- Completed onboarding and paid owner access, identity exports, one current100 USD course, FAQ.
- AWAITING_HITL Sleyz reply linked to an actual test prospect, plus an AWAITING_HITL Milo announcement.
- After approving/editing a draft through the UI, call `POST /qa/publish/{draft_id}` to create a test delivery receipt through the same database transitions. The UI should receive PUBLISHED over SSE and expose explicit resolution only for the buyer-linked Sleyz draft.
- `POST /qa/index` runs the actual leased queue worker with a deterministic exact-quote extractor. Inspect search, indexing status and forgetting in the UI.

The real provider smoke is a separate configured command; mocked QA inference is not evidence of live Huawei connectivity. Stop the Python and Next processes when QA is complete. Test data is preserved in the disposable database for inspection; a fresh test database gives a fresh scenario.
