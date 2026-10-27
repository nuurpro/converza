# Active sales service

Run from the repository root after applying migrations 001 through 007:

```powershell
python -m pip install -r core/requirements.txt
python -m uvicorn Sleyz.sales_main:app --host 127.0.0.1 --port 8001
```

Run the durable inbox and learning worker in a separate supervised process:

```powershell
$env:PYTHONPATH='core'
python -m services.sleyz
```

The entry point loads `core/.env` without overriding existing
process environment. Set `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SALES_BOT_TOKEN`,
`HUAWEI_MAAS_API_KEY`, `HUAWEI_MAAS_MODEL`, `SALES_WEBHOOK_SECRET` and
`MANAGER_BOT_TOKEN`. Register Telegram's webhook `/webhook` with its `secret_token`
set to `SALES_WEBHOOK_SECRET`. The bot token must match an organization's
`tg_connections.bot_token`; shared tokens across organizations are unsupported.
Business connection updates must come from the stored workspace owner.

The manager bot token posts review cards in the stored organization's
`group_chat_id`. Telegram bots cannot send review messages to one another. If the
group/token is unconfigured, the draft stays reviewable in the dashboard and a
sanitized configuration warning is logged. The manager and sales services must
share the same database and updated workflow migrations.

A buyer message and `PENDING_DRAFT` commit atomically under the organization and
prospect before the webhook acknowledges receipt. The worker claims generation,
loads shared identity/search/catalog and
the latest twenty prospect messages, then calls Huawei. Failures retain a draft
with a sanitized generation error. Success transitions to `AWAITING_HITL` before
notification. No reply is sent until approval/edit. Every delivery goes through
the shared platform dispatcher, with authoritative stored text and destinations,
receipt verification and explicit handling of uncertain sends. Resolution remains
a separate owner action.

Docker uses repository-root build context and explicit source copies:

```powershell
docker compose --env-file web/.env.local build sleyz-ingress
docker compose --env-file web/.env.local --profile workers up -d sleyz-ingress sleyz-worker
```

No environment files are copied into the image. Kubernetes deployment uses the
`converza-sales-runtime` Secret; `bridge/base/runtime-secret.template.yaml` lists
required key names without values. Existing exposed credentials from historical
manifests must be rotated before deployment. Do not apply the empty template over
a populated runtime Secret.

Local deterministic checks:

```powershell
$env:PYTHONPATH='core'
python -m unittest discover -s core/tests -p test_sleyz_service.py -v
```

A restart of the sales ingress, worker, core API and any older manager process is
required. Deploy the updated frontend too. See the
[SLEYZ service contract and operations](../core/services/sleyz/README.md) for
commerce setup, simulation, recovery, learning and validation commands.

## Instagram Login connection setup

Use a professional Instagram account connected through Instagram Login. Keep the
account ID and access token in the server environment:

```text
INSTAGRAM_APP_SECRET=<Meta app secret>
INSTAGRAM_VERIFY_TOKEN=<random webhook verification token>
INSTAGRAM_CONNECTIONS={"123456789":{"org_id":"workspace UUID","access_token":"server-only token"}}
INSTAGRAM_GRAPH_VERSION=v26.0
```

Set the Meta webhook callback to the public sales service URL followed by
`/webhooks/instagram`, enter `INSTAGRAM_VERIFY_TOKEN`, and subscribe to message
events. The callback verifies the GET challenge and checks POST signatures over
the exact raw body. Messages are routed by the connected account ID; client
provided organization IDs cannot route real Instagram messages. A connection
must identify exactly one organization. Server-side configuration changes take
effect without exposing tokens to the workspace UI.

Follow Meta's [webhook setup](https://developers.facebook.com/documentation/instagram-platform/webhooks/setup)
and [Instagram Login messaging instructions](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api).
Complete app access/review and token setup for the account before enabling it.
The authenticated `/api/sleyz/connections?org_id=...` endpoint reports configured
account IDs without returning credentials. This endpoint reports configuration,
not token validity or app review status.

Instagram publication uses the stored connected account and buyer destination,
requires human approval, verifies the returned recipient/message receipt, and
allows delivery only within 24 hours of the latest inbound message from that
buyer on that connection. A new buyer message opens a fresh window. Failed
network requests whose delivery is uncertain remain ambiguous and need receipt
reconciliation before any resend. Simulated drafts cannot send real messages.
