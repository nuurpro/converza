# Converza — Autonomous Revenue Team

**Website:** https://getconverza.com

Isolated **Node.js / TypeScript** microservice that acts as an autonomous **First Responder** for incoming brand direct messages.

Classifies each inbound message through the **shared Huawei MaaS Python client** (JSON Schema + Zod), then autonomously replies, hands off to a human, or ignores — using knowledge **only** from local `brand_context.json`.

## Quick start (single command)

```bash
cp .env.example .env   # once: configure CONVERZA_LLM_URL and LLM_SERVICE_API_KEY
./start.sh
```

`./start.sh` prefers Docker Compose (`docker compose up --build`); if Docker is unavailable it falls back to `npm install && npm start`.

| URL | Purpose |
|-----|---------|
| http://localhost:3000 | Minimal web UI to try the qualifier |
| http://localhost:3000/docs | Interactive API docs (Swagger UI) |
| http://localhost:3000/health | Health check |

## Core workflow

```
POST /v1/qualify  { "message": "…" }
        │
        ▼
┌───────────────────┐
│ Step 1 — Classify │  LLM + Zod schema (structured outputs)
│ LEAD_HOT          │
│ SUPPORT_REQUEST   │
│ SPAM_OR_TRASH     │
└─────────┬─────────┘
          │
   ┌──────┼──────────────────┐
   ▼      ▼                  ▼
 LEAD   SUPPORT            SPAM
   │      │                  │
   ▼      ▼                  ▼
 brand_context.json    HANDED_OFF msg    IGNORE (no reply)
 personalized reply
 + mock checkout link
```

### Step 1 — Intent classification

The LLM must return one of three strict intents:

| Intent | Meaning |
|--------|---------|
| `LEAD_HOT` | Explicit interest in services / pricing |
| `SUPPORT_REQUEST` | Technical issue or human assistance needed |
| `SPAM_OR_TRASH` | Negative feedback, bot spam, or irrelevance |

Enforced by the shared Huawei extraction endpoint and local Zod validation. Temperature is fixed at0.1 by the backend. No direct provider calls or provider fallback are used.

### Step 2 — Autonomous execution

| Intent | Status | Action |
|--------|--------|--------|
| `LEAD_HOT` | `REPLIED` | Pull `brand_context.json`, craft on-brand reply, append mock checkout link |
| `SUPPORT_REQUEST` | `HANDED_OFF` | Polite message — human agent is taking over |
| `SPAM_OR_TRASH` | `IGNORE` | `reply: null` — no outbound message |

## API

### `POST /v1/qualify`

**Request**

```json
{ "message": "Hey, how much for your marketing package?" }
```

Optional: `sender_id`, `channel` (default `"dm"`).

**Response (LEAD_HOT)** — raw structured JSON only:

```json
{
  "intent": "LEAD_HOT",
  "status": "REPLIED",
  "reply": "…personalized brand-tone reply…\n\nCheckout: https://getconverza.com/org/subscription/checkout…",
  "checkout_link": "https://getconverza.com/org/subscription/checkout?utm_source=dm&utm_medium=converza",
  "confidence": 0.93,
  "rationale": "User asked about pricing for a marketing package.",
  "brand": "Converza"
}
```

**Examples**

```bash
# Hot lead
curl -s http://localhost:3000/v1/qualify \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hey, how much for your marketing package?"}'

# Support
curl -s http://localhost:3000/v1/qualify \
  -H 'Content-Type: application/json' \
  -d '{"message":"My ads dashboard is broken, can a human help?"}'

# Spam
curl -s http://localhost:3000/v1/qualify \
  -H 'Content-Type: application/json' \
  -d '{"message":"Stop spamming me"}'
```

### `GET /health`

```bash
curl -s http://localhost:3000/health
```

### `GET /docs`

Swagger UI backed by `GET /openapi.json`. Open http://localhost:3000/docs after starting the server.

## Technical constraints (challenge checklist)

- **Strict schema outputs** — Zod schemas for API + LLM; Huawei JSON Schema validation; final API response is validated JSON only.
- **Context reliance** — All product, pricing, and tone knowledge loaded from `brand_context.json` (no remote KB).
- **Isolated microservice** — Express HTTP server, no monolith coupling.
- **Single-command spin-up** — `./start.sh`
- **API docs** — `/docs` (Swagger UI)

## Project layout

```
converza/
├── brand_context.json      # Local brand knowledge base (required)
├── src/
│   ├── index.ts            # HTTP server + /docs
│   ├── openapi.ts          # OpenAPI spec for Swagger UI
│   ├── routes/qualify.ts   # POST /v1/qualify
│   ├── schemas/            # Zod API + LLM schemas
│   ├── services/           # classifier, responder, qualifier pipeline
│   └── ui/                 # landing page + docs page
├── docker-compose.yml
├── Dockerfile
├── start.sh
└── .env.example
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CONVERZA_LLM_URL` | `http://127.0.0.1:8000` | Shared core API URL (Docker: use the core API service host) |
| `LLM_SERVICE_API_KEY` | — | Matches the dedicated core inference service credential |
| `PORT` | `3000` | HTTP port |

## Dev without Docker

```bash
cp .env.example .env
npm install
npm start          # or: npm run dev
```

## Repository

GitHub: https://github.com/ruslan-raxmonov/converza

## License

MIT

The qualifier returns candidate response JSON for local experimentation; it does not deliver channel messages. Use the active `Sleyz.sales_main` service for durable organization memory, HITL and confirmed delivery. Start the core API with its Huawei configuration before using this qualifier.
